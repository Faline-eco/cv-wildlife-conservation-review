from enum import Enum
from typing import List, Dict

from pydantic import BaseModel


class Direction(str, Enum):
    TO_SCIENTIFIC = "to_scientific"
    TO_COMMON = "to_common"


class TranslationRequest(BaseModel):
    names: List[str]
    direction: Direction


class TranslationResponse(BaseModel):
    original: str
    translations: List[str]


class CachePayload(BaseModel):
    translation_type_is_scientific: bool
    translator: str
    llm_model: str | None = None
    taxize_db: str | None = None
    translations: Dict[str, str] = {}
    files: Dict[str, dict] = {}
