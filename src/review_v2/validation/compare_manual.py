"""Agreement of an extraction run with the existing manual coding, on the fields the manual coding has.

Usage: python src/review_v2/validation/compare_manual.py <run_name> [<run_name> ...]

Per field: micro precision / recall / F1 over (paper, value) pairs and the share of papers with identical
value sets. Manual values come from the cleaned manual corpus (gapminder/2026130_manual.parquet).
Only verified items of included papers are counted (evidence found, not in introduction or related work).
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.extraction.verify import verified  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

EXTRACTION = ROOT / "review_output" / "v2" / "extraction"

# v2 vocabulary -> vocabulary of the manual coding
TASK_MAP = {"Re-Identification": "Identification", "Counting": "Detection"}
PLATFORM_MAP = {"Web / citizen-science images": "Non-specialized Camera",
                "Stationary underwater camera": "Non-specialized Camera",
                "Not reported": "Non-specialized Camera"}  # the manual coding has no "not reported"
HABITAT_MAP = {"Not reported": "Unknown / Other", "Other": "Unknown / Other"}
COUNTRY_MAP = {"United States": "USA", "United States of America": "USA", "United Kingdom": "UK",
               "Czechia": "Czech Republic"}


def ok(item, strict):
    return verified(item["evidence"]) if strict else True


def auto_values(rec, strict=True):
    r = rec["record"]
    s = [x for x in r["settings"] if ok(x, strict)]
    return {
        "Imaging Method": {PLATFORM_MAP.get(x["platform"], x["platform"]) for x in s},
        "Light Spectra": {sp["value"] for x in r["settings"] for sp in x["spectra"] if ok(sp, strict)},
        "ParentHabitat": {HABITAT_MAP.get(x["habitat"], x["habitat"]) for x in s},
        "Country": {COUNTRY_MAP.get(c, c) for x in s for c in x["countries"] if c != "Global / web"},
        "CV Tasks": {TASK_MAP.get(t["task"], t["task"]) for t in r["tasks"]
                     if ok(t, strict) and t["role"] == "primary"},
    }


def load_manual():
    m = pd.read_parquet(ROOT / "review_output" / "gapminder" / "2026130_manual.parquet")
    m["doi"] = m["doi"].map(norm_doi)
    return m.drop_duplicates("doi").set_index("doi")


def compare(run, strict=True):
    manual = load_manual()
    rows, elig = [], []
    for f in sorted((EXTRACTION / run).glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        doi = rec["doi"]
        e = rec["record"]["eligibility"]
        elig.append({"doi": doi, "manual_included": doi in manual.index, "auto_include": e["include"],
                     "criterion": e["criterion"], "subject_type": e["subject_type"]})
        if doi not in manual.index:
            continue
        auto = auto_values(rec, strict)
        for field, a in auto.items():
            g = {str(v) for v in manual.at[doi, field] if v is not None and str(v) not in ("", "nan")}
            if field in ("ParentHabitat", "Country"):
                g -= {"Unknown / Other", "Unknown", "Global"}
                a = a - {"Unknown / Other"}
            rows.append({"doi": doi, "field": field, "tp": len(a & g), "fp": len(a - g), "fn": len(g - a),
                         "identical": a == g, "auto": sorted(a), "manual": sorted(g)})
    d = pd.DataFrame(rows)
    agg = d.groupby("field").agg(papers=("doi", "count"), tp=("tp", "sum"), fp=("fp", "sum"),
                                 fn=("fn", "sum"), identical=("identical", "mean"))
    agg["precision"] = agg["tp"] / (agg["tp"] + agg["fp"])
    agg["recall"] = agg["tp"] / (agg["tp"] + agg["fn"])
    agg["f1"] = 2 * agg["precision"] * agg["recall"] / (agg["precision"] + agg["recall"])
    return agg.round(3), d, pd.DataFrame(elig)


def evidence_stats(run):
    from review_v2.extraction.verify import _walk
    c, tokens, secs, cost = {}, 0, 0, 0
    n = 0
    for f in (EXTRACTION / run).glob("*.json"):
        rec = json.loads(f.read_text(encoding="utf-8"))
        n += 1
        u = rec["provenance"]["usage"] or {}
        tokens += u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("output_tokens", 0)
        secs += (rec["provenance"].get("duration_ms") or 0) / 1000
        cost += rec["provenance"].get("cost_usd") or 0
        for item in _walk(rec["record"]):
            ev = item["evidence"]
            if ev["status"] == "none":
                continue
            key = "rejected_section" if ev["status"] != "not_found" and not verified(ev) else ev["status"]
            c[key] = c.get(key, 0) + 1
    return c, n, tokens / max(n, 1), secs / max(n, 1), cost


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    for run in sys.argv[1:]:
        agg, d, elig = compare(run)
        ev, n, tok, sec, cost = evidence_stats(run)
        print(f"\n===== {run}: {n} papers, {tok:,.0f} tokens and {sec:.0f} s per paper, API-equivalent ${cost:.2f}")
        print("evidence:", ev)
        print("eligibility vs manual:")
        print(pd.crosstab(elig["manual_included"], elig["auto_include"]).to_string())
        print(elig.loc[elig["manual_included"] != elig["auto_include"], ["doi", "criterion", "subject_type"]].to_string())
        print(agg.to_string())
        d.to_csv(EXTRACTION / run / "_vs_manual.csv", index=False, encoding="utf-8")
