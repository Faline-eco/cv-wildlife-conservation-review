from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict


@dataclass(frozen=True)
class Config:
    # Inputs / outputs
    input_excel_path: Path
    output_csv_path: Path
    output_bibtex_path: Path

    # Services
    doi2bib_base_url: str = "http://localhost:8080"
    opencitations_base_url: str = "https://opencitations.net/index/coci/api/v1"

    # Behavior
    min_year: int = 2014
    rate_limit_per_sec: int = 6
    timeout_seconds: float = 15.0
    max_retries: int = 3

    # Optional proxies for requests (e.g., {"http": "http://127.0.0.1:8118", "https": "http://127.0.0.1:8118"})
    proxies: Optional[Dict[str, str]] = None

