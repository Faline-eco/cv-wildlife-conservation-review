"""Validation 5.5: run-to-run stability of the extraction.

Usage: python src/review_v2/validation/stability.py [rerun_name]   (default stability_rerun)

The 100 papers of fetch/stability_dois.txt were extracted a second time with the same frozen protocol, model and
text (extraction/stability_rerun). Per field: micro F1 between the two runs (run 1 as reference, so F1 equals the
Dice overlap of the value sets) with paper-level bootstrap intervals, and the share of papers with identical sets.
Eligibility: share of papers with the same include decision.
Output: review_output/v2/validation/stability.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.merge import ROOT  # noqa: E402
from review_v2.validation.fields import values  # noqa: E402
from review_v2.validation.stats import bootstrap_prf, wilson  # noqa: E402

EXT = ROOT / "review_output" / "v2" / "extraction"
OUT = ROOT / "review_output" / "v2" / "validation"


def compare(rerun="stability_rerun"):
    per, same_incl, n = {}, 0, 0
    for f in sorted((EXT / rerun).glob("*.json")):
        b = json.loads(f.read_text(encoding="utf-8"))
        a = json.loads((EXT / "corpus_v2_opus" / f.name).read_text(encoding="utf-8"))
        if "record" not in a or "record" not in b:
            continue
        n += 1
        same_incl += a["record"]["eligibility"]["include"] == b["record"]["eligibility"]["include"]
        if not a["record"]["eligibility"]["include"]:
            continue
        va, vb = values(a), values(b)
        for field in va:
            per.setdefault(field, []).append((len(va[field] & vb[field]), len(vb[field] - va[field]),
                                              len(va[field] - vb[field])))
    res = {"papers": n, "same_include": wilson(same_incl, n), "fields": {}}
    for field, rows in per.items():
        r = bootstrap_prf(rows)
        r["identical"] = wilson(sum(fp == 0 and fn == 0 for _, fp, fn in rows), len(rows))
        res["fields"][field] = r
    return res


if __name__ == "__main__":
    res = compare(*sys.argv[1:])
    (OUT / "stability.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    s = res["same_include"]
    print(f"papers {res['papers']}, same include decision {s['k']}/{s['n']}")
    for field, r in res["fields"].items():
        print(f"  {field:14s} F1 {r['f1']['p']:.3f} [{r['f1']['lo']:.3f}-{r['f1']['hi']:.3f}]  identical "
              f"{r['identical']['k']}/{r['identical']['n']}")
