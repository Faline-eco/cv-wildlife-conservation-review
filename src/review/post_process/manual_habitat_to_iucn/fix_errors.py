import json
import traceback
from pathlib import Path

from iucn.generate_iucn_models import to_snake
from iucn.iucn_models import IUCNHabitats
from iucn.utils import root_presence_map, _any_true
from review.extractors import _build_model_map
from review.post_process.util import iterate_jsons_from_folder

from copy import deepcopy
from typing import get_origin, get_args, Type, Optional, Any, Iterable, Dict
from pydantic import BaseModel

# ================== version-agnostic field introspection ==================

def _iter_model_fields(model_cls: Type[BaseModel]):
    """
    Yield (name, type_annotation, default, default_factory, nested_model_cls)
    across Pydantic v1 and v2.
    """
    if hasattr(model_cls, "model_fields"):  # Pydantic v2
        for name, f in model_cls.model_fields.items():
            ann = f.annotation
            nested = _unwrap_model_annotation(ann)
            default = getattr(f, "default", None)
            default_factory = getattr(f, "default_factory", None)
            yield name, ann, default, default_factory, nested
        return

    # Pydantic v1
    for name, f in model_cls.__fields__.items():
        ann = getattr(f, "outer_type_", f.type_)
        nested = _unwrap_model_annotation(ann)
        default = getattr(f, "default", None)
        default_factory = getattr(f, "default_factory", None)
        yield name, ann, default, default_factory, nested


def _unwrap_model_annotation(ann) -> Optional[Type[BaseModel]]:
    if isinstance(ann, type) and issubclass_safe(ann, BaseModel):
        return ann
    origin = get_origin(ann)
    if origin is not None:
        for a in get_args(ann):
            if isinstance(a, type) and issubclass_safe(a, BaseModel):
                return a
    return None


def _is_bool_annotation(ann: Any) -> bool:
    if ann is bool:
        return True
    origin = get_origin(ann)
    if origin is not None:
        return any(a is bool for a in get_args(ann))
    return False


def issubclass_safe(a, b) -> bool:
    try:
        return isinstance(a, type) and issubclass(a, b)
    except Exception:
        return False

# ================== existing helpers (normalization) ==================

def _all_fields_bool_dict(model_cls: Type[BaseModel], value: bool) -> dict:
    out = {}
    for name, ann, default, default_factory, nested_model in _iter_model_fields(model_cls):
        if nested_model:
            out[name] = _all_fields_bool_dict(nested_model, value)
        else:
            if _is_bool_annotation(ann):
                out[name] = bool(value)
            else:
                if default is not None:
                    out[name] = deepcopy(default)
                elif default_factory is not None:
                    out[name] = default_factory()
                else:
                    out[name] = None
    return out


def _coerce_booleans_to_models(data: dict, model_cls: Type[BaseModel]) -> dict:
    """
    Expand boolean-at-model fields to dicts based on schema.
    """
    if not isinstance(data, dict):
        return data
    result = {}
    schema_fields = {name: (ann, nested_model)
                     for name, ann, _, _, nested_model in _iter_model_fields(model_cls)}
    for name, val in data.items():
        if name not in schema_fields:
            result[name] = val
            continue
        ann, nested_model = schema_fields[name]
        if nested_model:
            if isinstance(val, bool):
                result[name] = _all_fields_bool_dict(nested_model, val)
            elif isinstance(val, dict):
                result[name] = _coerce_booleans_to_models(val, nested_model)
            else:
                result[name] = val
        else:
            result[name] = val
    return result

# ================== labels → overlay (with replace paths) ==================

def _paths_in_model(model_cls: Type[BaseModel], prefix: str = "") -> Iterable[Dict[str, Any]]:
    for name, _, __, ___, nested in _iter_model_fields(model_cls):
        path = f"{prefix}.{name}" if prefix else name
        yield {"path": path, "name": name, "is_model": bool(nested), "model_cls": nested}
        if nested:
            yield from _paths_in_model(nested, path)


def _overlay_piece_for_entry(e: Dict[str, Any]) -> dict:
    """
    Build a nested dict for e["path"] that sets the node to 'all True'.
    """
    keys = e["path"].split(".")
    cursor = out = {}
    for k in keys[:-1]:
        cursor[k] = {}
        cursor = cursor[k]
    leaf = keys[-1]
    if e["is_model"]:
        cursor[leaf] = _all_fields_bool_dict(e["model_cls"], True)
    else:
        cursor[leaf] = True
    return out


def labels_to_overlay_and_replace_paths(
    labels: Iterable[str],
    root_model: Type[BaseModel],
    *,
    prefer_dotted: bool = True,
    on_ambiguous: str = "all",  # "all" | "first"
):
    """
    Returns (overlay_dict, replace_paths_set).
    replace_paths contains paths of model nodes that should fully REPLACE payload subtrees.
    """
    entries = list(_paths_in_model(root_model))
    by_path = {e["path"]: e for e in entries}
    by_name: Dict[str, list] = {}
    for e in entries:
        by_name.setdefault(e["name"], []).append(e)

    overlay: dict = {}
    replace_paths = set()

    def _merge_overlay(a: dict, b: dict) -> dict:
        # simple recursive merge for combining multiple label pieces
        out = deepcopy(a)
        for k, v in b.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = _merge_overlay(out[k], v)
            else:
                out[k] = deepcopy(v)
        return out

    for label in labels:
        matched_entries = []
        if prefer_dotted and label in by_path:
            matched_entries = [by_path[label]]
        else:
            matched_entries = by_name.get(label, [])
            if on_ambiguous != "all":
                matched_entries = matched_entries[:1]

        for e in matched_entries:
            piece = _overlay_piece_for_entry(e)
            overlay = _merge_overlay(overlay, piece)
            if e["is_model"]:
                replace_paths.add(e["path"])

    return overlay, replace_paths

# ================== override-aware merge ==================

def _merge_with_override(
    base: Any,
    override: Any,
    replace_paths: set,
    path: str = "",
):
    """
    Merge 'override' into 'base'. If current path (or child path) is in replace_paths,
    replace that subtree wholesale with override.
    """
    # If this node is marked for replacement, just take override
    if path and path in replace_paths:
        return deepcopy(override)

    # Dict + Dict: merge keys
    if isinstance(base, dict) and isinstance(override, dict):
        out = deepcopy(base)
        for k, v in override.items():
            child_path = f"{path}.{k}" if path else k
            if child_path in replace_paths:
                out[k] = deepcopy(v)
            else:
                if k in out:
                    out[k] = _merge_with_override(out[k], v, replace_paths, child_path)
                else:
                    out[k] = deepcopy(v)
        return out

    # Types differ or non-dicts: overlay wins where specified
    if override is not None:
        return deepcopy(override)
    return deepcopy(base)

# ================== main entry ==================

def parse_with_labels(
    payload: dict,
    labels: Iterable[str],
    root_model: Type[BaseModel],
    **label_opts,
) -> BaseModel:
    """
    Normalize payload, overlay labels (labels overrule!), and parse.
    """
    # 1) Normalize payload booleans to dicts so deeper dotted labels can merge cleanly
    normalized_payload = _coerce_booleans_to_models(deepcopy(payload or {}), root_model)

    # 2) Build overlay + replace paths from labels
    overlay, replace_paths = labels_to_overlay_and_replace_paths(labels, root_model, **label_opts)

    # 3) Merge with override semantics (labels overrule payload)
    merged = _merge_with_override(normalized_payload, overlay, replace_paths)

    # 4) Final pass through normalization and parse into model
    normalized = _coerce_booleans_to_models(merged, root_model)
    if hasattr(root_model, "model_validate"):
        return root_model.model_validate(normalized)  # Pydantic v2
    return root_model.parse_obj(normalized)          # Pydantic v1



if __name__ == '__main__':
    src_dir = Path(r"D:\LiteratureReviewCVinWC\review_output\manual")

    model_map = _build_model_map(use_leaf=False)
    print()
    for fp in iterate_jsons_from_folder(src_dir):
        with open(fp, "r", encoding="utf-8") as f:
            paper = json.load(f)
        if paper.get("Habitat") is not None:
            try:
                habitats = IUCNHabitats(**paper["Habitat"])
            except Exception as e:
                habitats = parse_with_labels(paper["Habitat"], [], IUCNHabitats)

            labels = paper.get("HabitatVerification", {}).get("verified", [])
            labels_snake = [to_snake(l) for l in labels]
            habitats_for_parent_only = parse_with_labels(paper["Habitat"], labels_snake, IUCNHabitats)

            parents = root_presence_map(habitats_for_parent_only)
            if len(parents) > len(habitats.__dict__):
                raise Exception()
            else:
                paper["Habitat (fixed)"] = habitats.model_dump()
                paper["ParentHabitat (fixed)"] = parents
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(paper, f)