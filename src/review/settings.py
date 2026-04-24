# wildcv_review/settings.py
from pydantic import Field
from pydantic_settings import BaseSettings
from typing import List, Optional

class Settings(BaseSettings):
    zotero_storage: str = r"C:\Users\<TODO>\Zotero\storage"
    dois_file_path: str = r"D:\LiteratureReviewCVinWC\review_input\reviews.csv"
    target_base_folder: str = r"D:\LiteratureReviewCVinWC\review_output"
    review_to_continue: Optional[str] = None
    light_model_name: str = "models/gemini-2.5-flash"
    strong_model_name: str = "models/gemini-2.5-pro"
    rpm: int = 148  # requests per minute
    concurrent_files: int = 4
    use_native_json_schema: bool = True
    api_keys: List[str] = Field(default_factory=list)

    class Config:
        env_prefix = ""
        env_file = r"D:\LiteratureReviewCVinWC\.env"
