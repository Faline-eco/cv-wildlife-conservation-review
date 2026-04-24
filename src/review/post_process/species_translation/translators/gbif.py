import urllib.parse
from collections import Counter
from typing import Iterable, List

import requests

from review.post_process.logger import animal_translate_logger
from review.post_process.species_translation.models import Direction
from review.post_process.species_translation.translators.base import AbstractTranslator, TranslationError


class GBIFTranslator(AbstractTranslator):
    slug = "GBIF"
    _BASE = "https://api.gbif.org/v1"

    def translate(self, names: Iterable[str], direction: Direction) -> List[str]:
        if direction == Direction.TO_SCIENTIFIC:
            raise TranslationError("GBIF supports only scientific→vernacular")
        results: List[str] = []
        for name in names:
            vernaculars = self._vernacular_names(name)
            results.append(vernaculars[0] if vernaculars else name)
        return results

    # ---------- internal helpers ------------------------------------
    def _vernacular_names(self, scientific_name: str) -> List[str]:
        match_url = (
            f"{self._BASE}/species/match?name={urllib.parse.quote_plus(scientific_name)}"
        )
        r = requests.get(match_url, timeout=10)
        if not r.ok:
            raise TranslationError(f"GBIF match failed for {scientific_name}")

        usage_key = r.json().get("usageKey")
        if not usage_key:
            return []

        offset, acc = 0, Counter()
        while True:
            url = f"{self._BASE}/species/{usage_key}/vernacularNames?offset={offset}"
            resp = requests.get(url, timeout=10)
            if not resp.ok:
                break
            data = resp.json()
            for item in data["results"]:
                if item["language"] == "eng":
                    acc[item["vernacularName"].lower()] += 1
            if data["endOfRecords"]:
                break
            offset += data["limit"]
        vernaculars_sorted = [v for v, _ in acc.most_common()]
        animal_translate_logger.debug("GBIF » %s → %s", scientific_name, vernaculars_sorted[:3])
        return vernaculars_sorted
