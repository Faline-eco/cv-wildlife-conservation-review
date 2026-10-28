"""Merge the per-source JSONL files into one deduplicated candidate table and report how much of
the existing corpus the index search recovers.

Output: review_output/v2/search/records.csv (one row per unique work).
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "review_output" / "v2" / "search"
SOURCES = ["scopus", "pubmed", "openalex"]  # priority order for metadata


def norm_doi(x):
    if not isinstance(x, str) or not x.strip():
        return None
    x = x.strip().lower()
    x = re.sub(r"^https?://(dx\.)?doi\.org/", "", x)
    return x if x.startswith("10.") else None


def norm_title(x):
    if not isinstance(x, str):
        return None
    x = unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower()
    x = re.sub(r"<[^>]+>", " ", x)
    x = re.sub(r"[^a-z0-9]+", " ", x).strip()
    return x or None


def load():
    rows = []
    for s in SOURCES:
        p = OUT / f"{s}.jsonl"
        if p.exists():
            rows += [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]
    df = pd.DataFrame(rows)
    df["doi"] = df["doi"].map(norm_doi)
    df["title_key"] = df["title"].map(norm_title)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    return df


def merge(df):
    # key: DOI where present, otherwise normalised title; records without DOI join a DOI record
    # that has the same normalised title
    title_to_doi = (df.dropna(subset=["doi", "title_key"]).drop_duplicates("title_key")
                    .set_index("title_key")["doi"])
    df["key"] = df["doi"].fillna(df["title_key"].map(title_to_doi))
    df["key"] = df["key"].fillna("title:" + df["title_key"].fillna(""))
    df["prio"] = df["source"].map({s: i for i, s in enumerate(SOURCES)})
    df = df.sort_values(["key", "prio"])

    def first(s):
        s = s.dropna()
        s = s[s.astype(str).str.strip() != ""]
        return s.iloc[0] if len(s) else None

    g = df.groupby("key", sort=False)
    out = g.agg(doi=("doi", first), title=("title", first), abstract=("abstract", first),
                year=("year", first), venue=("venue", first), doc_type=("doc_type", first),
                keywords=("keywords", first), sources=("source", lambda s: "|".join(sorted(set(s)))))
    return out.reset_index(drop=True)


def existing_sets():
    man = pd.read_excel(ROOT / "review_input" / "review_raw.xlsx")
    man = man[man["DOI"].notna()].copy()
    man["doi"] = man["DOI"].map(norm_doi)
    sets = {
        "manual_included": set(man.loc[man["IsAggriculture"] == 0, "doi"].dropna()),
        "manual_excluded": set(man.loc[man["IsAggriculture"] == 1, "doi"].dropna()),
    }
    cand = pd.read_csv(ROOT / "review_output" / "review_filtered_output_new.csv", sep=";")
    sets["citation_candidates"] = set(cand["doi"].map(norm_doi).dropna())
    return sets, man


if __name__ == "__main__":
    raw = load()
    rec = merge(raw)
    sets, man = existing_sets()
    for name, s in sets.items():
        rec[f"in_{name}"] = rec["doi"].isin(s)
    rec.to_csv(OUT / "records.csv", index=False, encoding="utf-8")

    print(f"raw records {len(raw)}, unique works {len(rec)}")
    print("with DOI:", rec['doi'].notna().sum(), " with abstract:", rec['abstract'].notna().sum())
    print("\nby year and source combination:")
    print(pd.crosstab(rec["year"], rec["sources"]).to_string())
    print("\nrecovery of existing sets by the index search:")
    for name, s in sets.items():
        print(f"  {name}: {rec['doi'].isin(s).sum()} of {len(s)}")
    inc = man[(man["IsAggriculture"] == 0) & man["doi"].notna()].copy()
    inc["found"] = inc["doi"].isin(set(rec["doi"].dropna()))
    print("\nmanual included, found by index search, per original database:")
    print(inc.groupby("Database")["found"].agg(["sum", "count"]).to_string())
    new = rec[~rec[[f"in_{n}" for n in sets]].any(axis=1)]
    print(f"\nnot seen before: {len(new)}")
    print(new["year"].value_counts().sort_index().to_string())
