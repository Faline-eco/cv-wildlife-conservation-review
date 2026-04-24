"""
Lightweight PDF pre-screening to save cost/time before LLM calls.

- Tries to extract text from the first N pages using PyPDF2 (if installed).
- Tries to detect presence of images via page XObject resources (best-effort).
- Computes simple keyword hit counts and a relevance score.
- Returns a structured PreScreenResult that the pipeline can use to decide
  whether to skip expensive extractions when clearly irrelevant.

All functions are defensive: if parsing fails or PyPDF2 isn't installed,
they degrade gracefully and still return a valid PreScreenResult.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


# ---- Default keyword sets (tune to your corpus) ----

DEFAULT_WILDLIFE_TERMS = [
    # habitats / conservation
    "conservation", "biodiversity", "iucn", "habitat", "ecosystem",
    # field methods
    "camera trap", "uav", "drone", "rov", "auv", "acoustic",
    # marine/terrestrial hints
    "reef", "marine", "terrestrial", "freshwater", "forest", "savanna", "grassland",
    # typical taxa words (broad)
    "mammal", "bird", "avian", "fish", "amphibian", "reptile", "invertebrate",
    # common species exemplars (you can expand)
    "elephant", "tiger", "shark", "whale", "dolphin", "turtle", "penguin",
]

DEFAULT_CV_TERMS = [
    # tasks
    "detection", "segmentation", "classification", "tracking", "pose estimation",
    "re-identification", "counting",
    # methods/models
    "cnn", "resnet", "unet", "yolo", "rcnn", "vit", "transformer",
    "hog", "svm", "gan", "diffusion", "optical flow", "slam", "sift", "surf",
    # generic DL/vision keywords
    "deep learning", "computer vision", "convolutional", "backbone",
]


@dataclass
class PreScreenResult:
    path: Path
    page_count: Optional[int] = None
    has_text: Optional[bool] = None
    has_images: Optional[bool] = None
    text_sample: str = ""
    wildlife_hits: Dict[str, int] = field(default_factory=dict)
    cv_hits: Dict[str, int] = field(default_factory=dict)
    score: int = 0
    recommend_skip: bool = False
    error: Optional[str] = None


def _try_import_pypdf2():
    try:
        import PyPDF2  # type: ignore
        return PyPDF2
    except Exception:
        return None


def _extract_text_first_pages(pdf_path: Path, max_pages: int) -> Tuple[str, Optional[int], Optional[bool], Optional[str]]:
    """
    Extract text from the first `max_pages` pages using PyPDF2 if available.
    Returns (text, page_count, has_text, error).
    """
    PyPDF2 = _try_import_pypdf2()
    if PyPDF2 is None:
        return ("", None, None, None)

    try:
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            n_pages = len(reader.pages)
            text_parts: List[str] = []
            for i in range(min(max_pages, n_pages)):
                try:
                    page = reader.pages[i]
                    text_parts.append(page.extract_text() or "")
                except Exception:
                    # Per-page failures shouldn't kill the run
                    text_parts.append("")
            text = "\n".join(text_parts).strip()
            has_text = bool(text)
            return (text, n_pages, has_text, None)
    except Exception as e:
        return ("", None, None, str(e))


def _detect_images_best_effort(pdf_path: Path, max_pages: int) -> Optional[bool]:
    """
    Best-effort image presence detection via PyPDF2 page XObjects.
    Returns True/False if determined, otherwise None.
    """
    PyPDF2 = _try_import_pypdf2()
    if PyPDF2 is None:
        return None

    try:
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            n_pages = len(reader.pages)
            limit = min(max_pages, n_pages)
            for i in range(limit):
                try:
                    page = reader.pages[i]
                    resources = page.get("/Resources") or {}
                    xobj = resources.get("/XObject")
                    if not xobj:
                        continue
                    # Resolve indirect objects
                    xobj = xobj.get_object()
                    for name, obj in xobj.items():
                        try:
                            subtype = obj.get("/Subtype")
                            if subtype and str(subtype) == "/Image":
                                return True
                        except Exception:
                            continue
                except Exception:
                    continue
            return False
    except Exception:
        return None


def _count_hits(text: str, terms: Iterable[str]) -> Dict[str, int]:
    """
    Count case-insensitive occurrences of each term in the text.
    """
    text_lower = text.lower()
    hits: Dict[str, int] = {}
    for t in terms:
        # Basic word-ish boundary; still catches phrases
        patt = r"\b" + re.escape(t.lower()) + r"\b"
        count = len(re.findall(patt, text_lower))
        if count > 0:
            hits[t] = count
    return hits


def quick_relevance_score(
    text: str,
    wildlife_terms: Iterable[str] = DEFAULT_WILDLIFE_TERMS,
    cv_terms: Iterable[str] = DEFAULT_CV_TERMS,
) -> Tuple[int, Dict[str, int], Dict[str, int]]:
    """
    Very simple score: total hits of wildlife + CV keywords.
    You can replace with a TF-IDF or embedding check later if needed.
    """
    w_hits = _count_hits(text, wildlife_terms)
    c_hits = _count_hits(text, cv_terms)
    score = sum(w_hits.values()) + sum(c_hits.values())
    return score, w_hits, c_hits


def pre_screen_pdf(
    pdf_path: Path,
    *,
    max_pages: int = 3,
    skip_threshold: int = 0,
    wildlife_terms: Iterable[str] = DEFAULT_WILDLIFE_TERMS,
    cv_terms: Iterable[str] = DEFAULT_CV_TERMS,
) -> PreScreenResult:
    """
    Extract a small text sample and image hint from the first few pages,
    compute a keyword score, and (optionally) recommend skipping LLM extraction.

    Args:
        pdf_path: PDF to inspect
        max_pages: first N pages to sample
        skip_threshold: recommend_skip = score <= skip_threshold
        wildlife_terms / cv_terms: customizable keyword sets

    Returns:
        PreScreenResult with best-effort fields filled.
    """
    pdf_path = Path(pdf_path)
    text, page_count, has_text, err = _extract_text_first_pages(pdf_path, max_pages)
    has_images = _detect_images_best_effort(pdf_path, max_pages)

    score, w_hits, c_hits = quick_relevance_score(text, wildlife_terms, cv_terms)
    recommend_skip = (score <= skip_threshold)

    return PreScreenResult(
        path=pdf_path,
        page_count=page_count,
        has_text=has_text,
        has_images=has_images,
        text_sample=text[:4000],  # keep it short
        wildlife_hits=w_hits,
        cv_hits=c_hits,
        score=score,
        recommend_skip=recommend_skip,
        error=err,
    )
