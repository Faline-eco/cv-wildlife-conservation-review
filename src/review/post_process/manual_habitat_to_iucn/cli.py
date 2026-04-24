import asyncio
import json
from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel, ValidationError

from iucn.gemini_iucn_models import gemini_safe_model
from iucn.iucn_models import IUCNHabitats
from iucn.utils import root_presence_map
from review.extractors import _build_model_map, _fill_missing_booleans
from review.genai_client import LLMClient
from review.post_process.util import iterate_jsons_from_folder
from review.post_process.logger import transform_logger as log
from review.settings import Settings

# ──────────────────────────────────────────────────────────────────────────────
HABITAT_PROMPT = """
⚠️ Focus ONLY on the '{{human_label}}' habitat group of the IUCN schema.

Habitats: {{habitats}}
Species: {{species}}

Rules
1. Set every Boolean field explicitly (True / False).
2. If a habitat string clearly matches one of the IUCN habitats, set that field to **True**.
3. If no adequate match exists, leave every field **False**.
4. If a habitat string is ambiguous, look at the species list for ecological hints (e.g., *Carcharhinus leucas* ⇒ likely “Rivers” & “Estuaries”; *Felis catus* ⇒ “Artificial/Terrestrial – Urban areas”).
5. Never invent extra keys, change field names, or omit required fields.
6. Output MUST be valid JSON (no comments, no trailing commas).
"""

# ──────────────────────────────────────────────────────────────────────────────
# Configurable knobs
MAX_PARALLEL_LLM  = 10          # tune to taste / RPM
MAX_PARALLEL_FILE = 4           # concurrent papers to process
SYSTEM_MSG = ("You are an expert wildlife ecologist and data modeller. "
              "Your job is to translate arbitrary, human-written habitat "
              "descriptions into the official IUCN Habitat Classification "
              "Scheme (v3.1) and return a JSON object that exactly matches "
              "the provided schema.")

# ──────────────────────────────────────────────────────────────────────────────
def build_prompt(paper: dict, human_label: str) -> str:
    """Fill the habitat prompt template for a given group."""
    return (HABITAT_PROMPT
            .replace("{{habitats}}", ", ".join(paper["Habitat (Manual)"]["verified"]))
            .replace("{{species}}",  ", ".join(paper["Species (Text)"]["verified"]))
            .replace("{{human_label}}", human_label))


async def translate_group(
    llm: LLMClient,
    sem: asyncio.Semaphore,
    paper: dict,
    group_key: str,
    model_cls: BaseModel,
    human_label: str,
    max_retries: int = 5
) -> tuple[str, BaseModel]:
    """
    Single habitat-group → LLM → validated Pydantic object.
    Returns (group_key, parsed_model)
    """
    prompt = build_prompt(paper, human_label)
    schema_only = gemini_safe_model(model_cls)

    retries = 0
    text = None

    while text is None and retries < max_retries:
        async with sem:  # honour global RPM / concurrency
            log.info(f"--- Translate {human_label}")
            text = await llm.generate(
                [prompt],
                system_instruction=SYSTEM_MSG,
                response_model=schema_only,
            )
            retries += 1

    # Validation / post-processing
    try:
        parsed = model_cls.model_validate_json(text)
    except ValidationError:
        raw_json = json.loads(text)
        filled   = _fill_missing_booleans(model_cls,
                                          raw_json if isinstance(raw_json, dict) else {})
        parsed   = model_cls.model_validate(filled)

    return group_key, parsed


async def process_paper(fp: Path, llm: LLMClient, sem: asyncio.Semaphore, skip_already_finished: bool = True) -> None:
    """Read a paper, run all LLM translations concurrently, write result back."""
    try:
        paper: dict = await asyncio.to_thread(fp.read_text, encoding="utf-8")
        paper = json.loads(paper)
    except UnicodeDecodeError:
        paper = json.loads(await asyncio.to_thread(fp.read_text))
    except Exception as exc:
        log.error(f"{fp.name}: {exc}")
        return

    if skip_already_finished and paper.get("Habitat") is not None and paper.get("ParentHabitat") is not None:
        log.info(f"Skipping {fp.stem}")
        return

    log.info(f"Translating {fp.stem}")
    try:
        model_map = _build_model_map(use_leaf=False)
        coros     = [
            translate_group(llm, sem, paper, group_key, model_cls, human_label)
            for group_key, (model_cls, human_label) in model_map.items()
        ]

        # Run all habitat-group requests in parallel
        typed_results: Dict[str, BaseModel] = {
            k: v for k, v in await asyncio.gather(*coros)
        }

        habitats = IUCNHabitats(**typed_results)
        paper["Habitat"]       = habitats.model_dump()
        paper["ParentHabitat"] = root_presence_map(habitats)

        # Write JSON back to disk
        await asyncio.to_thread(fp.write_text, json.dumps(paper, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    except Exception as exc:
        log.error(f"{fp.name}: {exc}")


async def main() -> None:
    src_dir = Path(r"D:\LiteratureReviewCVinWC\review_output\manual")
    skip_already_finished = True

    #############################

    settings = Settings()
    llm      = LLMClient(settings.api_keys,
                         settings.light_model_name,
                         settings.strong_model_name,
                         rpm=settings.rpm,
                         use_native_json_schema=settings.use_native_json_schema)

    llm_sem  = asyncio.Semaphore(MAX_PARALLEL_LLM)

    # Optional paper-level parallelism (bounded by MAX_PARALLEL_FILE)
    file_sem = asyncio.Semaphore(MAX_PARALLEL_FILE)

    async def sem_process(fp: Path):
        async with file_sem:
            await process_paper(fp, llm, llm_sem, skip_already_finished=skip_already_finished)

    tasks = [asyncio.create_task(sem_process(fp))
             for fp in iterate_jsons_from_folder(src_dir)]

    # Progress bar friendly – change to tqdm if you like
    for t in asyncio.as_completed(tasks):
        await t


if __name__ == "__main__":
    asyncio.run(main())
