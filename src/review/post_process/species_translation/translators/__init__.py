# animal_translator/translators/__init__.py
from .base import AbstractTranslator, TranslationError
from .gbif import GBIFTranslator
from .eco_name import EcoNameTranslator
from .api_ninja import APINinjaTranslator
from .llm import LLMTranslator
from .docker import DockerTranslator

# Instantiate once and expose a simple registry for the service layer
_all = [GBIFTranslator, EcoNameTranslator, APINinjaTranslator, LLMTranslator, DockerTranslator]
registry = {cls.slug: cls() for cls in _all}

__all__ = [
    "AbstractTranslator",
    "TranslationError",
    "GBIFTranslator",
    "EcoNameTranslator",
    "APINinjaTranslator",
    "LLMTranslator",
    "DockerTranslator",
    "registry",
]
