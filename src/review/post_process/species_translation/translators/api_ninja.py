# animal_translator/translators/api_ninja.py
from __future__ import annotations

import time
from typing import Iterable, List

import requests

from review.post_process.species_translation.config import get_settings
from review.post_process.logger import animal_translate_logger
from review.post_process.species_translation.models import Direction
from review.post_process.species_translation.translators.base import AbstractTranslator, TranslationError


class APINinjaTranslator(AbstractTranslator):
    """Uses https://api.api-ninjas.com/v1/animals to map common↔scientific.

    Notes:
    - The endpoint primarily searches by common name, but we try a reverse match
      by scanning returned `taxonomy.scientific_name`.
    """
    slug = "API_NINJA"
    _URL = "https://api.api-ninjas.com/v1/animals"

    def __init__(self) -> None:
        self.settings = get_settings()
        self._session = requests.Session()
        if not self.settings.api_ninja_key:
            animal_translate_logger.debug("API Ninja key not set; calls will fail if used.")
        self._session.headers.update({"X-Api-Key": self.settings.api_ninja_key or ""})

    def translate(self, names: Iterable[str], direction: Direction) -> List[str]:
        out: List[str] = []
        for n in names:
            try:
                out.append(self._translate_one(n, direction))
            except TranslationError as e:
                animal_translate_logger.debug("API Ninja failed for %s: %s", n, e)
                out.append("")
            # be kind to their API
            time.sleep(0.25)
        return out

    # ---------------------------------

    def _translate_one(self, name: str, direction: Direction) -> str:
        params = {"name": name}
        try:
            r = self._session.get(self._URL, params=params, timeout=15)
        except requests.RequestException as e:
            raise TranslationError(f"Request error: {e}") from e

        if r.status_code == 401:
            raise TranslationError("Unauthorized: missing or invalid API Ninja key.")
        if not r.ok:
            raise TranslationError(f"HTTP {r.status_code}: {r.text[:120]}")

        data = r.json() or []
        if not data:
            return ""

        if direction == Direction.TO_SCIENTIFIC:
            # choose the first result's taxonomy.scientific_name if present
            for item in data:
                sci = (item.get("taxonomy") or {}).get("scientific_name")
                if isinstance(sci, str) and sci.strip():
                    return sci.strip()
            return ""
        else:
            # we might have queried by scientific name; attempt reverse match
            # Prefer exact matching on taxonomy.scientific_name.
            for item in data:
                taxonomy = item.get("taxonomy") or {}
                sci = taxonomy.get("scientific_name", "")
                common = item.get("name", "")
                if isinstance(sci, str) and sci.lower() == name.lower():
                    return common.strip() if isinstance(common, str) else ""
            # Fallback: return the first "name" field
            first_name = data[0].get("name")
            return first_name.strip() if isinstance(first_name, str) else ""
