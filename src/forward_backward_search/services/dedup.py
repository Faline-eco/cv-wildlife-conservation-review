from __future__ import annotations

from typing import Set


class Deduper:
    def __init__(self) -> None:
        self._seen: Set[str] = set()

    def seen(self, doi: str) -> bool:
        return doi in self._seen

    def add(self, doi: str) -> None:
        self._seen.add(doi)
