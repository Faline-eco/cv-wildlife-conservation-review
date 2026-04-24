import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from review.extractors import extract_topics
from review.genai_client import LLMClient
from review.post_process.logger import re_run_logger as log
from review.post_process.util import iterate_jsons_from_folder
from review.schemas import TopicSpec
from review.settings import Settings
# from review.topics import cv_in_wc_topic_imaging_method

import asyncio
import json
from pathlib import Path

# --- helpers for thread-offloaded file I/O (no extra deps) ---

def _read_json_sync(fp: Path):
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except UnicodeDecodeError:
        with open(fp, "r") as f:
            return json.load(f)

def _write_json_sync(fp: Path, data: dict):
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

async def read_json(fp: Path):
    return await asyncio.to_thread(_read_json_sync, fp)

async def write_json(fp: Path, data: dict):
    await asyncio.to_thread(_write_json_sync, fp, data)

# --- core worker ---

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
    async with sem:  # bound total concurrency
        # Read JSON (thread offloaded)
        try:
            paper = await read_json(fp)
        except Exception as e:
            log.error(f"Error reading {fp}")
            log.error(e)
            return  # skip this file

        # Filter condition
        if not (paper.get("is_computer_vision_in_wildlife_study") is True and
                paper.get("is_computer_vision_in_wildlife_study_review") is False):
            log.info(f"Skipping {fp}: not related")
            return

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
            # extract_topics is assumed to be async; just await it
            updates = await extract_topics(llm, str(files[fp.stem]), actual_topics)
            # Merge + write back (thread offloaded)
            paper.update(updates)
            await write_json(fp, paper)
            log.info(f"Processed {fp}: {[t.key for t in actual_topics]}")
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

imaging_methods = ["Autonomous Underwater Vehicle (AUV)", "Remotely operated underwater vehicle (ROV)", "Ground Robot",
                                                             "Animal-mounted Camera", "Unmanned aerial vehicle (UAV; e.g. drone)", "Crewed aerial vehicle (CAV; e.g. plane, helicopter)",
                                                             "Satellite", "Camera Trap (temperature- or motion triggered)", "Time-lapse Camera",
                                                             "Camera (manually triggered; e.g. Smartphone, System Camera, SLR Camera)", "Depth Sensor / Lidar",
                                                             "Video Camera (e.g. CCTV Camera, Action Camera, PTZ Camera)", "Event Camera", "Acoustic Camera", "Other"]

cv_in_wc_topic_imaging_method_new = TopicSpec(key="Imaging Method (new)",
                                          prompt="Extract imaging methods that have been used in THIS paper's methodology (not related work).",
                                              allowed_vocab=imaging_methods)

bands = [
    "RGB (visible)",
    "Depth / LiDAR",
    "Grayscale",
    "Hyperspectral",
    "Near Infrared (NIR)",
    "Red-edge (specialised NIR)",
    "Short-wave Infrared (SWIR)",
    "Long-wave Infrared / Thermal (LWIR)",
    "Panchromatic",
    "Radar / Synthetic-Aperture Radar (SAR)",
    "Acoustic",
    "Ultraviolet (UV-A/B)",
    "Mid-wave Infrared (MWIR)",
    "Polarimetric SAR (PolSAR)",
    "Passive Microwave Radiometry",
    "Active Imaging Sonar (multibeam)",
    "Red Band",
    "Blue Band",
    "Green Band",
    "Other"
]

cv_in_wc_topic_light_spectra_text_new = TopicSpec(key="Light Spectra (Text) (new)",
                                              prompt="Extract used light spectra mentioned in THIS paper's methodology"
                                                     "(not related work).",
                                              allowed_vocab=bands)
cv_in_wc_topic_light_spectra_images_new = TopicSpec(key="Light Spectra (Images) (new)",
                                                prompt="From sample images, infer light spectra used in THIS paper's methodology (not related work).",
                                                require_images_only=True,
                                                allowed_vocab=bands)

if __name__ == '__main__':
    dataset_folder = r"D:\LiteratureReviewCVinWC\review_output\20250731\utf8"
    topics_to_re_run = [
        # cv_in_wc_topic_imaging_method,
        cv_in_wc_topic_imaging_method_new,
        cv_in_wc_topic_light_spectra_text_new,
        cv_in_wc_topic_light_spectra_images_new
    ]

    include_new_topics = True
    override_already_existing_topics = False

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
