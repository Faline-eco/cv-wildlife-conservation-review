"""GBIF backbone lookups with a local cache.

match(name, strict=True): /v1/species/match with kingdom hint Animalia. strict=True disables fuzzy matching, so a
name is only accepted when it exists in the backbone as written (matchType EXACT) or when GBIF falls back to the
next higher rank it knows (HIGHERRANK, e.g. a subspecies missing from the backbone). Accepted synonyms are
resolved to the accepted usage (acceptedUsageKey).
The non-strict mode is kept only for the evaluation of fuzzy matching (evaluate.py).
Cache: review_output/v2/taxa/gbif_cache.json, key "<strict>|<name>".
"""
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.fetch import get  # noqa: E402
from review_v2.search.merge import ROOT  # noqa: E402

DIR = ROOT / "review_output" / "v2" / "taxa"
CACHE = DIR / "gbif_cache.json"
RANKS = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]
RANK_ORDER = {r.upper(): i for i, r in enumerate(RANKS)}
# not in the GBIF backbone (ray-finned fish have no class there); filled by hand so that "fish" can be coded
MISSING = {"Actinopterygii": {"usageKey": 204, "canonicalName": "Actinopterygii", "rank": "CLASS", "status": "ACCEPTED",
                              "matchType": "EXACT", "kingdom": "Animalia", "phylum": "Chordata",
                              "class": "Actinopterygii", "note": "key 204 exists but species are not attached to it in the backbone"},
           "Reptilia": {"usageKey": 358, "canonicalName": "Reptilia", "rank": "CLASS", "status": "ACCEPTED",
                        "matchType": "EXACT", "kingdom": "Animalia", "phylum": "Chordata", "class": "Reptilia",
                        "note": "backbone splits reptiles into the classes Squamata, Testudines, Crocodylia"},
           "Chondrichthyes": {"usageKey": 121, "canonicalName": "Elasmobranchii", "rank": "CLASS",
                              "status": "ACCEPTED", "matchType": "EXACT", "kingdom": "Animalia", "phylum": "Chordata",
                              "class": "Elasmobranchii",
                              "note": "not in backbone; mapped to Elasmobranchii (sharks, rays), as in the papers"}}
# classes as usually reported (GBIF backbone classes -> conventional classes)
CLASS_ALIAS = {"Squamata": "Reptilia", "Testudines": "Reptilia", "Crocodylia": "Reptilia",
               "Rhynchocephalia": "Reptilia", "Elasmobranchii": "Chondrichthyes", "Holocephali": "Chondrichthyes"}


def standard_class(m):
    """Conventional class of a backbone match (fills ray-finned fish, merges reptile and shark classes)."""
    c = m.get("class")
    if not c and m.get("phylum") == "Chordata" and m.get("order"):
        c = "Actinopterygii"
    return CLASS_ALIAS.get(c, c)
_lock = threading.Lock()
_cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def _fetch(name, strict):
    r = get("https://api.gbif.org/v1/species/match",
            params={"name": name, "strict": str(strict).lower(), "kingdom": "Animalia", "verbose": "true"})
    m = r.json() if r.status_code == 200 else {"matchType": "ERROR"}
    alts = [a for a in m.pop("alternatives", []) if a.get("matchType") == "EXACT" and a.get("kingdom") == "Animalia"
            and a.get("canonicalName") == name]
    if strict and not accepted(m) and alts:
        # homonyms (Polychaeta: class and genus) make the strict match fall back to Animalia; take the exact
        # alternatives, highest rank first (a single-word name in these papers is a group, not a genus)
        m = {**sorted(alts, key=lambda a: RANK_ORDER.get(a.get("rank"), 9))[0], "matchType": "EXACT",
             "homonyms": [a.get("rank") for a in alts]}
    if m.get("acceptedUsageKey") and m.get("status") == "SYNONYM":
        acc = get(f"https://api.gbif.org/v1/species/{m['acceptedUsageKey']}").json()
        m = {**m, "synonymOf": m.get("canonicalName"), "usageKey": acc["key"],
             "canonicalName": acc.get("canonicalName"), "rank": acc.get("rank"),
             **{k: acc.get(k) for k in RANKS}, "status": "ACCEPTED_VIA_SYNONYM"}
    return m


def match(name, strict=True):
    if name in MISSING:
        return MISSING[name]
    key = f"{int(strict)}|{name}"
    if key not in _cache:
        m = _fetch(name, strict)
        with _lock:
            _cache[key] = m
    m = _cache[key]
    if strict and m.get("matchType") == "HIGHERRANK" and m.get("canonicalName") == name:
        # e.g. "Lepus": the genus itself, reported as HIGHERRANK because of a placeholder species "Lepus spec"
        m = {**m, "matchType": "EXACT"}
    if strict and m.get("matchType") == "FUZZY" and _same_but_ending(name, m.get("canonicalName") or ""):
        m = {**m, "matchType": "EXACT", "note": "epithet ending (gender agreement)"}
    return m


def _same_but_ending(a, b):
    """'Erethizon dorsatum' vs 'Erethizon dorsatus': same genus, epithets differ only in the Latin ending."""
    a, b = a.split(), b.split()
    if len(a) != len(b) or len(a) < 2 or a[0] != b[0]:
        return False
    stem = re.compile(r"(us|um|a|is|e|er|ae|i)$")
    return all(stem.sub("", x) == stem.sub("", y) for x, y in zip(a[1:], b[1:]))


def match_many(names, strict=True, workers=8):
    with ThreadPoolExecutor(workers) as ex:
        out = dict(zip(names, ex.map(lambda n: match(n, strict), names)))
    save()
    return out


def save():
    DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        CACHE.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")


def accepted(m):
    """True when a strict match can be used: exact name in the backbone, in kingdom Animalia."""
    return m.get("matchType") in ("EXACT", "HIGHERRANK") and m.get("kingdom") == "Animalia" \
        and m.get("rank") not in (None, "KINGDOM")
