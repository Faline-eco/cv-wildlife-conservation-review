"""Validation 5.1: accuracy of the title/abstract screening.

Usage: python src/review_v2/validation/screening_accuracy.py

A. Calibration set: 1,693 old-corpus papers with a full-text verdict of the frozen extractor (papers.csv,
   strict and widened scope). T/A decision = two screeners, unsure records adjudicated, fishery-catch rule of
   finalize.py. Positive = passed on to full text (include or fulltext). The re-adjudication of three groups of
   agreed exclusions (finalize.py) was not run on this set, so sensitivity is a lower bound.
B. The 760 manually decided records of the original review: screener A and the two-screener decision vs the
   manual decision. The manual coding included laboratory, livestock and aquaculture papers that the stated
   scope excludes, so B is also given for the manual includes that the full-text extractor finds eligible.
C. Yield of the full-text stage per T/A status in the new corpus (share of coded papers that are eligible).
D. Agreement between screener A and B (kappa) over all screened records.
Output: review_output/v2/validation/screening_accuracy.json
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402
from review_v2.validation.stats import binary, kappa, wilson  # noqa: E402

V2 = ROOT / "review_output" / "v2"
SCR = V2 / "screening"
OUT = V2 / "validation"


def calibration(papers):
    c = pd.read_csv(SCR / "calibration" / "ta_decisions.csv", low_memory=False)
    a = pd.read_csv(SCR / "calibration_adj" / "adjudicated.csv", low_memory=False).set_index("id")
    catch = (a["decision_adj"] == "exclude") & (a["criterion_adj"] == "E-AGRI") & \
            (a["subject_adj"] == "specimen_or_catch")
    a.loc[catch, "decision_adj"] = "fulltext"
    c["final"] = c["ta_decision"]
    u = c["ta_decision"] == "unsure"
    c.loc[u, "final"] = c.loc[u, "id"].map(a["decision_adj"]).fillna("fulltext")
    c["doi"] = c["doi"].map(norm_doi)
    c = c.join(papers[["eligible", "eligible_strict"]], on="doi", how="inner")
    passed = c["final"] != "exclude"
    res = {"n": len(c), "final_counts": c["final"].value_counts().to_dict()}
    for scope in ("eligible_strict", "eligible"):
        res[scope] = binary(passed, c[scope])
        res[scope]["screeners_only"] = binary(c["ta_decision"] != "exclude", c[scope])
        res[scope]["yield_by_decision"] = {k: wilson(int(g[scope].sum()), len(g)) for k, g in c.groupby("final")}
    return res


def manual(papers):
    v = pd.read_csv(SCR / "pilot_manual" / "vs_manual.csv")
    v["doi"] = v["id"].map(norm_doi)
    gold = v["manual"] == "include"
    res = {"n": len(v), "manual_include": int(gold.sum())}
    for name, pred in (("screener_a", v["decision_a"] != "exclude"),
                       ("two_screeners", (v["decision_a"] != "exclude") | (v["decision_b"] != "exclude"))):
        res[name] = binary(pred, gold)
    v = v.join(papers[["eligible"]], on="doi")
    inc = v[gold & v["eligible"].fillna(False).astype(bool)]
    res["manual_include_eligible_v2"] = {
        "n": len(inc),
        "screener_a_passed": wilson(int((inc["decision_a"] != "exclude").sum()), len(inc)),
        "two_screeners_passed": wilson(int(((inc["decision_a"] != "exclude") |
                                            (inc["decision_b"] != "exclude")).sum()), len(inc))}
    return res


def fulltext_yield(papers):
    res = {}
    for k, g in papers.groupby("screening"):
        res[k] = {"strict": wilson(int(g["eligible_strict"].sum()), len(g)),
                  "widened": wilson(int(g["eligible"].sum()), len(g))}
    return res


def screener_agreement():
    t = pd.read_csv(SCR / "ta_final.csv", low_memory=False)
    t = t.dropna(subset=["decision_a", "decision_b"])
    return {"n": len(t), "kappa": kappa(t["decision_a"], t["decision_b"]),
            "agree": wilson(int((t["decision_a"] == t["decision_b"]).sum()), len(t))}


def fmt(w):
    return f"{w['k']}/{w['n']} = {100 * w['p']:.1f}% [{100 * w['lo']:.1f}-{100 * w['hi']:.1f}]"


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    papers = pd.read_csv(V2 / "corpus" / "papers.csv").drop_duplicates("doi").set_index("doi")
    res = {"calibration": calibration(papers), "manual": manual(papers), "fulltext_yield": fulltext_yield(papers),
           "screener_agreement": screener_agreement()}
    (OUT / "screening_accuracy.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    c = res["calibration"]
    print("A. calibration set", c["n"], c["final_counts"])
    for s in ("eligible_strict", "eligible"):
        print(f"  {s}: sensitivity {fmt(c[s]['sensitivity'])}, specificity {fmt(c[s]['specificity'])}, "
              f"precision {fmt(c[s]['precision'])}, F1 {c[s]['f1']:.3f}, kappa {c[s]['kappa']:.3f}")
        print("    screeners only: sensitivity", fmt(c[s]["screeners_only"]["sensitivity"]))
        for k, w in c[s]["yield_by_decision"].items():
            print(f"    eligible among {k}: {fmt(w)}")
    m = res["manual"]
    print("B. manual decisions", m["n"])
    for k in ("screener_a", "two_screeners"):
        print(f"  {k}: sensitivity {fmt(m[k]['sensitivity'])}, specificity {fmt(m[k]['specificity'])}, "
              f"kappa {m[k]['kappa']:.3f}")
    e = m["manual_include_eligible_v2"]
    print(f"  manual includes eligible in v2 ({e['n']}): screener A passes {fmt(e['screener_a_passed'])}, "
          f"two screeners {fmt(e['two_screeners_passed'])}")
    print("C. full-text yield")
    for k, w in res["fulltext_yield"].items():
        print(f"  {k}: strict {fmt(w['strict'])}, widened {fmt(w['widened'])}")
    a = res["screener_agreement"]
    print(f"D. screener A vs B: kappa {a['kappa']:.3f}, agreement {fmt(a['agree'])}")
