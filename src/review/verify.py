# wildcv_review/preprocessing_verify.py (new small helper)
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Tuple
import re
from rapidfuzz import fuzz

def _load_pdf_texts(pdf_path: Path) -> List[str]:
    try:
        import pypdf  # type: ignore
    except Exception:
        return []
    try:
        pages = []
        with open(pdf_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for i in range(len(reader.pages)):
                try:
                    t = reader.pages[i].extract_text() or ""
                except Exception:
                    t = ""
                pages.append(t)
        return pages
    except Exception:
        return []

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _match_page(qn: str, text: str, use_fuzzy: bool) -> float:
    norm_text = _norm(text)
    if qn in norm_text:
        return 100
    if use_fuzzy:
        score = fuzz.partial_ratio(qn, norm_text)
        return score
    return 0

def verify_items_against_pdf(
    pdf_path: Path,
    items: List[dict],
    use_fuzzy: bool = True,
    fuzzy_threshold: int = 85
) -> Tuple[List[dict], List[dict]]:
    """
    items: [{"value": str, "evidence": {"page": int|None, "quote": str}}, ...]
    Returns: (verified_items, unverified_items)
    """
    pages = _load_pdf_texts(pdf_path)
    if not pages:
        return ([], items)

    verified, unverified = [], []

    for it in items:
        ev = (it or {}).get("evidence") or {}
        q = ev.get("quote") or ""
        p = ev.get("page")
        if not q:
            unverified.append(it)
            continue

        qn = _norm(q)
        found = False

        # Try page-based search if possible
        # if p and 1 <= int(p) <= len(pages):
        #     found = match_page(pages[int(p)-1])
        # else:
        matched_score = 0
        for txt in pages:
            matched_score = _match_page(qn, txt, use_fuzzy)
            if matched_score >= fuzzy_threshold:
                found = True
                break

        it["match_score"] = matched_score

        if found:
            verified.append(it)
        else:
            unverified.append(it)

    return verified, unverified
