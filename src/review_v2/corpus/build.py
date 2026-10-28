"""Corpus table: one row per coded paper, with eligibility under both scopes and the wild/captive tag.

Usage: python src/review_v2/corpus/build.py

Scope (decision 2026-10-22): eligible = the extractor's `include` (wild, free-ranging animals) OR excluded only
as E-CAPTIVE with animals that are alive (zoo, aquarium, enclosure). Dead specimens (museum collections, market
fish, otoliths), laboratory and farm animals stay excluded. `eligible_strict` keeps the original scope.
Also excluded (decision 2026-10-27): papers the extractor included although it coded the subject as specimen or
livestock/pet, and papers without a publication year in 2014-2026 (criteria E-CAPTIVE, E-AGRI, E-YEAR).
The excluded papers that keep the protocol code E-CAPTIVE are then dead specimens only; they are written as
E-MUSEUM (the code used in the paper).

captivity: wild / captive / wild_and_captive / not_reported. From subject_type where it is unambiguous
(wild_free_ranging -> wild, captive_or_zoo -> captive); otherwise from the supplementary pass
extraction/captivity.py ("pending" if that pass has not yet run for the paper; the DOIs are written to
fetch/captivity_pending_dois.txt).

Output: review_output/v2/corpus/papers.csv
"""
import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.extraction.captivity import OUTDIR as CAPTIVITY  # noqa: E402
from review_v2.fulltext.prepare import paper_id  # noqa: E402
from review_v2.search.fetch import get, load_env  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

V2 = ROOT / "review_output" / "v2"
OUT = V2 / "corpus"
RUN = V2 / "extraction" / "corpus_v2_opus"
OLD = [ROOT / "review_output" / "gapminder" / f"2026130_{k}.parquet" for k in ("manual", "auto")]
META = OUT / "openalex_meta.json"
SUBJECT_TAG = {"wild_free_ranging": "wild", "captive_or_zoo": "captive"}


def records():
    rows = []
    for f in sorted(RUN.glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        if "record" not in r:
            continue
        e = r["record"]["eligibility"]
        rows.append({"doi": norm_doi(r["doi"]), "include": e["include"], "criterion": e["criterion"],
                     "subject_type": e["subject_type"], "paper_type": e["paper_type"], "reason": e["reason"],
                     "cost_usd": r["provenance"].get("cost_usd")})
    return pd.DataFrame(rows)


def openalex_meta(dois):
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    todo = [d for d in dois if d not in meta and "," not in d and "|" not in d]
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        r = get("https://api.openalex.org/works", params={
            "filter": "doi:" + "|".join("https://doi.org/" + d for d in chunk), "per-page": 100,
            "select": "doi,title,publication_year,primary_location", "api_key": os.environ["OPENALEX_API_KEY"]})
        for w in r.json().get("results", []) if r.status_code == 200 else []:
            src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
            meta[norm_doi(w["doi"])] = {"title": w.get("title"), "year": w.get("publication_year"), "venue": src}
        for d in chunk:
            meta.setdefault(d, {})
    # not found in OpenAlex (mostly preprints): Crossref, one DOI at a time
    for d in [d for d in dois if not meta.get(d, {}).get("title")]:
        r = get(f"https://api.crossref.org/works/{d}", headers={"User-Agent": "LiteratureReviewCVinWC/2.0"})
        if r.status_code != 200:
            continue
        m = r.json()["message"]
        parts = (m.get("posted") or m.get("published") or m.get("issued") or {}).get("date-parts") or [[None]]
        meta[d] = {"title": (m.get("title") or [None])[0], "year": parts[0][0],
                   "venue": (m.get("container-title") or [m.get("institution", [{}])[0].get("name")
                                                          if m.get("institution") else None])[0]}
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=0), encoding="utf-8")
    return meta


if __name__ == "__main__":
    load_env()
    OUT.mkdir(parents=True, exist_ok=True)
    df = records()
    ta = pd.read_csv(V2 / "screening" / "ta_final.csv", low_memory=False).dropna(subset=["doi"])
    ta["doi"] = ta["doi"].map(norm_doi)
    ta = ta.drop_duplicates("doi").set_index("doi")
    old = set().union(*(set(pd.read_parquet(p)["doi"].dropna().map(norm_doi)) for p in OLD))

    df["screening"] = df["doi"].map(ta["final"]).fillna("not screened")
    df["screening_run"] = df["doi"].map(ta["run"])
    df["in_old_corpus"] = df["doi"].isin(old)
    for c in ("title", "year", "venue"):
        df[c] = df["doi"].map(ta[c])
    meta = openalex_meta(df.loc[df["title"].isna() | df["year"].isna(), "doi"].tolist())
    for c in ("title", "year", "venue"):
        df[c] = df[c].fillna(df["doi"].map(lambda d: meta.get(d, {}).get(c)))
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")

    # dead specimens and livestock/pets are out of scope even when the extractor set include; so are papers
    # without a publication year in 2014-2026 (one online-first 2013 paper, four without any year)
    in_scope = (~df["subject_type"].isin(["specimen", "livestock_or_pet"])) & df["year"].between(2014, 2026).fillna(False).astype(bool)
    # give the papers that the extractor included but the scope rules drop the matching exclusion criterion
    dropped = df["include"] & ~in_scope
    df["scope_dropped"] = dropped
    df.loc[dropped & (df["subject_type"] == "specimen"), "criterion"] = "E-CAPTIVE"
    df.loc[dropped & (df["subject_type"] == "livestock_or_pet"), "criterion"] = "E-AGRI"
    df.loc[dropped & ~df["year"].between(2014, 2026).fillna(False).astype(bool), "criterion"] = "E-YEAR"
    df["eligible_strict"] = df["include"] & in_scope
    df["eligible"] = (df["include"] | (df["criterion"] == "E-CAPTIVE")) & in_scope
    # in the widened scope the protocol code E-CAPTIVE only excludes dead specimens: reported as E-MUSEUM
    df.loc[~df["eligible"] & (df["criterion"] == "E-CAPTIVE"), "criterion"] = "E-MUSEUM"

    def tag(row):
        if row.subject_type in SUBJECT_TAG:
            return SUBJECT_TAG[row.subject_type], "extraction"
        f = CAPTIVITY / f"{paper_id(row.doi)}.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))["captivity"], "captivity_pass"
        return "pending", None
    df[["captivity", "captivity_source"]] = df.apply(tag, axis=1, result_type="expand")
    pending = df[df["eligible"] & (df["captivity"] == "pending")]["doi"]
    (V2 / "fetch" / "captivity_pending_dois.txt").write_text("\n".join(pending) + "\n", encoding="utf-8")

    cols = ["doi", "title", "year", "venue", "screening", "screening_run", "in_old_corpus", "eligible",
            "eligible_strict", "scope_dropped", "captivity", "captivity_source", "criterion", "subject_type", "paper_type", "reason",
            "cost_usd"]
    df[cols].sort_values(["year", "doi"]).to_csv(OUT / "papers.csv", index=False, encoding="utf-8")

    el = df[df["eligible"]]
    print(f"coded {len(df)}, eligible {len(el)} (strict {int(df['eligible_strict'].sum())}), "
          f"captivity pending for {len(pending)}; extraction cost ${df['cost_usd'].sum():.0f}")
    print(pd.crosstab(el["captivity"], el["year"].fillna(0) >= 2024, margins=True).to_string())
    print(pd.crosstab(el["screening"], el["in_old_corpus"], margins=True).to_string())
    print("missing title:", int(df["title"].isna().sum()), " missing year:", int(df["year"].isna().sum()))
