import json

from review.genai_client import LLMClient
from review.post_process.logger import re_run_logger as log
from review.post_process.rerun.cli import bands, imaging_methods, write_json, read_json
from review.post_process.util import iterate_jsons_from_folder
from review.schemas import TopicSpec
from review.settings import Settings
from google.genai import types as genai_types

import asyncio
from pathlib import Path

_SYSTEM_PROMPT = (
    "You are a technical assistant. Assign the given term to one or None of the given categories.\n"
    "Return ONLY a JSON array of strings, one output per input (use empty string if unknown)."
)

async def _process_one_file(
    fp: Path,
    *,
    llm,
    files,  # mapping used like files[fp.stem]
    topics_to_re_run,
    include_new_topics: bool,
    override_already_existing_topics: bool,
    log,
    sem: asyncio.Semaphore,
):
    schema = genai_types.Schema(
        type=genai_types.Type.ARRAY,
        items=genai_types.Schema(type=genai_types.Type.STRING),
    )
    async with sem:  # bound total concurrency
        # Read JSON (thread offloaded)
        try:
            paper = await read_json(fp)
        except Exception as e:
            log.error(f"Error reading {fp}")
            log.error(e)
            return  # skip this file

        # Decide which topics to run
        actual_topics = []
        for topic in topics_to_re_run:
            contained_topic = paper.get(topic.key)
            if contained_topic is None and include_new_topics:
                actual_topics.append(topic)
            if contained_topic is not None and override_already_existing_topics:
                actual_topics.append(topic)

        if not actual_topics:
            log.info(f"Skipping {fp}: nothing to do")
            return

        # Run extraction (concurrently across files)
        try:
            for topic in actual_topics:
                verified_updates = []
                unverified_updates = []
                old_topic = paper.get(topic.old_key)
                if old_topic is not None:
                    if isinstance(old_topic, dict):
                        if len(old_topic.get("verified")) > 0:
                            verified = "[" + ", ".join(old_topic.get("verified")) + "]"
                        else:
                            verified = None
                    else:
                        verified = "[" + old_topic + "]"

                    if verified is not None:
                        content = topic.prompt.replace("{{old}}", verified)
                        if topic.allowed_vocab is not None and len(topic.allowed_vocab) > 0:
                            content += "\n"
                            content += "Allowed values are: ["
                            content += ", ".join(topic.allowed_vocab)
                            content += "]"
                        text = await llm.generate(
                            contents=content,
                            system_instruction=_SYSTEM_PROMPT,
                            response_model=schema,
                            use_strong_model=True,
                        )
                        arr = json.loads(text)
                        if not isinstance(arr, list):
                            raise ValueError("Model did not return a JSON array.")
                        while "" in arr:
                            arr.remove("")
                        verified_updates.extend(arr)

                    if isinstance(old_topic, dict) and len(old_topic.get("unverified")) > 0:
                        unverified = "[" + ",".join(old_topic.get("unverified")) + "]"
                        content = topic.prompt.replace("{{old}}", unverified)
                        if topic.allowed_vocab is not None and len(topic.allowed_vocab) > 0:
                            content += "\n"
                            content += "Allowed values are: ["
                            content += ", ".join(topic.allowed_vocab)
                            content += "]"
                        text = await llm.generate(
                            contents=content,
                            system_instruction=_SYSTEM_PROMPT,
                            response_model=schema,
                            use_strong_model=True,
                        )
                        arr = json.loads(text)
                        if not isinstance(arr, list):
                            raise ValueError("Model did not return a JSON array.")
                        while "" in arr:
                            arr.remove("")
                        unverified_updates.extend(arr)
                paper[topic.key] = {"verified": verified_updates, "unverified": unverified_updates}
            await write_json(fp, paper)
            log.info(f"Processed {fp}: {[f'{t.key}: {paper[t.key]}' for t in actual_topics]}")
        except Exception as e:
            print(f"Error processing {fp}: {e}")

# --- orchestrator ---

async def process_all_parallel(
    dataset_folder: str | Path,
    *,
    llm,
    files,
    topics_to_re_run,
    include_new_topics: bool,
    override_already_existing_topics: bool,
    log,
    max_concurrency: int = 8,   # tune this as you like
):
    sem = asyncio.Semaphore(max_concurrency)

    tasks = []
    for fp in iterate_jsons_from_folder(Path(dataset_folder)):
        tasks.append(
            asyncio.create_task(
                _process_one_file(
                    fp,
                    llm=llm,
                    files=files,
                    topics_to_re_run=topics_to_re_run,
                    include_new_topics=include_new_topics,
                    override_already_existing_topics=override_already_existing_topics,
                    log=log,
                    sem=sem,
                )
            )
        )

    # Run with best-effort completion (don't cancel all on first error)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # Optional: surface unexpected exceptions
    for r in results:
        if isinstance(r, Exception):
            log.error(f"Unhandled error in a worker: {r}")

cv_in_wc_topic_imaging_method_new = TopicSpec(key="Imaging Method (Text) (new)",
                                              prompt="Assign the given Imaging methods to one of the the given values allowed: {{old}}",
                                              allowed_vocab=imaging_methods, old_key="Imaging Method")

cv_in_wc_topic_light_spectra_text_new = TopicSpec(key="Light Spectra (Text) (new)",
                                              prompt="Assign the given Light spectra to one of the the given values allowed: {{old}}",
                                              allowed_vocab=bands, old_key="Light Spectra (Text)")
if __name__ == '__main__':
    dataset_folder = r"D:\LiteratureReviewCVinWC\review_output\manual"
    topics_to_re_run = [
        cv_in_wc_topic_imaging_method_new,
        cv_in_wc_topic_light_spectra_text_new,
    ]

    include_new_topics = True
    override_already_existing_topics = True

    s = Settings()
    files = {}
    for sub in Path(s.zotero_storage).iterdir():
        if not sub.is_dir():
            continue
        for pdf in sub.glob("*.pdf"):
            stem = pdf.stem
            files[stem] = pdf

    llm = LLMClient(s.api_keys, s.light_model_name, s.strong_model_name, rpm=s.rpm, use_native_json_schema=s.use_native_json_schema)

    asyncio.run(process_all_parallel(
        dataset_folder,
        llm=llm,
        files=files,
        topics_to_re_run=topics_to_re_run,
        include_new_topics=include_new_topics,
        override_already_existing_topics=override_already_existing_topics,
        log=log,
        max_concurrency=8,
    ))
