"""Elsevier PDFs saved by hand from fetch/elsevier_by_hand.html, copied into <PDF_STORE>/pdf_chrome/.

Usage: python src/review_v2/fulltext/import_elsevier.py [folder ...]

Looks for 1-s2.0-<PII>-main*.pdf in the given folders (default: the Downloads folder and its subfolders),
maps the PII to the DOI with fetch/elsevier_pii.json and stores the file as <paper_id>.pdf, where
inventory.py picks it up. Files that are not a PDF of at least two pages are reported and skipped.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.fulltext.fetch_direct import is_pdf  # noqa: E402
from review_v2.fulltext.prepare import OUT, PDF_STORE, paper_id  # noqa: E402
from review_v2.search.merge import ROOT  # noqa: E402

PII = ROOT / "review_output" / "v2" / "fetch" / "elsevier_pii.json"
DEST = PDF_STORE / "pdf_chrome"

if __name__ == "__main__":
    folders = [Path(f) for f in sys.argv[1:]] or [Path.home() / "Downloads"]
    by_pii = {p: doi for doi, p in json.loads(PII.read_text()).items()}
    DEST.mkdir(parents=True, exist_ok=True)
    counts = {"copied": 0, "already_there": 0, "not_a_pdf": 0, "unknown_pii": 0}
    for folder in folders:
        for f in folder.rglob("1-s2.0-*.pdf"):
            m = re.match(r"1-s2\.0-(S\w+?)-main", f.name)
            doi = by_pii.get(m.group(1)) if m else None
            if not doi:
                counts["unknown_pii"] += 1
                continue
            target = DEST / f"{paper_id(doi)}.pdf"
            if target.exists():
                counts["already_there"] += 1
                continue
            content = f.read_bytes()
            if not is_pdf(content):
                counts["not_a_pdf"] += 1
                print("  not a full PDF:", f)
                continue
            target.write_bytes(content)
            counts["copied"] += 1
    print(counts)
