"""PDF -> page-wise text with section labels. The same text feeds the extractor and the evidence check.

Usage: python src/review_v2/fulltext/prepare.py <dois.txt>   (DOIs looked up in zotero_pdfs.csv)
Output: review_output/v2/fulltext/text/<paper_id>.json
        {doi, pdf, sha256, n_pages, status, pages: [{page, text, sections: [label at page start, ...]}]}
status: ok | scanned (no usable text layer) | error
"""
import os
import hashlib
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

OUT = ROOT / "review_output" / "v2" / "fulltext"
TEXT = OUT / "text"
# PDFs fetched directly or saved by hand (pdf_direct/, pdf_chrome/); on the network share since 2026-10-25, D: was full
PDF_STORE = Path(os.environ.get("PDF_STORE", ROOT / "pdf_store"))

# heading -> section class; a quote is acceptable evidence only in the classes marked body
HEADINGS = [
    ("abstract", r"abstract|summary"),
    ("introduction", r"introduction|background|motivation"),
    ("related", r"related\s+works?|literature\s+review|previous\s+work|prior\s+work|state\s+of\s+the\s+art"),
    ("references", r"references|bibliography|literature\s+cited|works\s+cited"),
    ("back", r"acknowledge?ments?|funding|author\s+contributions?|conflicts?\s+of\s+interest|"
             r"declaration\s+of\s+.{3,40}|data\s+availability(\s+statement)?|supplementary\s+.{3,40}|"
             r"appendix.{0,40}"),
    ("body", r"(materials?\s+and\s+)?methods?|methodology|materials?|data(sets?)?(\s+.{3,40})?|"
             r"study\s+(area|site)s?|experiments?(\s+.{3,40})?|experimental\s+.{3,40}|results?(\s+.{3,40})?|"
             r"evaluation|implementation(\s+.{3,40})?|proposed\s+.{3,40}|approach|system\s+.{3,40}|"
             r"discussions?|conclusions?(\s+.{3,40})?|limitations?"),
]
NUM = r"(?:\d{1,2}(?:\.\d{1,2})*\.?|[IVX]{1,4}\.)?[\s|]*"
HEADING_RE = [(label, re.compile(rf"^{NUM}(?:{pat})\s*[:.]?$", re.I)) for label, pat in HEADINGS]


def paper_id(doi):
    """Reversible file name for a DOI."""
    return doi.replace("/", "__").replace(":", "--")


def heading_label(line):
    line = line.strip()
    # a heading starts with a number or a capital and is not the end of a wrapped sentence
    if not 3 <= len(line) <= 60 or not (line[0].isdigit() or line[0].isupper()) or line.endswith((",", ";")):
        return None
    if line.endswith(".") and not line[0].isdigit():
        return None
    for label, rx in HEADING_RE:
        if rx.match(line):
            return label
    return None


def prepare(doi, pdf):
    raw = Path(pdf).read_bytes()
    rec = {"doi": doi, "pdf": pdf, "sha256": hashlib.sha256(raw).hexdigest(), "status": "ok", "pages": []}
    doc = pymupdf.open(stream=raw, filetype="pdf")
    rec["n_pages"] = doc.page_count
    current = "front"
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text", sort=False)
        text = re.sub(r"-\n(?=[a-z])", "", text)            # undo hyphenation at line breaks
        lines, marks = [], [{"line": 0, "section": current}]
        for line in text.splitlines():
            label = heading_label(line)
            if label == "introduction" and current not in ("front", "abstract"):
                label = None                                # "Background" inside the body is not the introduction
            if label and label != current:
                current = label
                marks.append({"line": len(lines), "section": current})
            lines.append(line.rstrip())
        rec["pages"].append({"page": i, "text": "\n".join(lines), "sections": marks})
    chars = sum(len(p["text"]) for p in rec["pages"])
    if chars < 300 * max(rec["n_pages"], 1):
        rec["status"] = "scanned"
    return rec


def render(rec, max_chars=180_000):
    """Text handed to the extractor: page markers, reference list and back matter dropped."""
    parts = []
    for p in rec["pages"]:
        lines = p["text"].splitlines()
        marks = p["sections"] + [{"line": len(lines), "section": None}]
        keep = []
        for m, nxt in zip(marks, marks[1:]):
            if m["section"] != "references":
                keep += lines[m["line"]:nxt["line"]]
        if keep:
            parts.append(f"<<page {p['page']}>>\n" + "\n".join(keep))
    return "\n\n".join(parts)[:max_chars]


if __name__ == "__main__":
    TEXT.mkdir(parents=True, exist_ok=True)
    pdfs = pd.read_csv(OUT / "zotero_pdfs.csv").set_index("doi")["pdf"]
    dois = [d for d in map(norm_doi, Path(sys.argv[1]).read_text().splitlines()) if d]
    stats = {"ok": 0, "scanned": 0, "error": 0, "no_pdf": 0, "cached": 0}
    for doi in dict.fromkeys(dois):
        target = TEXT / f"{paper_id(doi)}.json"
        if target.exists():
            stats["cached"] += 1
            continue
        if doi not in pdfs.index:
            stats["no_pdf"] += 1
            continue
        try:
            rec = prepare(doi, pdfs[doi])
        except Exception as e:  # noqa: BLE001
            rec = {"doi": doi, "pdf": pdfs[doi], "status": "error", "error": str(e)[:300], "pages": []}
        stats[rec["status"]] += 1
        target.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    print(stats)
