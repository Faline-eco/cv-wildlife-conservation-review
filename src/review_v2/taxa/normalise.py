"""Species items -> GBIF backbone taxa.

Usage: python src/review_v2/taxa/normalise.py   (after llm_names.py)

Per item (one row per scientific name part, see items.split_sci):
1. "gbif_exact": the scientific name given in the extraction matches the backbone exactly (strict match, synonyms
   resolved to the accepted name).
2. "llm_gbif_exact": no usable scientific name, no exact match, or only a higher-rank match for a binomial -> the
   LLM translation (llm_names.py) is looked up strictly; used when it matches exactly.
3. "gbif_higherrank": strict match only at a higher rank and the LLM gave nothing better.
4. "non_taxon" / "not_animal" (LLM), "unresolved" otherwise.
taxon_class: conventional class (gbif.standard_class): ray-finned fish have no class in the backbone and are
filled as Actinopterygii; the backbone classes Squamata, Testudines, Crocodylia are merged into Reptilia and
Elasmobranchii / Holocephali into Chondrichthyes.
Output: review_output/v2/taxa/species.csv
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.taxa import gbif, items  # noqa: E402
from review_v2.taxa.llm_names import CACHE as LLM_CACHE, entry  # noqa: E402

COLS = ["usageKey", "canonicalName", "rank", "status", "matchType", "phylum", "class", "order", "family", "genus",
        "species"]


def binomial(s):
    return isinstance(s, str) and len(s.split()) >= 2


def strict_matches(d):
    return gbif.match_many(sorted(d["sci"].dropna().unique()))


def needs_llm(row, sm):
    if not isinstance(row.sci, str):
        return True
    m = sm[row.sci]
    return not gbif.accepted(m) or (m["matchType"] == "HIGHERRANK" and binomial(row.sci))


def llm_entries():
    d = items.load()
    sm = strict_matches(d)
    return sorted({entry(r.name.strip(), r.sci or r.scientific_name.strip()) for r in d.itertuples()
                   if needs_llm(r, sm)})


def resolve():
    d = items.load()
    sm = strict_matches(d)
    llm = json.loads(LLM_CACHE.read_text(encoding="utf-8")) if LLM_CACHE.exists() else {}
    lm = gbif.match_many(sorted({v["scientific_name"] for v in llm.values() if v["scientific_name"]}))
    out = []
    for r in d.itertuples(index=False):
        rec = r._asdict()
        m, src, t = None, "unresolved", None
        if isinstance(r.sci, str) and gbif.accepted(sm[r.sci]):
            m, src = sm[r.sci], "gbif_exact" if sm[r.sci]["matchType"] == "EXACT" else "gbif_higherrank"
        if m is None or src == "gbif_higherrank" and binomial(r.sci):
            t = llm.get(entry(r.name.strip(), r.sci or r.scientific_name.strip()))
            if t and t["kind"] != "taxon":
                m, src = (None, t["kind"]) if m is None else (m, src)
            elif t and t["scientific_name"] and gbif.accepted(lm.get(t["scientific_name"], {})) \
                    and lm[t["scientific_name"]]["matchType"] == "EXACT":
                m, src = lm[t["scientific_name"]], "llm_gbif_exact"
        rec["source"] = src
        rec["llm_certain"] = t["certain"] if t else None
        rec.update({f"gbif_{c}": (m or {}).get(c) for c in COLS})
        out.append(rec)
    df = pd.DataFrame(out)
    df["taxon_class"] = [gbif.standard_class({"class": c, "phylum": p, "order": o}) if k == k else None
                         for c, p, o, k in zip(df["gbif_class"], df["gbif_phylum"], df["gbif_order"],
                                               df["gbif_usageKey"])]
    df["gbif_usageKey"] = df["gbif_usageKey"].astype("Int64")
    return df


if __name__ == "__main__":
    df = resolve()
    df.to_csv(gbif.DIR / "species.csv", index=False, encoding="utf-8")
    print(df["source"].value_counts().to_string())
    print("items with taxon:", int(df["gbif_usageKey"].notna().sum()), "of", len(df))
