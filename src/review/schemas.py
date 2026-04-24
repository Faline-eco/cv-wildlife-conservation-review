# wildcv_review/schemas.py
from dataclasses import dataclass

from pydantic import BaseModel, AnyUrl, Field
from typing import List, Optional

class IsCVWildlife(BaseModel):
    is_computer_vision_in_wildlife_study: bool
    is_review: bool
    explanation: str

class Dataset(BaseModel):
    name: str
    url: Optional[str] = None

class Datasets(BaseModel):
    datasets: List[Dataset] = Field(default_factory=list)

class IucnHabitatsOut(BaseModel):
    response: List[str] = Field(default_factory=list)

class StringList(BaseModel):
    response: List[str] = Field(default_factory=list)

class Evidence(BaseModel):
    page: Optional[int] = None           # 1-based index if known
    quote: str                           # short verbatim snippet from the paper

class LabeledItem(BaseModel):
    value: str                           # exact phrase from the paper
    evidence: Optional[Evidence] = None  # optional but strongly encouraged

class ItemList(BaseModel):
    items: List[LabeledItem] = Field(default_factory=list)


@dataclass(frozen=True)
class TopicSpec:
    key: str                      # e.g., "CV Tasks"
    prompt: str                   # natural-language instruction
    allowed_vocab: Optional[List[str]] = None  # constrain values to this set (case-insensitive)
    require_images_only: bool = False          # used for e.g., "Species (Images)"
    old_key: Optional[str] = None

class DatasetEvidenceItem(BaseModel):
    # Keep "value" as the dataset *name* so we can reuse verify_items_against_pdf()
    value: str                      # e.g., "ImageNet" or "private"
    url: Optional[str] = None       # if public; omit or null if private/unspecified
    evidence: Optional[Evidence] = None

class DatasetEvidenceList(BaseModel):
    items: List[DatasetEvidenceItem]


class ReviewedPaperEvidenceItem(BaseModel):
    value: str                           # title verbatim (used by verification)
    doi: Optional[str] = None
    url: Optional[str] = None
    year: Optional[int] = None
    evidence: Optional[Evidence] = None  # your existing Evidence model

class ReviewedPaperEvidenceList(BaseModel):
    items: List[ReviewedPaperEvidenceItem] = Field(default_factory=list)