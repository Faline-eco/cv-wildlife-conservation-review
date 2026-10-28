"""Screening input from a citation run: new works, filtered by metadata and deduplicated against everything known.

Usage: python src/review_v2/citations/candidates.py <run_name>     e.g. hop2

Keeps works of the run (citations/<run>/works.jsonl) that are linked to a seed of the run, lie in the year window,
are an article, conference paper or preprint, are in English (or have no language), and are not yet known:
not screened (screening/ta_final.csv), not in a search result, not coded, not a candidate of another run.
Output: citations/<run>/to_screen.csv (columns as for the other screening inputs) and a saturation report:
the share of the run's in-window works that were already known (evidence that one hop saturates).
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

V2 = ROOT / "review_output" / "v2"
CIT = V2 / "citations"
TYPES = {"article", "conference-paper", "preprint", "proceedings-article"}


def jsonl(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


if __name__ == "__main__":
    run = sys.argv[1]
    out = CIT / run
    linked = {e["work"] for e in jsonl(out / "edges.jsonl") if e["work"]}
    works = pd.DataFrame([w for w in jsonl(out / "works.jsonl") if not w.get("out_of_window")])
    other = pd.concat([pd.DataFrame([w for w in jsonl(f) if not w.get("out_of_window")])
                       for f in CIT.glob("*/works.jsonl") if f.parent.name != run], ignore_index=True)
    known = set(pd.read_csv(V2 / "screening" / "ta_final.csv", usecols=["doi"], low_memory=False)["doi"].dropna())
    for f in ("records.csv", "library_records.csv", "to_screen_ieee.csv", "to_screen_libs2.csv"):
        known |= set(pd.read_csv(V2 / "search" / f, usecols=["doi"], low_memory=False)["doi"].dropna())
    known |= set(pd.read_csv(V2 / "corpus" / "papers.csv", usecols=["doi"])["doi"].dropna())
    known = {norm_doi(d) for d in known if isinstance(d, str)}
    # works stored by another run but reached by this run's seeds count as reached here too
    reached = pd.concat([works, other[other["id"].isin(linked)]], ignore_index=True).drop_duplicates("id")
    reached = reached[reached["id"].isin(linked)]
    ok = reached["doc_type"].isin(TYPES) & (reached["language"].isna() | (reached["language"] == "en"))
    ok &= reached["title"].notna()
    cand = reached[ok].copy()
    cand["doi"] = cand["doi"].map(lambda d: norm_doi(d) if isinstance(d, str) else None)
    cand["known"] = cand["doi"].isin(known)
    print(f"{run}: {len(reached)} in-window works linked to seeds, {len(cand)} after type/language filter, "
          f"{int(cand['known'].sum())} already known ({100 * cand['known'].mean():.1f}%)")
    new = cand[~cand["known"]].copy()
    new = pd.concat([new[new["doi"].isna()], new[new["doi"].notna()].drop_duplicates("doi")])
    new["id"] = new["doi"].fillna(new["id"])
    new["keywords"] = ""
    new["sources"] = f"citations_{run}"
    new["in_old_candidates"] = False
    cols = ["id", "doi", "title", "abstract", "year", "venue", "doc_type", "keywords", "sources", "in_old_candidates"]
    new[cols].to_csv(out / "to_screen.csv", index=False, encoding="utf-8")
    json.dump({"linked_in_window": len(reached), "after_filter": len(cand), "already_known": int(cand["known"].sum()),
               "new": len(new), "without_abstract": int(new["abstract"].isna().sum())},
              open(out / "candidates_report.json", "w"), indent=1)
    print(f"to screen: {len(new)} ({int(new['abstract'].isna().sum())} without abstract) -> {out / 'to_screen.csv'}")
