"""How good would GBIF fuzzy matching have been? Comparison with the LLM + exact-match route.

Usage: python src/review_v2/taxa/evaluate.py   (after normalise.py)

A. Common names (items without a scientific name): GBIF match in default (fuzzy) mode on the name as written,
   vs the LLM translation matched exactly. Counted: GBIF returns nothing usable (kingdom only / no match), GBIF
   returns a taxon that agrees with the LLM route (same class and, where both have one, same genus), GBIF returns
   a conflicting taxon (a different class or genus = false positive).
B. Scientific names that the strict match rejects: GBIF fuzzy result vs the LLM correction (exact match).
The disagreements are written to taxa/fuzzy_disagreements.csv for inspection.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.taxa import gbif, items  # noqa: E402
from review_v2.taxa.llm_names import CACHE as LLM_CACHE, entry  # noqa: E402

RANKED = ("SPECIES", "SUBSPECIES", "GENUS", "FAMILY", "ORDER", "CLASS", "PHYLUM")


def cls(m):
    return gbif.standard_class(m)


def compare(fz, ref):
    if fz.get("matchType") in (None, "NONE", "ERROR") or fz.get("rank") not in RANKED or fz.get("kingdom") != "Animalia":
        return "gbif_no_taxon"
    if not ref:
        return "llm_no_taxon"
    if cls(fz) != cls(ref):
        return "conflict_class"
    if fz.get("genus") and ref.get("genus") and fz["genus"] != ref["genus"]:
        return "conflict_genus"
    return "agree"


if __name__ == "__main__":
    d = items.load()
    llm = json.loads(LLM_CACHE.read_text(encoding="utf-8"))
    rows = []
    common = d[d["sci"].isna()].drop_duplicates("name")
    gbif.match_many(sorted(set(common["name"].map(items.common_key))), strict=False)
    gbif.match_many(sorted(set(d["sci"].dropna())), strict=False)
    for r in common.itertuples():
        t = llm.get(entry(r.name.strip(), r.scientific_name.strip()))
        if not t or t["kind"] != "taxon":
            continue
        ref = gbif.match(t["scientific_name"]) if t["scientific_name"] else {}
        ref = ref if gbif.accepted(ref) and ref.get("matchType") == "EXACT" else None
        fz = gbif.match(items.common_key(r.name), strict=False)
        rows.append({"set": "A_common_name", "input": r.name, "gbif_fuzzy": fz.get("canonicalName"),
                     "gbif_rank": fz.get("rank"), "llm_exact": (ref or {}).get("canonicalName"),
                     "result": compare(fz, ref)})
    sci = d.dropna(subset=["sci"]).drop_duplicates("sci")
    for r in sci.itertuples():
        if gbif.accepted(gbif.match(r.sci)):
            continue
        t = llm.get(entry(r.name.strip(), r.sci))
        ref = gbif.match(t["scientific_name"]) if t and t["kind"] == "taxon" and t["scientific_name"] else {}
        ref = ref if gbif.accepted(ref) and ref.get("matchType") == "EXACT" else None
        fz = gbif.match(r.sci, strict=False)
        rows.append({"set": "B_rejected_scientific_name", "input": r.sci, "gbif_fuzzy": fz.get("canonicalName"),
                     "gbif_rank": fz.get("rank"), "llm_exact": (ref or {}).get("canonicalName"),
                     "result": compare(fz, ref)})
    df = pd.DataFrame(rows)
    print(pd.crosstab(df["set"], df["result"], margins=True).to_string())
    df[df["result"].str.startswith("conflict")].to_csv(gbif.DIR / "fuzzy_disagreements.csv", index=False,
                                                       encoding="utf-8")
    df.to_csv(gbif.DIR / "fuzzy_evaluation.csv", index=False, encoding="utf-8")
