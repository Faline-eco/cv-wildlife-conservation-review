# wildcv_review/cli.py
import argparse
import asyncio, logging, json
import os.path
from datetime import datetime
from pathlib import Path
import pandas as pd

from review.logging_conf import setup_logging, get_logger
from review.settings import Settings
from review.genai_client import LLMClient
from review.pipeline import PaperReviewPipeline
from review.storage import Storage
from review.topics import *


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="WildCV literature extractor")
    p.add_argument("--force", action="store_true",
                   help="Proceed even if config drift is detected (overrides safety check).")
    p.add_argument("--rpm", type=int, default=None, help="Override requests-per-minute limit.")
    p.add_argument("--concurrency", type=int, default=None, help="Max number of PDFs processed concurrently.")
    p.add_argument("--json-logs", action="store_true", help="Emit JSON logs when possible.")
    p.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR).")
    p.add_argument("--log-file", default=None, help="Optional rotating log file path.")
    p.add_argument("--export-csv", type=Path, default=None, help="Optional path to write a summary CSV.")
    return p.parse_args()

def main():
    args = parse_args()
    setup_logging(level=args.log_level, json_logs=args.json_logs, log_file=args.log_file)
    log = get_logger(__name__)

    s = Settings()
    if s.review_to_continue is not None:
        target_folder = os.path.join(s.target_base_folder, s.review_to_continue)
    else:
        now = datetime.now()
        target_folder = os.path.join(s.target_base_folder, f"{now.year:04d}{now.month:02d}{now.day:02d}")
    s.target_base_folder = target_folder
    logging.basicConfig(level=logging.INFO)

    TOPICS = [
        cv_in_wc_topic_species_text, cv_in_wc_topic_species_images, cv_in_wc_topic_country,
        cv_in_wc_topic_imaging_method, cv_in_wc_topic_light_spectra_text, cv_in_wc_topic_light_spectra_images,
        cv_in_wc_topic_cv_tasks, cv_in_wc_topic_cv_algorithms,
    ]
    HABITAT_PROMPT = cv_in_wc_HABITAT_PROMPT
    DATASET_PROMPT = cv_in_wc_DATASET_PROMPT

    if args.rpm is not None:
        s.rpm = args.rpm
    if args.concurrency is not None:
        s.concurrent_files = args.concurrency

    store = Storage(Path(s.target_base_folder))

    current_config = {
        "light_model": s.light_model_name,
        "strong_model": s.strong_model_name,
        "topics": [t.prompt for t in TOPICS],
        "habitat_prompt": HABITAT_PROMPT,
        "use_native_json_schema": s.use_native_json_schema,
        "rpm": s.rpm,
        "concurrency": s.concurrent_files,
    }

    # Drift check
    if store.config_has_drift(current_config) and not args.force:
        log.error("Config drift detected. Re-run with --force to proceed.")
        log.error(store.config_diff(current_config))
        return

    # Save snapshot (writes both normalized config and hash)
    store.save_config_snapshot(config=current_config, extra={"invoked_by": "cli", "version": "1.0.0"})

    if store.config_has_drift(current_config):
        diff = store.config_diff(current_config)
        log.warning("Config drift: added=%d removed=%d changed=%d",
                    len(diff["added"]), len(diff["removed"]), len(diff["changed"]))
        # Optionally log some details:
        for path, ch in list(diff["changed"].items())[:10]:
            log.info("Changed %s: %r -> %r", path, ch["from"], ch["to"])



    doi_df = pd.read_csv(s.dois_file_path, sep=";")
    dois = [d.replace("http://doi.org", "").replace("https://doi.org", "").replace("/", "").lower() for d in doi_df["doi"].dropna().astype(str)]
    years = doi_df["year"].tolist()
    doi_to_year = dict(zip(doi_df["doi"].astype(str), years))

    # Discover PDFs present in Zotero storage that match your DOIs
    files, file_to_doi = [], {}
    for sub in Path(s.zotero_storage).iterdir():
        if not sub.is_dir():
            continue
        for pdf in sub.glob("*.pdf"):
            stem = pdf.stem
            try:
                idx = dois.index(stem.lower())
                file_to_doi[stem.lower()] = doi_df["doi"].iloc[idx]
                files.append(pdf)
            except ValueError:
                pass

    llm = LLMClient(s.api_keys, s.light_model_name, s.strong_model_name, rpm=s.rpm, use_native_json_schema=s.use_native_json_schema)

    pipe = PaperReviewPipeline(llm, Path(s.target_base_folder))

    results = asyncio.run(pipe.run(files, file_to_doi, doi_to_year, TOPICS, HABITAT_PROMPT, DATASET_PROMPT, concurrency=s.concurrent_files))
    # Optionally write a summary CSV here
    if args.export_csv:
        store.export_summary_csv(results, args.export_csv)
        log.info("Wrote summary CSV to %s", args.export_csv)

if __name__ == "__main__":
    main()
