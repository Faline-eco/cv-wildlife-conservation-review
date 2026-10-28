"""Turn the library export files (review_input/exports/<library>/) into the common record format and
keep the records the index search has not delivered yet.

Output: review_output/v2/search/<library>.jsonl      (all exported records)
        review_output/v2/search/library_records.csv  (unique, not in records.csv, not manually coded)
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.merge import OUT, ROOT, existing_sets, norm_doi, norm_title  # noqa: E402

EXPORTS = ROOT / "review_input" / "exports"
COLS = ["source", "source_id", "doi", "title", "abstract", "year", "venue", "doc_type", "keywords"]


def ieee():
    frames = [pd.read_csv(p) for p in sorted((EXPORTS / "ieee").glob("*.csv"))]
    if not frames:
        return pd.DataFrame(columns=COLS)
    d = pd.concat(frames, ignore_index=True)
    return pd.DataFrame({
        "source": "ieee", "source_id": d["PDF Link"], "doi": d["DOI"], "title": d["Document Title"],
        "abstract": d["Abstract"], "year": d["Publication Year"], "venue": d["Publication Title"],
        "doc_type": d["Document Identifier"], "keywords": d["Author Keywords"],
    })


def jsonl(name):
    """Libraries where only the hit list (DOI, title) was saved to <library>/*.tsv: the metadata comes
    from fetch_by_doi.py (<library>_meta.jsonl)."""
    def read():
        p = OUT / f"{name}_meta.jsonl"
        if not p.exists():
            return pd.DataFrame(columns=COLS)
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        d = pd.DataFrame(rows).reindex(columns=COLS)
        d["source"] = name
        return d
    return read


LIBRARIES = {"ieee": ieee, "acm": jsonl("acm"), "sciencedirect": jsonl("sciencedirect"),
             "springer": jsonl("springer"), "wiley": jsonl("wiley"), "iet": jsonl("iet"),
             "nature": jsonl("nature")}

if __name__ == "__main__":
    frames = []
    for name, reader in LIBRARIES.items():
        d = reader()
        if not len(d):
            continue
        d.to_json(OUT / f"{name}.jsonl", orient="records", lines=True, force_ascii=False)
        frames.append(d)
        print(f"{name}: {len(d)} exported")
    df = pd.concat(frames, ignore_index=True)
    df["doi"] = df["doi"].map(norm_doi)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["title_key"] = df["title"].map(norm_title)
    df["key"] = df["doi"].fillna("title:" + df["title_key"].fillna(""))

    def first(s):
        s = s.dropna()
        return s.iloc[0] if len(s) else None

    rec = df.groupby("key", sort=False).agg(
        doi=("doi", first), title=("title", first), abstract=("abstract", first), year=("year", first),
        venue=("venue", first), doc_type=("doc_type", first), keywords=("keywords", first),
        sources=("source", lambda s: "|".join(sorted(set(s)))), title_key=("title_key", first),
    ).reset_index(drop=True)

    index = pd.read_csv(OUT / "records.csv")
    sets, man = existing_sets()
    known_doi = set(index["doi"].dropna()) | sets["manual_included"] | sets["manual_excluded"]
    known_title = set(index["title"].map(norm_title).dropna()) | set(man["Paper"].map(norm_title).dropna())
    rec["in_index"] = rec["doi"].isin(known_doi) | rec["title_key"].isin(known_title)
    rec["in_citation_candidates"] = rec["doi"].isin(sets["citation_candidates"])
    print(f"unique {len(rec)}, already known {rec['in_index'].sum()}")
    print(pd.crosstab(rec["sources"], rec["in_index"]).to_string())
    new = rec[~rec["in_index"]].drop(columns=["title_key", "in_index"])
    new.to_csv(OUT / "library_records.csv", index=False, encoding="utf-8")
    print(f"new records to screen: {len(new)}")
    print(new["year"].value_counts().sort_index().to_string())
