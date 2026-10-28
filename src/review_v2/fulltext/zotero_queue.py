"""DOI queue for the Zotero console script (zotero_find_pdfs.js): screened papers still without a PDF.

Usage: python src/review_v2/fulltext/zotero_queue.py
Run inventory.py first. Springer book chapters are left out (no institutional access). The queue is
ordered round-robin over publishers, so that no publisher receives two requests in a row.
"""
import sys
from collections import defaultdict
from itertools import zip_longest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

FETCH = ROOT / "review_output" / "v2" / "fetch"

if __name__ == "__main__":
    have = set(pd.read_csv(ROOT / "review_output" / "v2" / "fulltext" / "zotero_pdfs.csv")["doi"])
    by_publisher = defaultdict(list)
    for name in ["FINAL_1_include_2024_2026", "FINAL_1_include_2014_2023", "FINAL_2_fulltext_2024_2026",
                 "FINAL_2_fulltext_2014_2023"]:
        for doi in map(norm_doi, (FETCH / f"{name}_dois.txt").read_text().split()):
            if doi and doi not in have and not doi.startswith("10.1007/978-"):
                by_publisher[doi.split("/")[0]].append(doi)
    groups = sorted(by_publisher.values(), key=len, reverse=True)
    queue = [d for row in zip_longest(*groups) for d in row if d]
    (FETCH / "zotero_find_pdf_dois.txt").write_text("\n".join(queue) + "\n", encoding="utf-8")
    print(len(queue), "DOIs;", {g[0].split("/")[0]: len(g) for g in groups[:6]})
