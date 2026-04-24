# wildcv_review/pipeline.py
import asyncio, json, logging
import traceback
from pathlib import Path
from typing import Dict, List
import pandas as pd

from iucn.utils import root_presence_map
from review.genai_client import LLMClient
from review.extractors import check_topic, get_datasets, get_habitats, extract_topics
from review.schemas import IsCVWildlife

class PaperReviewPipeline:
    def __init__(self, llm: LLMClient, target_dir: Path):
        self.llm = llm
        self.target_dir = target_dir
        self.target_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, stem: str) -> Path:
        return self.target_dir / f"{stem}.json"

    async def _process_one(self, pdf_path: Path, doi: str, year: int, topics: List[tuple], habitat_prompt: str, dataset_prompt: str) -> Dict:
        stem = pdf_path.stem
        cache = self._cache_path(stem)
        if cache.exists():
            try:
                with cache.open(encoding="UTF-8") as f:
                    cached = json.load(f)
                    logging.info(f"Skipping, already processed: {pdf_path}")
                    return cached
            except Exception as e:
                logging.warning(f"Something went wrong with result cache: {cache}")
                logging.warning(traceback.format_exc())

        logging.info(f"Checking if computer vision in wildlife study")
        topic_flags: IsCVWildlife = await check_topic(self.llm, str(pdf_path))
        result: Dict = {
            "doi": doi, "year": year,
            "is_computer_vision_in_wildlife_study": topic_flags.is_computer_vision_in_wildlife_study,
            "is_computer_vision_in_wildlife_study_review": topic_flags.is_review,
            "is_computer_vision_in_wildlife_study_explanation": topic_flags.explanation,
        }

        if topic_flags.is_computer_vision_in_wildlife_study and not topic_flags.is_review:
            logging.info(f"Checking topics")
            result.update(await extract_topics(self.llm, str(pdf_path), topics))
            logging.info(f"Checking datasets")
            result["Dataset"] = (await get_datasets(self.llm, str(pdf_path), dataset_prompt))
            logging.info(f"Checking habitats")
            habitats, verification = (await get_habitats(self.llm, str(pdf_path), habitat_prompt))
            result["Habitat"] = habitats.model_dump()
            result["HabitatVerification"] = verification
            result["ParentHabitat"] = root_presence_map(habitats)

        with cache.open("w", encoding="utf-8") as f:
            logging.info(f"Writing results to {cache}")
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    async def run(self, files: List[Path], doi_map: Dict[str,str], year_map: Dict[str,int], topics: List[tuple], habitat_prompt: str, dataset_prompt:str, concurrency: int = 4):
        await self.llm.clean_up_buckets()
        already_processed = set()
        sem = asyncio.Semaphore(concurrency)
        async def guarded(f: Path):
            # todo remove
            # if f.name != "10.1371journal.pone.0239504.pdf":
            #     return {}

            if f.name in already_processed:
                logging.info(f"Already processed, skipping: {f}")
                return {}

            try:
                async with sem:
                    logging.info(f"Processing: {f}")
                    doi = doi_map.get(f.stem.lower(), "")
                    year = year_map.get(doi, None)
                    res = await self._process_one(f, doi, year, topics, habitat_prompt, dataset_prompt)
                    logging.info(f"Processed: {f}")
                    already_processed.add(f.name)
                    logging.info(f"Result: {res}")
                    await self.llm.clean_up_buckets()
                    return res
            except Exception as e:
                logging.error(f"Error processing {f}: {e}")
                logging.error(traceback.format_exc())
                return {}
        return await asyncio.gather(*[guarded(f) for f in files])
