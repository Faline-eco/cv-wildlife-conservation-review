from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # --- I/O ---------------------------------------------------------
    cache_file: Path = Field(
        default=r"D:\LiteratureReviewCVinWC\review_output\20250731_species.json",
        description="Disk cache for translations.",
    )

    # --- translation options ----------------------------------------
    convert_to_scientific: bool = True
    translator: str = "LLM"  # EcoNameTranslator | GBIF | LLM | API_NINJA | DOCKER
    docker_url: str = "http://localhost:8000/comm2sci"
    docker_taxize_db: Optional[str] = None

    # --- LLM ---------------------------------------------------------
    api_keys: List[str] = Field(default_factory=list)
    gemini_model: str = "models/gemini-2.5-flash"
    rpm: int = 148  # requests per minute

    # --- API Ninja ---------------------------------------------------
    api_ninja_key: Optional[str] = None

    class Config:
        env_prefix = ""
        env_file = r"D:\LiteratureReviewCVinWC\.env"


@lru_cache
def get_settings() -> Settings:  # cached so it is a singleton
    return Settings()
