"""DOIs for the next extraction round: screened papers (include or fulltext) that have a PDF but no record.

Usage: python src/review_v2/extraction/next_round.py <name>   (writes fetch/<name>, e.g. round9_dois.txt)
Run fulltext/inventory.py first; then prepare.py and extract.py on the written list.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.fulltext.prepare import paper_id  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

R = ROOT / "review_output" / "v2"

if __name__ == "__main__":
    have = set(pd.read_csv(R / "fulltext/zotero_pdfs.csv")["doi"].map(norm_doi))
    done = {p.stem for p in (R / "extraction/corpus_v2_opus").glob("*.json")}
    ta = pd.read_csv(R / "screening/ta_final.csv", low_memory=False)
    ta = ta[ta["doi"].notna() & (ta["final"] != "exclude")]
    manual = {norm_doi(x) for x in (R / "fetch/batch0_manual_included_missing_dois.txt").read_text().split()}
    for name, dois in [("include", set(ta.loc[ta["final"] == "include", "doi"]) | manual),
                       ("fulltext", set(ta.loc[ta["final"] == "fulltext", "doi"]))]:
        with_pdf = dois & have
        print(f"{name}: {len(dois)} DOIs, {len(with_pdf)} with PDF, "
              f"{sum(paper_id(d) in done for d in with_pdf)} coded")
    todo = sorted(d for d in (set(ta["doi"]) | manual) & have if paper_id(d) not in done)
    (R / "fetch" / sys.argv[1]).write_text("\n".join(todo) + "\n", encoding="utf-8")
    print("to code:", len(todo))
