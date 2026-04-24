from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Publication:
    doi: str
    url: str
    year: Optional[int]  # None if unknown
    title: Optional[str] = None
    authors: Optional[str] = None
