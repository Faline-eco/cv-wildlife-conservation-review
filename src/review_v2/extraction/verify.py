"""Deterministic evidence check: is the quote on the cited page, and in which section?

Each item that carries a quote gets an `evidence` field:
  {status: exact | fuzzy | other_page | not_found | none, score, page, section}
An item counts as verified if status is exact or fuzzy and the section is not introduction or related work.
"""
import re
import unicodedata

from rapidfuzz import fuzz

FUZZY_MIN = 90
REJECTED_SECTIONS = {"introduction", "related", "references"}


def norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[‐-―\-]", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _section_at(page, pos_norm, page_norm):
    """Section label at a position of the normalised page text."""
    lines = page["text"].splitlines()
    marks = page["sections"]
    section, consumed = marks[0]["section"], 0
    starts = {m["line"]: m["section"] for m in marks}
    for i, line in enumerate(lines):
        if i in starts:
            section = starts[i]
        consumed += len(norm(line)) + 1
        if consumed > pos_norm:
            break
    return section


def locate(quote, page_no, paper):
    q = norm(quote)
    if len(q) < 8:
        return {"status": "none", "score": 0, "page": page_no, "section": None}
    pages = {p["page"]: p for p in paper["pages"]}
    order = ([page_no] if page_no in pages else []) + [n for n in pages if n != page_no]
    best = {"status": "not_found", "score": 0, "page": page_no, "section": None}
    for n in order:
        text = norm(pages[n]["text"])
        pos = text.find(q)
        if pos >= 0:
            score, start = 100, pos
        else:
            al = fuzz.partial_ratio_alignment(q, text)
            score, start = (al.score, al.dest_start) if al else (0, 0)
        if score > best["score"]:
            status = "exact" if score == 100 else "fuzzy" if score >= FUZZY_MIN else "not_found"
            if status != "not_found" and n != page_no:
                status = "other_page"
            best = {"status": status, "score": round(score, 1), "page": n,
                    "section": _section_at(pages[n], start, text)}
        if best["score"] == 100:
            break
    return best


def verified(ev):
    return ev["status"] in ("exact", "fuzzy", "other_page") and ev["section"] not in REJECTED_SECTIONS


def _walk(node):
    if isinstance(node, dict):
        if "quote" in node and "page" in node:
            yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def check_record(record, paper):
    for item in _walk(record):
        item["evidence"] = locate(item["quote"], item["page"], paper)
    return record
