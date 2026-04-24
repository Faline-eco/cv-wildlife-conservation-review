# wildcv_review/utils.py
from __future__ import annotations
import json, ast
from typing import (
    Callable,
    Hashable,
    Iterable,
    List,
    Optional,
    Tuple,
    TypeVar,
    overload, Any, Dict,
)
import re

from pydantic import BaseModel

from review.schemas import Datasets, Dataset


def parse_json_array(text: str) -> List[str]:
    # Try strict JSON first
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return [str(x) for x in obj]
        if isinstance(obj, dict) and "response" in obj and isinstance(obj["response"], list):
            return [str(x) for x in obj["response"]]
    except Exception:
        pass
    # Last resort: Python literal eval (still validate)
    try:
        obj = ast.literal_eval(text)
        if isinstance(obj, tuple):
            obj = list(obj)
        if isinstance(obj, list):
            return [str(x) for x in obj]
    except Exception:
        pass
    return []


# If a field has a description, prefer it; otherwise humanize the snake_case name.
def humanize_field(name: str) -> str:
    name = name.replace("_", " ").strip()
    name = re.sub(r"\s+", " ", name)
    return name[:1].upper() + name[1:]

def field_label(model_cls: type[BaseModel], field_name: str) -> str:
    # info = model_cls.model_fields.get(field_name)
    # if info and isinstance(info, pydantic.Field):
    #     # pydantic v2 Field is not the same as typing Field; description accessible via .description
    #     pass  # Placeholder; see below line
    # In Pydantic v2, model_fields[field_name] is a FieldInfo
    info = model_cls.model_fields.get(field_name)
    desc = getattr(info, "description", None) if info else None
    return (desc or humanize_field(field_name)).strip()

def extract_true_labels(model_cls: type[BaseModel], instance: BaseModel) -> List[str]:
    true_labels: List[str] = []
    for fname, finfo in model_cls.model_fields.items():
        try:
            val = getattr(instance, fname)
        except Exception:
            continue
        if isinstance(val, bool) and val:
            true_labels.append(field_label(model_cls, fname))
    return true_labels

def canonical_path_label(group_label: str, leaf_label: str) -> str:
    # Canonical string you’ll store in your results list
    return f"{group_label}: {leaf_label}"

T = TypeVar("T")

@overload
def dedup_preserve_order(values: Iterable[str], *, key: None = ...) -> List[str]: ...
@overload
def dedup_preserve_order(values: Iterable[T], *, key: Callable[[T], Hashable]) -> List[T]: ...

def dedup_preserve_order(
    values: Iterable[T],
    *,
    key: Optional[Callable[[T], Hashable]] = None,
) -> List[T]:
    """
    Stable deduplication that preserves the first occurrence.

    - With no `key`, this **exactly matches** your original implementation for strings.
    - With a `key`, you can define your own uniqueness rule (e.g., case-insensitive tuples).

    Examples:
        dedup_preserve_order(["A", "B", "A"]) -> ["A", "B"]

        dedup_preserve_order(
            [("ImageNet", "http://..."), ("imagenet", "http://...")],
            key=lambda r: (r[0].strip().lower(), (r[1] or "").strip().lower())
        )
        -> [("ImageNet", "http://...")]
    """
    seen: set[Hashable] = set()
    out: List[T] = []
    for v in values:
        k: Hashable = key(v) if key is not None else v  # type: ignore[assignment]
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out

def dedup_datasets_preserve_order(
    rows: Iterable[Tuple[str, Optional[str]]]
) -> List[Tuple[str, Optional[str]]]:
    """
    Convenience helper for (name, url?) dataset tuples:
    - Dedups case-insensitively on trimmed name + url.
    - Returns trimmed values.
    """
    # First, dedup by a normalized key using the generalized function
    deduped = dedup_preserve_order(
        rows,
        key=lambda r: (r[0].strip().lower(), (r[1] or "").strip().lower())
    )
    # Then, normalize outputs (trim whitespace)
    return [(name.strip(), (url.strip() if url else None)) for name, url in deduped]

def filter_allowed(values: Iterable[str], allowed: List[str]) -> List[str]:
    # Case-insensitive mapping to canonical labels
    canon = {a.lower(): a for a in allowed}
    out = []
    for v in values:
        k = v.lower().strip()
        if k in canon:
            out.append(canon[k])
    return dedup_preserve_order(out)

def labels_to_allowed_list_str(labels: List[str]) -> str:
    # e.g., 'Lagoon; Back slope; Foreslope (outer reef slope)'
    return "; ".join(labels)

def items_to_datasets(items: List[Dict[str, Any]]) -> Datasets:
    """
    Convert verified/unverified evidence items into Datasets(datasets=[...]).
    Assumes 'value' holds the dataset name and 'url' (optional) may be present.
    """
    rows: List[Tuple[str, Optional[str]]] = []
    for x in items:
        name = (x.get("value") or "").strip()
        if not name:
            continue
        url = x.get("url")
        if isinstance(url, str):
            url = url.strip() or None
        else:
            url = None
        rows.append((name, url))

    rows = dedup_datasets_preserve_order(rows)
    return Datasets(datasets=[Dataset(name=n, url=u) for (n, u) in rows])
