"""Final title/abstract status of every screened record and the DOI lists for the Zotero import.

Usage: python src/review_v2/screening/finalize.py

Combines the two-screener decisions of all runs with the adjudication of the unsure records and with
the re-adjudication of three groups of agreed exclusions that the calibration showed to be lossy
(coral / benthic fauna, wild animals near farms, fishery catch). Records excluded only as captive / zoo animals
go to full text (scope widened 2026-10-22).
  include  -> full text, first priority       exclude -> out
  fulltext -> full text, second priority (title and abstract do not settle eligibility)
Writes screening/ta_final.csv and fetch/FINAL_*.txt (papers with a PDF in Zotero are left out of the lists).
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.screening.screen import OUT, ROOT  # noqa: E402
from review_v2.search.merge import norm_doi  # noqa: E402

RUNS = ["index_2014_2026", "libraries_2024_2026", "citations_hop1", "citations_hop2"]
FETCH = ROOT / "review_output" / "v2" / "fetch"
RANK = {"include": 0, "fulltext": 1, "exclude": 2}


def adjudicated(name):
    d = pd.read_csv(OUT / name / "adjudicated.csv", low_memory=False)
    # Fishery catch (fish on deck or landed) is coded as wild at full text, so it is not excluded here.
    catch = (d["decision_adj"] == "exclude") & (d["criterion_adj"] == "E-AGRI") & \
            (d["subject_adj"] == "specimen_or_catch")
    d.loc[catch, "decision_adj"] = "fulltext"
    return d.set_index("id")[["decision_adj", "criterion_adj", "subject_adj", "reason_adj"]]


if __name__ == "__main__":
    adj = pd.concat([adjudicated(n) for n in ("adjudication", "adjudication_hop2")
                     if (OUT / n / "adjudicated.csv").exists()])
    rescue = pd.concat([adjudicated(n) for n in ("adjudication_rescue", "adjudication_rescue_hop2")
                        if (OUT / n / "adjudicated.csv").exists()])
    adj, rescue = adj[~adj.index.duplicated()], rescue[~rescue.index.duplicated()]
    parts = []
    for run in [r for r in RUNS if (OUT / r / "ta_decisions.csv").exists()]:
        d = pd.read_csv(OUT / run / "ta_decisions.csv", low_memory=False)
        d["run"] = run
        parts.append(d[["id", "doi", "title", "year", "venue", "run", "decision_a", "criterion_a", "decision_b",
                        "criterion_b", "ta_decision"]])
    df = pd.concat(parts, ignore_index=True).drop_duplicates("id").reset_index(drop=True).join(adj, on="id")
    df["stage"] = "screeners"
    df["final"] = df["ta_decision"]
    unsure = df["ta_decision"] == "unsure"
    df.loc[unsure, "final"] = df.loc[unsure, "decision_adj"].fillna("fulltext")
    df.loc[unsure, "stage"] = "adjudicator"
    hit = df["id"].isin(rescue.index) & (df["ta_decision"] == "exclude")
    for c in rescue.columns:
        df.loc[hit, c] = df.loc[hit, "id"].map(rescue[c])
    back = hit & (df["decision_adj"] != "exclude")
    df.loc[back, "final"] = df.loc[back, "decision_adj"]
    df.loc[hit, "stage"] = "re-adjudicated exclusion"
    df["final_criterion"] = "none"
    ex = df["final"] == "exclude"
    df.loc[ex, "final_criterion"] = df.loc[ex, "criterion_adj"].where(df.loc[ex, "stage"] != "screeners",
                                                                    df.loc[ex, "criterion_a"])
    # widened scope (2026-10-22): live captive / zoo animals are no longer an exclusion; such records go to full
    # text, where the extraction decides (dead specimens stay out there)
    cap = (df["final"] == "exclude") & (df["final_criterion"] == "E-CAPTIVE")
    df.loc[cap, "final"] = "fulltext"
    df.loc[cap, "stage"] = "widened scope (captive)"
    df["doi"] = df["doi"].map(lambda d: norm_doi(d) if isinstance(d, str) else None)
    df = df.sort_values("final", key=lambda s: s.map(RANK))
    df = pd.concat([df[df["doi"].isna()], df[df["doi"].notna()].drop_duplicates("doi")], ignore_index=True)
    ex = df["final"] == "exclude"
    df.to_csv(OUT / "ta_final.csv", index=False, encoding="utf-8")
    print(pd.crosstab(df["run"], df["final"], margins=True).to_string())
    print(pd.crosstab(df["stage"], df["final"]).to_string())

    have = set(pd.read_csv(ROOT / "review_output" / "v2" / "fulltext" / "zotero_pdfs.csv")["doi"].map(norm_doi))
    manual = {norm_doi(x) for x in (FETCH / "batch0_manual_included_missing_dois.txt").read_text().split()}
    lists = {
        "FINAL_1_include": set(df.loc[(df["final"] == "include") & df["doi"].notna(), "doi"]) | manual,
        "FINAL_2_fulltext": set(df.loc[(df["final"] == "fulltext") & df["doi"].notna(), "doi"]),
        # not for download by default: unsure records the adjudicator excluded for lack of any sign of image
        # analysis; kept as a list so that a sample can be checked in full text
        "FINAL_3_excluded_no_cv_optional": set(df.loc[ex & (df["stage"] == "adjudicator") &
                                                      (df["final_criterion"] == "E-NOCV") & df["doi"].notna(),
                                                      "doi"]),
    }
    for name, dois in lists.items():
        todo = sorted(dois - have)
        (FETCH / f"{name}_dois.txt").write_text("\n".join(todo) + "\n", encoding="utf-8")
        print(f"{name}: {len(dois)} DOIs, {len(dois & have)} already in Zotero, {len(todo)} to fetch")
    no_doi = df[df["doi"].isna() & (df["final"] != "exclude")]
    no_doi[["title", "year", "venue", "run", "final"]].to_csv(FETCH / "FINAL_no_doi.csv", index=False,
                                                             encoding="utf-8")
    print("without DOI (include or fulltext):", len(no_doi))
