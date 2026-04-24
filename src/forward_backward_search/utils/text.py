from __future__ import annotations

from typing import Iterable, List, Optional
import math


def is_nan(value) -> bool:
    # pandas uses float('nan') for empty cells; guard without importing pandas here
    try:
        return isinstance(value, float) and math.isnan(value)
    except Exception:
        return False


def normalize_doi(input_value: str) -> Optional[str]:
    """Return DOI part (no scheme/host), or None if it cannot be recognized.
    Accepts either 'https://doi.org/...' or a bare DOI like '10.1145/...'."""
    if not isinstance(input_value, str):
        return None
    v = input_value.strip()
    if not v:
        return None
    if v.lower().startswith("http://dx.doi.org/"):
        v = v[len("http://dx.doi.org/"):]
    if v.lower().startswith("https://dx.doi.org/"):
        v = v[len("https://dx.doi.org/"):]
    if v.lower().startswith("http://doi.org/"):
        v = v[len("http://doi.org/"):]
    if v.lower().startswith("https://doi.org/"):
        v = v[len("https://doi.org/"):]
    return v if '/' in v else None  # crude check that it's a DOI-like string


def doi_url(doi: str) -> str:
    return f"https://doi.org/{doi}"


def parse_list_cell(cell) -> List[str]:
    """Best-effort parsing of a cell that may contain a list-like value.
    Handles NaN, a single string, or a Python-list-like string (e.g., "['A', 'B']")."""
    if is_nan(cell):
        return []
    if isinstance(cell, list):
        return [str(x).strip() for x in cell if str(x).strip()]
    if isinstance(cell, str):
        s = cell.strip()
        if s.startswith('[') and s.endswith(']'):
            # Try to eval safely: use split heuristics to avoid eval
            inner = s[1:-1].strip()
            if not inner:
                return []
            parts = [p.strip() for p in inner.split(',')]
            norm = []
            for p in parts:
                if p.startswith("'") and p.endswith("'"):
                    p = p[1:-1]
                if p.startswith('"') and p.endswith('"'):
                    p = p[1:-1]
                p = p.strip()
                if p:
                    norm.append(p)
            return norm
        return [s]
    # Fallback
    return [str(cell).strip()]
