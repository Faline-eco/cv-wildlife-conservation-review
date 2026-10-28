"""Combine the two screeners of a run and write the DOI lists for the Zotero import.

Usage: python src/review_v2/screening/combine.py <records.csv> <run_name> <batch_name>

Rule: both include -> include, both exclude -> exclude, anything else (disagreement, unsure, a
missing decision) -> unsure. Include and unsure go to full text.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.screening.screen import OUT, ROOT, load_records  # noqa: E402

if __name__ == "__main__":
    records, run, batch = sys.argv[1:4]
    df = load_records(records)
    for s in "ab":
        d = pd.read_csv(OUT / run / f"decisions_{s}.csv").drop_duplicates("id")
        df = df.merge(d.rename(columns={c: f"{c}_{s}" for c in ["decision", "criterion", "reason"]}),
                      on="id", how="left")
    same = df["decision_a"] == df["decision_b"]
    df["ta_decision"] = df["decision_a"].where(same & df["decision_a"].isin(["include", "exclude"]), "unsure")
    df.to_csv(OUT / run / "ta_decisions.csv", index=False, encoding="utf-8")
    print(df["ta_decision"].value_counts().to_string())
    print("agreement:", int(same.sum()), "of", len(df))

    fetch = ROOT / "review_output" / "v2" / "fetch"
    todo = df[df["ta_decision"] != "exclude"]
    cols = ["doi", "title", "year", "venue", "sources", "ta_decision", "reason_a"]
    todo[todo["doi"].notna()][cols].to_csv(fetch / f"{batch}_to_fetch.csv", index=False, encoding="utf-8")
    todo[todo["doi"].isna()][cols].to_csv(fetch / f"{batch}_no_doi.csv", index=False, encoding="utf-8")
    for dec in ["include", "unsure"]:
        dois = sorted(todo.loc[(todo["ta_decision"] == dec) & todo["doi"].notna(), "doi"])
        (fetch / f"{batch}_{dec}_dois.txt").write_text("\n".join(dois) + "\n", encoding="utf-8")
        print(f"{batch} {dec}: {len(dois)} DOIs")
    print("without DOI:", int(todo["doi"].isna().sum()))
    print(pd.crosstab(todo["sources"], todo["ta_decision"]).to_string())
