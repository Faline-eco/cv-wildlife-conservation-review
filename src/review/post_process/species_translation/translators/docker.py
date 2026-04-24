# animal_translator/translators/docker.py
from __future__ import annotations

import json
from typing import Iterable, List

import requests

from review.post_process.species_translation.config import get_settings
from review.post_process.species_translation.translators.base import AbstractTranslator, TranslationError
from review.post_process.species_translation.models import Direction


class DockerTranslator(AbstractTranslator):
    """Calls a local HTTP service (e.g., containerized R/taxize or your own microservice).

    Configure:
      - settings.docker_url (e.g. http://localhost:8000/comm2sci)
      - settings.docker_taxize_db (optional: pass-through parameter)
    """
    slug = "DOCKER"

    def __init__(self) -> None:
        self.settings = get_settings()
        self._session = requests.Session()

    def translate(self, names: Iterable[str], direction: Direction) -> List[str]:
        payload = {
            "names": list(names),
            "direction": direction.value,  # "to_scientific" | "to_common"
        }
        if self.settings.docker_taxize_db:
            payload["db"] = self.settings.docker_taxize_db

        try:
            r = self._session.post(self.settings.docker_url, json=payload, timeout=60)
        except requests.RequestException as e:
            raise TranslationError(f"Local service not reachable: {e}") from e

        if not r.ok:
            raise TranslationError(f"HTTP {r.status_code}: {r.text[:160]}")

        try:
            data = r.json()
        except json.JSONDecodeError as e:
            raise TranslationError(f"Bad JSON from local service: {e}") from e

        # Expect either {"translations": ["Panthera leo", ...]} or a mapping.
        if isinstance(data, dict) and "translations" in data and isinstance(data["translations"], list):
            return [str(x) if x is not None else "" for x in data["translations"]]

        if isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
            return [str(x) if x is not None else "" for x in data["results"]]

        # Try to coerce a dict mapping {original: translated}
        if isinstance(data, dict):
            # order according to input names
            name_list = list(names)
            return [str(data.get(k, "")) for k in name_list]

        raise TranslationError("Unexpected response shape from local service.")
