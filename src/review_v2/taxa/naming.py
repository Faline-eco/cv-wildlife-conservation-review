"""Taxon naming per paper: does the paper name its taxa scientifically or only by common name?

Usage: python src/review_v2/taxa/naming.py   (after taxa/normalise.py and corpus/tables.py)

Added 2026-10-27 (plan 6.4). The extraction stores per taxon the name as written and a scientific name "only if the
paper gives it", but the coder sometimes filled scientific names itself, and taxa/normalise.py translates common
names (source llm_gbif_exact). This pass checks the text instead, without an LLM:
per taxon value (role target or benchmark class, an animal taxon matched in GBIF; species incl. subspecies, genus,
or a higher rank such as Cervidae, Aves, Holothuroidea), the scientific name (as extracted or as matched in GBIF) is searched in the paper text without the reference list, in full ("Ursus arctos") or
abbreviated ("U. arctos", "An. stephensi"); genera and higher ranks as a word. Case is ignored (papers write "Loxodonta Africana"
or "lutjanus"). A value whose scientific name equals its common name
(Gorilla, Bison, Python) counts as "same".
Paper class: "scientific" (every value's scientific name is in the text), "common" (none), "mixed", or
"not applicable" (no taxon value matched in GBIF, e.g. animal vs background).
Output: review_output/v2/taxa/naming_items.csv (one row per value) and naming_papers.csv (doi, taxon_naming over all
values, taxon_naming_species over species and genus values only, counts).
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.fulltext.prepare import TEXT, paper_id, render  # noqa: E402
from review_v2.search.merge import ROOT  # noqa: E402

V2 = ROOT / "review_output" / "v2"
OUT = V2 / "taxa"
ROLES = {"target", "benchmark_class"}
NO_TAXON = {"non_taxon", "not_animal", "unresolved"}
LEVEL = {"species": "species", "subspecies": "species", "form": "species", "variety": "species", "genus": "genus"}


def clean(text):
    text = re.sub(r"<<page \d+>>", " ", text)
    text = re.sub(r"[-­]\s*", "", text)   # hyphens and soft hyphens, also at line ends ("Plectrogly-Phidodon")
    return re.sub(r"\s+", " ", text)


def names(row):
    out = set()
    for c in ("scientific_name", "sci", "gbif_canonicalName", "gbif_species"):
        v = row.get(c)
        if isinstance(v, str) and v.strip():
            out.add(" ".join(v.split()[:2]) if row["level"] == "species" else v.split()[0])
    return {n for n in out if (len(n.split()) == 2) == (row["level"] == "species")}


def found(name, text):
    if " " in name:
        g, e = name.split()
        # "Goniopora-lobata" (hyphen dropped by clean), "Acanthaster cf. solaris", "Neophocaena phocaenoides asiaeorientalis"
        pat = (rf"\b(?:{re.escape(g)}|{re.escape(g[:1])}[a-z]{{0,2}}\.)[\s_]*(?:(?:cf|aff)\.\s*|[a-z]+\s+)?"
               rf"{re.escape(e)}\b")
        return re.search(pat, text, re.I) is not None
    return re.search(rf"\b{re.escape(name)}\b", text, re.I) is not None


def main():
    papers = pd.read_csv(V2 / "corpus" / "papers.csv")
    eligible = set(papers.loc[papers["eligible"], "doi"])
    sp = pd.read_csv(OUT / "species.csv", low_memory=False)
    sp = sp[sp["doi"].isin(eligible) & sp["role"].isin(ROLES) & ~sp["source"].isin(NO_TAXON)].copy()
    rank = sp["gbif_rank"].str.lower()
    sp["level"] = rank.map(lambda r: LEVEL.get(r, "higher") if isinstance(r, str) else None)
    sp = sp[sp["level"].notna()]
    rows, texts = [], {}
    for r in sp.to_dict("records"):
        d = r["doi"]
        if d not in texts:
            f = TEXT / f"{paper_id(d)}.json"
            texts[d] = clean(render(json.loads(f.read_text(encoding="utf-8")))) if f.exists() else None
        text = texts[d]
        cand = names(r)
        common = str(r["name"]).strip()
        same = any(common.lower() == n.lower() for n in cand)
        sci_in = None if text is None else any(found(n, text) for n in cand)
        rows.append({"doi": d, "item": r["item"], "name": common, "sci": next(iter(sorted(cand)), ""),
                     "level": r["level"], "source": r["source"], "same": same, "sci_in_text": sci_in})
    it = pd.DataFrame(rows).drop_duplicates(["doi", "sci", "level"])
    it.to_csv(OUT / "naming_items.csv", index=False)
    t = it[it["sci_in_text"].notna()]
    out = pd.DataFrame({"doi": sorted(eligible)})
    has_text = out["doi"].map(lambda d: (TEXT / f"{paper_id(d)}.json").exists())
    # taxon_naming: all taxon values; taxon_naming_species: species and genus values only (a paper with the class
    # "birds" and Latin species names is "mixed" in the first and "scientific" in the second)
    for col, sub in (("taxon_naming", t), ("taxon_naming_species", t[t["level"] != "higher"])):
        g = sub.groupby("doi")["sci_in_text"].agg(["sum", "count"])
        cls = pd.Series("mixed", index=g.index)
        cls[g["sum"] == g["count"]] = "scientific"
        cls[g["sum"] == 0] = "common"
        out[col] = out["doi"].map(cls).fillna("not applicable").where(has_text, "no text")
        if col == "taxon_naming":
            out["values"] = out["doi"].map(g["count"]).fillna(0).astype(int)
            out["sci_in_text"] = out["doi"].map(g["sum"]).fillna(0).astype(int)
    out.to_csv(OUT / "naming_papers.csv", index=False)
    print(len(out), "eligible papers")
    print(pd.crosstab(out["taxon_naming"], out["taxon_naming_species"], margins=True).to_string())
    print("\nvalues:", len(t), "scientific name in text:", int(t["sci_in_text"].sum()))
    print(pd.crosstab(t["source"], t["sci_in_text"], margins=True).to_string())


if __name__ == "__main__":
    main()
