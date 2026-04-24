# animal_translator/translators/llm.py
from __future__ import annotations

import asyncio
import json
from typing import Iterable, List

from review.genai_client import LLMClient
from ..config import get_settings
from review.post_process.logger import animal_translate_logger
from ..models import Direction
from .base import AbstractTranslator, TranslationError
from google.genai import types as genai_types

_SYSTEM_PROMPT = (
    "You are a taxonomy assistant. Convert species names between common and scientific.\n"
    "Return ONLY a JSON array of strings, one output per input (use empty string if unknown)."
)

_USER_PROMPT_TEMPLATE = """Task: Convert species names {direction_readable}.

Input names (JSON array):
{names_json}

Output:
Return ONLY a JSON array of strings (no extra text), same order and length as the input.
The strings should be singular names (e.g. Tetraonini instead of Tetraoninae) and without abbreviations (e.g. R. fulva as Rhagonycha fulva). Also avoid sp or spp endings.
"""


def _chunks(seq: List[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


class LLMTranslator(AbstractTranslator):
    """LLM-backed translator using the provided LLMClient (Google GenAI)."""
    slug = "LLM"

    def __init__(self) -> None:
        self.settings = get_settings()

        keys = list(self.settings.api_keys or [])
        strong = self.settings.gemini_model or "models/gemini-2.5-flash"
        # Optional lighter model; falls back to strong if not configured
        light = getattr(self.settings, "gemini_light_model", None) or strong
        rpm = int(self.settings.rpm or 60)

        self._client = None if LLMClient is None else LLMClient(
            api_keys=keys or [""],
            light_model_name=light,
            strong_model_name=strong,
            rpm=rpm,
            use_native_json_schema=True,
        )

        # Small batches to keep prompts modest; adjust if needed
        self._batch_size = 50

    # ----------------------------------------------------------------

    def translate(self, names: Iterable[str], direction: Direction) -> List[str]:
        names_list = list(names)
        if not names_list:
            return []

        if self._client is None or genai_types is None:
            raise TranslationError(
                "genai_client / google.genai unavailable. Ensure genai_client.py is importable "
                "and the Google GenAI SDK is installed."
            )

        async def _run() -> List[str]:
            results: List[str] = []
            schema = genai_types.Schema(
                type=genai_types.Type.ARRAY,
                items=genai_types.Schema(type=genai_types.Type.STRING),
            )

            for batch in _chunks(names_list, self._batch_size):
                prompt = _USER_PROMPT_TEMPLATE.format(
                    direction_readable="to SCIENTIFIC names" if direction == Direction.TO_SCIENTIFIC else "to COMMON names",
                    names_json=json.dumps(batch, ensure_ascii=False),
                )
                try:
                    text = await self._client.generate(
                        contents=prompt,
                        system_instruction=_SYSTEM_PROMPT,
                        response_model=schema,
                        use_strong_model=True,
                    )
                except Exception as e:
                    raise TranslationError(f"LLM request failed: {e}") from e

                try:
                    arr = json.loads(text)
                    if not isinstance(arr, list):
                        raise ValueError("Model did not return a JSON array.")
                    # Normalize length to match batch
                    if len(arr) < len(batch):
                        arr += [""] * (len(batch) - len(arr))
                    elif len(arr) > len(batch):
                        arr = arr[: len(batch)]
                    results.extend(str(x) if x is not None else "" for x in arr)
                except Exception as e:
                    animal_translate_logger.debug("Raw LLM response: %s", text[:400])
                    raise TranslationError(f"LLM response parse error: {e}") from e

            return results

        # Run the async client in a blocking way for the sync service layer
        try:
            return asyncio.run(_run())
        except RuntimeError:
            # Fallback in rare contexts where an event loop is already running:
            # schedule the task on the current loop and block until complete.
            loop = asyncio.get_event_loop()
            fut = asyncio.ensure_future(_run(), loop=loop)
            return loop.run_until_complete(fut)
