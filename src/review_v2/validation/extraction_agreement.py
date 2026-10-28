"""Validation 5.2: agreement of the extraction with the manual coding of the original review.

Usage: python src/review_v2/validation/extraction_agreement.py

Papers: manually coded papers (gapminder/2026130_manual.parquet) that the extractor also finds eligible
(widened scope). Per field, micro precision / recall / F1 over (paper, value) pairs with the manual coding as
reference, paper-level bootstrap intervals, and the share of papers with identical sets. Verified items (main result) and all items (in brackets: the verification step
trades recall for precision).
Matching rules (stated in the paper):
- closed vocabularies (platform, habitat, spectrum, task): identity after mapping the v2 vocabulary to the
  coarser manual one (compare_manual.py maps; "Other" / "Unknown" / "Not reported" dropped on both sides);
- country: identity after alias merging;
- taxa: same GBIF backbone species, genus and class (manual names matched strictly to the backbone as well);
- algorithms: same family (registry/algorithms.json; manual names looked up by the same key, unknown keys
  compared as written);
- datasets: the manual sheet mostly records "Private" or a DOI, so only the paper-level flags "own data" and
  "public dataset" are compared.
Output: review_output/v2/validation/extraction_agreement.json and extraction_agreement_items.csv (unmatched
values per paper for the supplement).
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.registry.normalise import key  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402
from review_v2.taxa import gbif  # noqa: E402
from review_v2.validation.compare_manual import HABITAT_MAP, PLATFORM_MAP, TASK_MAP, load_manual  # noqa: E402
from review_v2.validation.fields import _REG, taxon_class, values  # noqa: E402
from review_v2.validation.stats import bootstrap_prf, wilson  # noqa: E402

V2 = ROOT / "review_output" / "v2"
RUN = V2 / "extraction" / "corpus_v2_opus"
OUT = V2 / "validation"
DROP = {"Other", "Unknown / Other", "Unknown", "Not reported", "Global", "nan", ""}
CLASS_ALIAS = {"Pisces": "Actinopterygii", "Actinopteri": "Actinopterygii"}


def manual_values(row):
    def s(col):
        v = row[col]
        return {str(x) for x in (list(v) if v is not None else []) if str(x) not in DROP}
    taxa = [gbif.match(n) for n in s("Species")]
    taxa = [m for m in taxa if gbif.accepted(m)]
    algos = set()
    for a in s("CV Algorithms"):
        m = _REG["algorithms"].get(key(a), {})
        if not m.get("generic", False):
            algos.add(m.get("family") or key(a))
    ds = [d.lower() for d in s("Dataset")]
    return {
        "platform": s("Imaging Method"), "habitat": s("ParentHabitat"), "spectrum": s("Light Spectra"),
        "country": s("Country"), "task": s("CV Tasks") - {"Shape Estimation"},
        "taxon_species": {m["species"] for m in taxa if m.get("species")},
        "taxon_genus": {m["genus"] for m in taxa if m.get("genus")},
        "taxon_class": {CLASS_ALIAS.get(c, c) for c in s("Class")} | {taxon_class(m) for m in taxa if taxon_class(m)},
        "algorithm": algos,
        "own_data": {"yes"} if any(d == "private" for d in ds) else set(),
        "public_dataset": {"yes"} if any(d not in ("private", "unknown") for d in ds) else set(),
    }


def auto_values(rec, only_verified=True):
    v = values(rec, only_verified)
    v["platform"] = {PLATFORM_MAP.get(x, x) for x in v["platform"]} - DROP
    v["habitat"] = {HABITAT_MAP.get(x, x) for x in v["habitat"]} - DROP
    v["spectrum"] -= DROP
    v["task"] = {TASK_MAP.get(x, x) for x in v["task"]}
    v["country"] = {{"United States": "USA", "United Kingdom": "UK"}.get(c, c) for c in v["country"]}
    ds = rec["record"]["datasets"]
    v["own_data"] = {"yes"} if any(d["role"] == "collected_by_authors" for d in ds) else set()
    v["public_dataset"] = {"yes"} if any(d["role"] in ("public_wildlife_dataset", "generic_benchmark")
                                         for d in ds) else set()
    del v["dataset"]
    return v


def run(only_verified):
    manual = load_manual()
    eligible = set(pd.read_csv(V2 / "corpus" / "papers.csv").query("eligible")["doi"])
    per, rows = {}, []
    for doi in sorted(set(manual.index) & eligible):
        from review_v2.fulltext.prepare import paper_id
        f = RUN / f"{paper_id(doi)}.json"
        if not f.exists():
            continue
        a = auto_values(json.loads(f.read_text(encoding="utf-8")), only_verified)
        m = manual_values(manual.loc[doi])
        m["country"] = {{"United States": "USA", "United Kingdom": "UK"}.get(c, c) for c in m["country"]}
        for field in m:
            per.setdefault(field, []).append((len(a[field] & m[field]), len(a[field] - m[field]),
                                              len(m[field] - a[field])))
            rows.append({"doi": doi, "field": field, "both": sorted(a[field] & m[field]),
                         "auto_only": sorted(a[field] - m[field]), "manual_only": sorted(m[field] - a[field])})
    res = {"papers_manual": len(manual), "papers_compared": len(per["platform"]), "fields": {}}
    for field, r in per.items():
        b = bootstrap_prf(r)
        b["identical"] = wilson(sum(fp == 0 and fn == 0 for _, fp, fn in r), len(r))
        res["fields"][field] = b
    return res, rows


if __name__ == "__main__":
    res, rows = run(True)
    res["all_items"] = run(False)[0]["fields"]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "extraction_agreement.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    pd.DataFrame(rows).to_csv(OUT / "extraction_agreement_items.csv", index=False, encoding="utf-8")
    print(f"manual papers {res['papers_manual']}, compared {res['papers_compared']}")
    for field, b in res["fields"].items():
        print(f"  {field:15s} P {b['precision']['p']:.3f}  R {b['recall']['p']:.3f}  F1 {b['f1']['p']:.3f} "
              f"[{b['f1']['lo']:.3f}-{b['f1']['hi']:.3f}]  identical {b['identical']['p']:.2f}   "
              f"(all items: P {res['all_items'][field]['precision']['p']:.3f} R {res['all_items'][field]['recall']['p']:.3f})")
