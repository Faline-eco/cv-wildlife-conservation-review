# helpers/gemini_schema.py
from __future__ import annotations

from typing import Dict, Type
from pydantic import BaseModel, Field, create_model

# Cache so we only build each safe model once
_GEMINI_SAFE_CACHE: Dict[Type[BaseModel], Type[BaseModel]] = {}

def gemini_safe_model(model: Type[BaseModel]) -> Type[BaseModel]:
    """
    Create a clone of `model` with the same field names/types but:
      - NO defaults (no False, no default_factory) to satisfy Gemini.
      - Preserves field descriptions and aliases.
      - Recurses into nested BaseModel fields.
    """
    if model in _GEMINI_SAFE_CACHE:
        return _GEMINI_SAFE_CACHE[model]

    fields = {}
    for name, f in model.model_fields.items():
        typ = f.annotation

        # Recurse into nested models
        if isinstance(typ, type) and issubclass(typ, BaseModel):
            typ = gemini_safe_model(typ)

        # Preserve description / alias but DO NOT set any default.
        # Field(..., ...) marks the field as "required" without a default.
        kwargs = {}
        if getattr(f, "description", None):
            kwargs["description"] = f.description
        if getattr(f, "alias", None):
            kwargs["alias"] = f.alias
        # If you use validation_alias/serialization_alias, carry them too:
        if getattr(f, "validation_alias", None):
            kwargs["validation_alias"] = f.validation_alias
        if getattr(f, "serialization_alias", None):
            kwargs["serialization_alias"] = f.serialization_alias

        fields[name] = (typ, Field(..., **kwargs))

    # New class name is only for internal use with Gemini.
    Safe = create_model(f"{model.__name__}ForGemini", __base__=BaseModel, **fields)  # type: ignore
    _GEMINI_SAFE_CACHE[model] = Safe
    return Safe
