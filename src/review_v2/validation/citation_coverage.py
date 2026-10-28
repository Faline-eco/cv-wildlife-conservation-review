"""Validation 5.4: how complete is the corpus? Seed bias, leave-one-out recovery and capture-recapture.

Usage: python src/review_v2/validation/citation_coverage.py   (after citations/fetch_citations.py for hop1 + hop2)

Population: eligible papers (corpus/papers.csv). Two independent-ish ways of finding a paper:
  index arm    : the paper's DOI is in a database / library search result (search/records.csv,
                 library_records.csv, to_screen_ieee.csv, to_screen_libs2.csv)
  citation arm : the paper is linked by a citation (either direction, OpenAlex) to another eligible paper.
                 Every eligible paper is a seed (hop1: old corpus, hop2: the rest), so this is leave-one-out by
                 construction: a paper's own seed role does not count.
(i)   seed bias: per citation-found paper, the number of other eligible papers linking to it; share reachable
      through one link only; recovery by seed group (old manual / old automated corpus / new).
(ii)  leave-one-out recovery of the manual arm of the original review through the citation arm.
(iii) Chapman capture-recapture estimate of the number of eligible papers that the two arms could find, and the
      share the corpus covers. The arms are positively dependent (well-cited papers are easier to find in
      databases too), which biases the estimate downwards, so the covered share is an upper bound. Separately
      for 2014-2023 and 2024-2026, because the database arm was run over both periods but the libraries only for
      2024-2026.
Output: validation/citation_coverage.json, validation/coverage_arms.csv
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402
from review_v2.validation.stats import wilson  # noqa: E402

V2 = ROOT / "review_output" / "v2"
CIT = V2 / "citations"


def jsonl(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def chapman(n1, n2, m):
    n = (n1 + 1) * (n2 + 1) / (m + 1) - 1
    var = (n1 + 1) * (n2 + 1) * (n1 - m) * (n2 - m) / ((m + 1) ** 2 * (m + 2))
    return {"n_index": n1, "n_citation": n2, "both": m, "estimate": n, "lo": n - 1.96 * var ** 0.5,
            "hi": n + 1.96 * var ** 0.5}


if __name__ == "__main__":
    p = pd.read_csv(V2 / "corpus" / "papers.csv")
    p = p[p["eligible"] & p["doi"].notna()].drop_duplicates("doi").copy()
    p["year"] = p["year"].fillna(2014).astype(int).clip(lower=2014)
    elig = set(p["doi"])

    index = set()
    for f in ("records.csv", "library_records.csv", "to_screen_ieee.csv", "to_screen_libs2.csv"):
        index |= {norm_doi(d) for d in pd.read_csv(V2 / "search" / f, usecols=["doi"], low_memory=False)["doi"]
                  if isinstance(d, str)}

    oa = {}       # OpenAlex id -> DOI for eligible papers
    for run in ("hop1", "hop2"):
        for s in jsonl(CIT / run / "seeds.jsonl"):
            if s["id"] and s["doi"] in elig:
                oa[s["id"]] = s["doi"]
        # works found by the citation search: papers found in hop 2 were never seeds themselves (fixed 2026-10-27;
        # before, they counted as found by neither arm)
        for w in jsonl(CIT / run / "works.jsonl"):
            d = norm_doi(w.get("doi") or "")
            if w.get("id") and d in elig:
                oa.setdefault(w["id"], d)
    links = defaultdict(set)   # eligible DOI -> other eligible DOIs linked to it
    for run in ("hop1", "hop2"):
        for e in jsonl(CIT / run / "edges.jsonl"):
            d = oa.get(e["work"])
            if d and e["seed"] in elig and e["seed"] != d:
                links[d].add(e["seed"])
                links[e["seed"]].add(d)
    p["in_index"] = p["doi"].isin(index)
    p["in_citation"] = p["doi"].map(lambda d: len(links.get(d, ())) > 0)
    p["n_links"] = p["doi"].map(lambda d: len(links.get(d, ())))
    p["in_openalex"] = p["doi"].isin(set(oa.values()))

    old = {k: {norm_doi(d) for d in pd.read_parquet(ROOT / "review_output" / "gapminder" / f"2026130_{k}.parquet")
               ["doi"] if isinstance(d, str)} for k in ("manual", "auto")}
    p["group"] = "new"
    p.loc[p["doi"].isin(old["auto"]), "group"] = "old automated (citation) arm"
    p.loc[p["doi"].isin(old["manual"]), "group"] = "old manual arm"

    cit = p[p["in_citation"]]
    res = {"papers": len(p), "in_openalex": int(p["in_openalex"].sum()),
           "index_arm": wilson(int(p["in_index"].sum()), len(p)),
           "citation_arm": wilson(int(p["in_citation"].sum()), len(p)),
           "both": int((p["in_index"] & p["in_citation"]).sum()),
           "neither": int((~p["in_index"] & ~p["in_citation"]).sum()),
           "seed_bias": {"median_links": float(cit["n_links"].median()),
                         "one_link_only": wilson(int((cit["n_links"] == 1).sum()), len(cit)),
                         "links_histogram": {str(k): v for k, v in sorted(Counter(
                             cit["n_links"].clip(upper=20)).items())},
                         "recovery_by_group": {g: wilson(int(x["in_citation"].sum()), len(x))
                                               for g, x in p.groupby("group")}},
           "leave_one_out_manual_arm": wilson(int(p.loc[p["group"] == "old manual arm", "in_citation"].sum()),
                                              int((p["group"] == "old manual arm").sum())),
           "capture_recapture": {},
           # publishers the first version could not search (Reviewer 3): MDPI and the Nature portfolio
           "publishers": {name: {"eligible": int(g.shape[0]), "in_index": int(g["in_index"].sum()),
                                 "in_citation": int(g["in_citation"].sum())}
                          for name, g in (("mdpi", p[p["doi"].str.startswith("10.3390/")]),
                                          ("nature", p[p["doi"].str.startswith("10.1038/")]))}}
    for name, g in (("all", p), ("2014-2023", p[p["year"] <= 2023]), ("2024-2026", p[p["year"] >= 2024])):
        c = chapman(int(g["in_index"].sum()), int(g["in_citation"].sum()), int((g["in_index"] & g["in_citation"]).sum()))
        c["corpus"] = len(g)
        c["union"] = int((g["in_index"] | g["in_citation"]).sum())
        c["covered_share"] = min(1.0, c["union"] / c["estimate"])
        c["corpus_share"] = min(1.0, len(g) / c["estimate"])
        c["covered_share_range"] = [min(1.0, c["union"] / c["hi"]), min(1.0, c["union"] / max(c["lo"], 1))]
        res["capture_recapture"][name] = c
    # per paper, for the composition of the arms (seed bias, Reviewer 2): make_figures.arm_composition
    p[["doi", "year", "in_index", "in_citation", "n_links"]].to_csv(V2 / "validation" / "coverage_arms.csv",
                                                                    index=False, encoding="utf-8")
    (V2 / "validation" / "citation_coverage.json").write_text(json.dumps(res, indent=1, default=float),
                                                               encoding="utf-8")
    print(json.dumps(res, indent=1, default=float))
