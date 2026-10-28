"""Tidy tables of the coded corpus for figures, numbers and validation.

Usage: python src/review_v2/corpus/tables.py   (after corpus/build.py, taxa/normalise.py, registry/normalise.py)

One parquet file per table in review_output/v2/corpus/, all keyed by doi (and setting index where items belong
to a study setting). Every item carries `verified` (quote found in the paper, not in introduction or related
work; extraction/verify.py). Figures use verified items of eligible papers; validation can use all.
  settings          doi, setting, platform, platform_source, habitat, location_detail, verified
                    ("Not reported" replaced by the verified value of extraction/platform_pass.py, if any;
                    such a setting counts as verified)
  setting_countries doi, setting, country (aliases merged; "Global / web" kept as its own value)
  setting_spectra   doi, setting, spectrum, source, verified
  setting_species   doi, setting, name -> species item of the same paper by name
  species           taxa/species.csv (one row per item and scientific name part) + verified
  datasets          doi, name, role, availability, origin, canonical, family, generic, verified
  tasks             doi, task, role, verified
  algorithms        doi, name, type, role, canonical, family, generic, verified
  flags             doi, cost_reported, ethics_statement, explainability (value only when verified)
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.extraction.platform_pass import results as platform_results  # noqa: E402
from review_v2.extraction.verify import verified  # noqa: E402
from review_v2.registry.normalise import DIR as REGISTRY, key  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402
from review_v2.taxa.gbif import DIR as TAXA  # noqa: E402

V2 = ROOT / "review_output" / "v2"
OUT = V2 / "corpus"
RUN = V2 / "extraction" / "corpus_v2_opus"

COUNTRY_ALIAS = {
    "Brunei Darussalam": "Brunei", "Cabo Verde": "Cape Verde", "Congo, The Democratic Republic of the":
    "Democratic Republic of the Congo", "Curaçao": "Curacao", "Czechia": "Czech Republic",
    "Côte d'Ivoire": "Ivory Coast", "Lao People's Democratic Republic": "Laos", "Réunion": "Reunion",
    "Republic of the Congo": "Congo", "South Georgia": "South Georgia and the South Sandwich Islands",
    "Türkiye": "Turkey", "United States of America": "United States", "United States Virgin Islands":
    "U.S. Virgin Islands", "Viet Nam": "Vietnam", "Sint Eustatius": "Saint Eustatius",
    "Chagos Archipelago": "British Indian Ocean Territory",
}


def ok(item):
    return verified(item["evidence"])


def registry(kind):
    f = REGISTRY / f"{kind}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def build():
    reg = {k: registry(k) for k in ("algorithms", "datasets")}
    t = {k: [] for k in ("settings", "setting_countries", "setting_spectra", "setting_species", "datasets", "tasks",
                         "algorithms", "flags")}
    verified_species = {}
    platform_pass = platform_results()
    for f in sorted(RUN.glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        if "record" not in r:
            continue
        doi, rec = norm_doi(r["doi"]), r["record"]
        for i, s in enumerate(rec["settings"]):
            platform, platform_source = s["platform"], "extraction"
            if platform == "Not reported" and platform_pass.get((doi, i), (None, False))[1]:
                platform, platform_source = platform_pass[(doi, i)][0], "platform_pass"
            t["settings"].append({"doi": doi, "setting": i, "platform": platform, "platform_source": platform_source,
                                  "habitat": s["habitat"], "location_detail": s["location_detail"],
                                  "verified": ok(s) or platform_source == "platform_pass"})
            for c in s["countries"]:
                t["setting_countries"].append({"doi": doi, "setting": i, "country": COUNTRY_ALIAS.get(c, c)})
            for sp in s["spectra"]:
                t["setting_spectra"].append({"doi": doi, "setting": i, "spectrum": sp["value"],
                                             "source": sp["source"], "verified": ok(sp)})
            for n in s["species"]:
                t["setting_species"].append({"doi": doi, "setting": i, "name": n})
        for j, s in enumerate(rec["species"]):
            verified_species[(doi, j)] = ok(s)
        for d in rec["datasets"]:
            m = reg["datasets"].get(key(d["name"]), {})
            own = d["role"] == "collected_by_authors"
            t["datasets"].append({"doi": doi, "name": d["name"], "role": d["role"],
                                  "availability": d["availability"], "origin": d["origin"],
                                  "canonical": "own data" if own else m.get("canonical"),
                                  "family": "own data" if own else m.get("family"),
                                  "generic": own or m.get("generic"), "verified": ok(d)})
        for x in rec["tasks"]:
            t["tasks"].append({"doi": doi, "task": x["task"], "role": x["role"], "verified": ok(x)})
        for a in rec["algorithms"]:
            m = reg["algorithms"].get(key(a["name"]), {})
            t["algorithms"].append({"doi": doi, "name": a["name"], "type": a["type"], "role": a["role"],
                                    "canonical": m.get("canonical"), "family": m.get("family"),
                                    "generic": m.get("generic"), "verified": ok(a)})
        t["flags"].append({"doi": doi, **{k: v["value"] and ok(v) for k, v in rec["flags"].items()}})
    tables = {k: pd.DataFrame(v) for k, v in t.items()}
    sp = pd.read_csv(TAXA / "species.csv", low_memory=False)
    sp["verified"] = [verified_species.get((d, i), False) for d, i in zip(sp["doi"], sp["item"])]
    tables["species"] = sp
    return tables


if __name__ == "__main__":
    tables = build()
    for name, df in tables.items():
        df.to_parquet(OUT / f"{name}.parquet", index=False)
        print(f"{name}: {len(df)} rows")
