# animal_translator/translators/eco_name.py
from __future__ import annotations

import time
from typing import Iterable, List, Optional

import requests

from review.post_process.species_translation.config import get_settings
from review.post_process.logger import animal_translate_logger
from review.post_process.species_translation.models import Direction
from review.post_process.species_translation.translators.base import AbstractTranslator, TranslationError


class EcoNameTranslator(AbstractTranslator):
    """Adapter for a generic 'EcoName' style service.

    This assumes a REST API with endpoints like:
      - GET {base}/to_scientific?name=<common>
      - GET {base}/to_common?name=<scientific>

    If you use a different service, adjust `_endpoint` or override methods.
    """
    slug = "ECONAME"

    def __init__(self) -> None:
        self.settings = get_settings()
        # Allow overriding base URL via env var ECONAME_BASE_URL
        # If not set, this adapter will log and gracefully return empty strings.
        self._base_url: Optional[str] = getattr(self.settings, "econame_base_url", None)  # type: ignore[attr-defined]
        self._session = requests.Session()

    def translate(self, names: Iterable[str], direction: Direction) -> List[str]:
        results: List[str] = []
        for name in names:
            try:
                results.append(self._translate_one(name, direction))
            except TranslationError as e:
                animal_translate_logger.debug("EcoName failed for %s: %s", name, e)
                results.append("")
            time.sleep(0.1)
        return results

    # ---------------------------------

    def _translate_one(self, name: str, direction: Direction) -> str:
        if not self._base_url:
            raise TranslationError("EcoName base URL not configured (econame_base_url).")

        endpoint = "to_scientific" if direction == Direction.TO_SCIENTIFIC else "to_common"
        url = f"{self._base_url.rstrip('/')}/{endpoint}"
        try:
            r = self._session.get(url, params={"name": name}, timeout=20)
        except requests.RequestException as e:
            raise TranslationError(f"Request error: {e}") from e

        if not r.ok:
            raise TranslationError(f"HTTP {r.status_code}: {r.text[:120]}")

        data = r.json()
        if isinstance(data, dict):
            # try a few common shapes
            if "translation" in data and isinstance(data["translation"], str):
                return data["translation"].strip()
            if "result" in data and isinstance(data["result"], str):
                return data["result"].strip()
        if isinstance(data, str):
            return data.strip()
        return ""
