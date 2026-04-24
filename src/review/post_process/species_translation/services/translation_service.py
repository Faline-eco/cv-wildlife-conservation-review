# animal_translator/services/translation_service.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from pydantic import TypeAdapter

from review.post_process.species_translation.config import get_settings
from review.post_process.logger import animal_translate_logger
from review.post_process.species_translation.models import Direction, TranslationResponse, CachePayload
from review.post_process.species_translation.translators.base import AbstractTranslator, TranslationError
from review.post_process.species_translation.translators import registry


class TranslationService:
    """Orchestrates caching and translation across adapters."""

    def __init__(self, cache_path: Path | None = None, translator_slug: str | None = None):
        self.settings = get_settings()
        self.cache_path = cache_path or self.settings.cache_file
        self.cache = self._load_cache()

        slug = (translator_slug or self.settings.translator).upper()
        self.translator: AbstractTranslator | None = registry.get(slug)
        if not self.translator:
            raise ValueError(f"Unknown translator «{slug}». Available: {', '.join(registry.keys())}")

        self.direction = Direction.TO_SCIENTIFIC if self.settings.convert_to_scientific else Direction.TO_COMMON

    def translate_many(self, names: Iterable[str], *, file_id: str | None = None) -> List[TranslationResponse]:
        names_list = list(names)
        out: List[TranslationResponse] = []

        to_lookup: list[str] = []
        for n in names_list:
            cached = self.cache.translations.get(n)
            if cached:
                out.append(TranslationResponse(original=n, translations=[cached]))
            else:
                to_lookup.append(n)

        if to_lookup:
            try:
                translated = self.translator.translate(to_lookup, self.direction)
                for original, best in zip(to_lookup, translated, strict=False):
                    if best:
                        out.append(TranslationResponse(original=original, translations=[best]))
                        self.cache.translations[original] = best
                    else:
                        out.append(TranslationResponse(original=original, translations=[]))
            except TranslationError as e:
                animal_translate_logger.error("Batch failed via %s: %s", type(self.translator).__name__, e)
                for original in to_lookup:
                    out.append(TranslationResponse(original=original, translations=[]))

        if file_id:
            self.cache.files.setdefault(file_id, {})["species"] = names_list

        self._persist_cache()
        out.sort(key=lambda r: names_list.index(r.original))
        return out

    # ---------------- private ----------------

    def _load_cache(self) -> CachePayload:
        adapter = TypeAdapter(CachePayload)
        if self.cache_path.exists():
            try:
                text = self.cache_path.read_text(encoding="utf-8")
                return adapter.validate_json(text)
            except Exception as e:
                animal_translate_logger.warning("Cache unreadable (%s). Starting fresh.", e)
        return CachePayload(
            translation_type_is_scientific=self.settings.convert_to_scientific,
            translator=self.settings.translator,
            llm_model=self.settings.gemini_model,
            taxize_db=self.settings.docker_taxize_db,
            translations={},
            files={},
        )

    def _persist_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self.cache.model_dump(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            animal_translate_logger.warning("Could not write cache to %s (%s).", self.cache_path, e)
