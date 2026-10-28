"""Canonical value sets per paper and field, shared by the agreement (5.2) and stability (5.5) checks.

values(record, only_verified) -> {field: set of canonical values}
  platform, habitat, spectrum, country (aliases merged, "Global / web" dropped), task (primary tasks),
  taxon_species / taxon_genus / taxon_class (GBIF backbone, target species items only; see taxa/normalise.py),
  algorithm (registry family, generic names dropped), dataset (registry family of named datasets).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.corpus.tables import COUNTRY_ALIAS, registry  # noqa: E402
from review_v2.extraction.verify import verified  # noqa: E402
from review_v2.registry.normalise import key  # noqa: E402
from review_v2.taxa import gbif, items  # noqa: E402
from review_v2.taxa.llm_names import CACHE as LLM_CACHE, entry  # noqa: E402

_REG = {k: registry(k) for k in ("algorithms", "datasets")}
_LLM = json.loads(LLM_CACHE.read_text(encoding="utf-8")) if LLM_CACHE.exists() else {}


def taxa(name, scientific_name):
    """GBIF matches for one species item (same rules as taxa/normalise.py, without new LLM calls)."""
    out = []
    for part in items.split_sci(scientific_name) or [None]:
        m = gbif.match(part) if part else {}
        if not gbif.accepted(m) or (m.get("matchType") == "HIGHERRANK" and part and len(part.split()) > 1):
            t = _LLM.get(entry(name.strip(), part or scientific_name.strip()))
            if t and t["kind"] == "taxon" and t["scientific_name"]:
                m2 = gbif.match(t["scientific_name"])
                if gbif.accepted(m2) and m2.get("matchType") == "EXACT":
                    m = m2
        if gbif.accepted(m):
            out.append(m)
    return out


def taxon_class(m):
    return gbif.standard_class(m)


def values(rec, only_verified=True):
    def ok(x):
        return verified(x["evidence"]) if only_verified else True
    r = rec["record"]
    s = [x for x in r["settings"] if ok(x)]
    v = {
        "platform": {x["platform"] for x in s},
        "habitat": {x["habitat"] for x in s},
        "spectrum": {sp["value"] for x in r["settings"] for sp in x["spectra"] if ok(sp)},
        "country": {COUNTRY_ALIAS.get(c, c) for x in s for c in x["countries"] if c != "Global / web"},
        "task": {t["task"] for t in r["tasks"] if ok(t) and t["role"] == "primary"},
        "algorithm": set(), "dataset": set(), "taxon_species": set(), "taxon_genus": set(), "taxon_class": set(),
    }
    for a in r["algorithms"]:
        m = _REG["algorithms"].get(key(a["name"]), {})
        if ok(a) and not m.get("generic", False):
            v["algorithm"].add(m.get("family") or key(a["name"]))
    for d in r["datasets"]:
        m = _REG["datasets"].get(key(d["name"]), {})
        if ok(d) and d["role"] != "collected_by_authors" and not m.get("generic", False):
            v["dataset"].add(m.get("family") or key(d["name"]))
    for sp in r["species"]:
        if not ok(sp) or sp["role"] != "target":
            continue
        for m in taxa(sp["name"], sp["scientific_name"]):
            if m.get("species"):
                v["taxon_species"].add(m["species"])
            if m.get("genus"):
                v["taxon_genus"].add(m["genus"])
            if taxon_class(m):
                v["taxon_class"].add(taxon_class(m))
    return v
