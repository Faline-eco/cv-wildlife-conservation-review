#!/usr/bin/env python3
import argparse
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from review.genai_client import LLMClient
from review.post_process.rerun.cli import cv_in_wc_topic_imaging_method_new, cv_in_wc_topic_light_spectra_text_new, \
    cv_in_wc_topic_light_spectra_images_new
from review.settings import Settings
from review.topics import *
from review.pipeline import PaperReviewPipeline

# --- imports from your project (adjust these to your package/module layout) ---
# from your_project.llm_client import LLMClient
# from your_project.pipeline import PaperReviewPipeline

# If your code lives alongside this script, uncomment the direct imports:
# from llm_client import LLMClient
# from pipeline import PaperReviewPipeline

# --- helpers -----------------------------------------------------------------

def find_pdfs(folder: Path, recursive: bool = True) -> List[Path]:
    pattern = "**/*.pdf" if recursive else "*.pdf"
    files = sorted(folder.glob(pattern))
    return [f for f in files if f.is_file()]

def infer_year_from_filename(stem: str) -> Optional[int]:
    """
    Lightweight heuristic: pick the first plausible 4-digit year (1900-2099) in the filename stem.
    Examples:
      'Smith_2021_RemoteSensing' -> 2021
      '10.1371journal.pone.0239504' -> None
    """
    m = re.search(r"(19|20)\d{2}", stem)
    if not m:
        return None
    try:
        year = int(m.group(0))
        return year
    except Exception:
        return None

def load_topics(topics_path: Optional[Path]) -> List[Tuple[str, str]]:
    """
    Topics must be List[tuple] for the pipeline. We support:
      - JSON file:  either [["topic","prompt"], ...] or [{"name":..., "prompt":...}, ...]
      - CSV/TXT:    each line "topic|prompt"
    If not provided, we return an empty list (pipeline handles it).
    """
    if not topics_path:
        return []

    if not topics_path.exists():
        logging.warning(f"Topics file not found: {topics_path}. Proceeding with empty topics.")
        return []

    if topics_path.suffix.lower() == ".json":
        data = json.loads(topics_path.read_text(encoding="utf-8"))
        topics: List[Tuple[str, str]] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "name" in item and "prompt" in item:
                    topics.append((str(item["name"]), str(item["prompt"])))
                elif isinstance(item, list) and len(item) >= 2:
                    topics.append((str(item[0]), str(item[1])))
        return topics

    # Simple line format: topic|prompt
    raw = topics_path.read_text(encoding="utf-8").splitlines()
    topics: List[Tuple[str, str]] = []
    for line in raw:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            k, v = line.split("|", 1)
            topics.append((k.strip(), v.strip()))
        else:
            # If only a single token is provided, use it as both name and prompt
            topics.append((line, line))
    return topics

def build_maps(files: List[Path],
               doi_csv: Optional[Path],
               infer_years: bool, static_year: Optional[int] = None) -> Tuple[Dict[str, str], Dict[str, int]]:
    """
    Builds:
      - doi_map:     { pdf_stem_lower -> doi_string }
      - year_map:    { doi_string -> year_int }
    If no DOI info is available, doi_map entries are empty strings and year_map stays empty.
    Optionally infer year from filename to use when DOI is present (or store under empty DOI otherwise).
    """
    doi_map: Dict[str, str] = {}
    year_map: Dict[str, int] = {}

    # Optional: load a CSV (or TSV) with columns: stem,doi,year
    if doi_csv and doi_csv.exists():
        text = doi_csv.read_text(encoding="utf-8").splitlines()
        header = True
        for line in text:
            if header and ("," in line or "\t" in line):
                header = False
                # fall-through: still parse this line in case header lacked labels
            parts = re.split(r"[,\t]", line.strip())
            if len(parts) < 2:
                continue
            stem = parts[0].strip().lower()
            doi = parts[1].strip()
            doi_map[stem] = doi
            if len(parts) >= 3 and parts[2].strip().isdigit():
                year_map[doi] = int(parts[2].strip())

    # Ensure every file stem has an entry in doi_map (empty if unknown)
    for f in files:
        stem = f.stem.lower()
        if stem not in doi_map:
            doi_map[stem] = ""  # unknown DOI

        # Optional filename year inference:
        if static_year is not None:
            year_map[doi_map[stem]] = static_year
        elif infer_years:
            y = infer_year_from_filename(f.stem)
            # Only store inferred year if we have a DOI (what the pipeline expects)
            # If DOI is unknown (""), the pipeline will look up year_map with "", which is harmless.
            if y is not None and doi_map[stem] and doi_map[stem] not in year_map:
                year_map[doi_map[stem]] = y

    return doi_map, year_map

# --- CLI & runner ------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run PaperReviewPipeline on a folder of PDFs (no DOI/Zotero required)."
    )
    p.add_argument("--pdf-dir", type=Path, help="Folder containing PDFs (searched recursively).", default=Path(r"D:\LiteratureReviewCVinWC\review_input\cv4animals"))
    p.add_argument("--target-dir", type=Path, default=Path(r"D:\LiteratureReviewCVinWC\review_output\cv4animals"),
                   help="Directory for pipeline result caches (JSON).")
    p.add_argument("--doi-csv", type=Path, default=None,
                   help="Optional CSV/TSV with columns: stem,doi,year. "
                        "stem should match the PDF filename (without extension).")
    p.add_argument("--infer-year-from-filename", action="store_true",
                   help="Try to infer a 4-digit year from PDF filenames (heuristic).", default=False)
    p.add_argument("--static-year", default=2024, type=int,
                   help="Static year for all input files.",)
    p.add_argument("--concurrency", type=int, default=4, help="Max concurrent LLM jobs.")
    p.add_argument("--non-recursive", action="store_true", help="Do not recurse into subfolders.")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level.")

    p.add_argument("--temperature", type=float, default=None, help="Temperature for LLMClient.")

    return p.parse_args()

def read_prompt_file(path: Optional[Path], fallback: str) -> str:
    if path and path.exists():
        return path.read_text(encoding="utf-8").strip()
    return fallback

async def main_async(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)-8s | %(message)s",
    )

    pdf_dir: Path = args.pdf_dir
    if not pdf_dir.exists():
        raise SystemExit(f"PDF directory does not exist: {pdf_dir}")

    files = find_pdfs(pdf_dir, recursive=not args.non_recursive)
    if not files:
        logging.warning(f"No PDFs found in {pdf_dir}. Nothing to do.")
        return

    topics = [
        cv_in_wc_topic_species_text, cv_in_wc_topic_species_images, cv_in_wc_topic_country,
        cv_in_wc_topic_imaging_method, cv_in_wc_topic_light_spectra_text, cv_in_wc_topic_light_spectra_images,
        cv_in_wc_topic_cv_tasks, cv_in_wc_topic_cv_algorithms,
        cv_in_wc_topic_imaging_method_new, cv_in_wc_topic_light_spectra_text_new,
        cv_in_wc_topic_light_spectra_images_new
    ]

    habitat_prompt = cv_in_wc_HABITAT_PROMPT

    dataset_prompt = cv_in_wc_DATASET_PROMPT

    doi_map, year_map = build_maps(files, args.doi_csv, args.infer_year_from_filename, args.static_year)

    s = Settings()
    llm = LLMClient(s.api_keys, s.light_model_name, s.strong_model_name, rpm=s.rpm, use_native_json_schema=s.use_native_json_schema)

    pipeline = PaperReviewPipeline(llm=llm, target_dir=args.target_dir)  # type: ignore[name-defined]

    logging.info(f"Discovered {len(files)} PDF(s). Starting pipeline…")
    results = await pipeline.run(
        files=files,
        doi_map=doi_map,
        year_map=year_map,
        topics=topics,
        habitat_prompt=habitat_prompt,
        dataset_prompt=dataset_prompt,
        concurrency=args.concurrency,
    )

    # Persist a combined results file alongside the per-paper caches.
    # combined_path = args.target_dir / "combined_results.json"
    # Filter out empty dicts returned on errors
    # payload = [r for r in results if isinstance(r, dict) and r]
    # combined_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # logging.info(f"Wrote combined results to: {combined_path}")

def main() -> None:
    args = parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted by user.")

if __name__ == "__main__":
    main()
