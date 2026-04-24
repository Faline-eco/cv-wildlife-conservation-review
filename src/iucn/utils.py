from typing import Dict, Any

from pydantic import BaseModel

from iucn.iucn_models import IUCNHabitats


def _any_true(value: Any) -> bool:
    """
    Recursively check whether any boolean leaf under `value` is True.
    Works for nested Pydantic models or plain containers.
    """
    if isinstance(value, bool):
        return value

    if isinstance(value, BaseModel):
        # pydantic v2: model_fields; v1: __fields__
        try:
            field_names = value.model_fields.keys()  # type: ignore[attr-defined]
        except AttributeError:  # pydantic v1
            field_names = value.__fields__.keys()  # type: ignore[attr-defined]

        for name in field_names:
            if _any_true(getattr(value, name)):
                return True
        return False

    if isinstance(value, dict):
        return any(_any_true(v) for v in value.values())

    if isinstance(value, (list, tuple, set)):
        return any(_any_true(v) for v in value)

    # Ignore non-bool, non-container types
    return False


def root_presence_map(habitats: IUCNHabitats) -> Dict[str, bool]:
    """
    For a given IUCNHabitats instance, return a dict mapping each
    Level-1 class name ('Forest', 'Savanna', ...) to True/False depending on
    whether any leaf boolean inside that subtree is True.

    Example output:
        {'Forest': True, 'Savanna': False, 'Shrubland': False, 'MarineNeritic': True}
    """
    result: Dict[str, bool] = {}

    # pydantic v2: model_fields; v1: __fields__
    try:
        top_fields = habitats.model_fields.keys()  # type: ignore[attr-defined]
    except AttributeError:  # pydantic v1
        top_fields = habitats.__fields__.keys()  # type: ignore[attr-defined]

    for name in top_fields:
        root_obj = getattr(habitats, name)
        root_class_name = type(root_obj).__name__  # e.g., 'Forest', 'MarineNeritic'
        result[root_class_name] = _any_true(root_obj)

    return result