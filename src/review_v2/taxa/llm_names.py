"""LLM translation of taxon names that GBIF cannot match exactly.

Usage: python src/review_v2/taxa/llm_names.py [--model ID] [--batch N] [--workers N]

Input: every distinct species item that has no usable scientific name (common names such as "elephant",
"echinus", "fish") and every scientific name that the strict GBIF match rejects or only matches at a higher
rank (typos, PDF hyphenation, outdated names). The model returns one accepted scientific name per entry; the
answer is used only if it matches the GBIF backbone exactly (normalise.py). GBIF fuzzy matching is not used:
on common names it returns unrelated taxa ("serval" -> a beetle, "echinus" -> a mite).
Cache: review_output/v2/taxa/llm_names.json, key = entry text.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.taxa.gbif import DIR  # noqa: E402

CACHE = DIR / "llm_names.json"

PROTOCOL = """You normalise animal names extracted from computer-vision papers on wildlife monitoring to the GBIF \
backbone taxonomy. Each entry is a name as written in a paper, sometimes with a scientific name the paper gave \
(possibly misspelt, split by PDF hyphenation, wrongly capitalised or outdated).
For each entry return:
- "scientific_name": the currently accepted scientific name (canonical form, no author) of the lowest taxon that \
the name denotes in a wildlife-monitoring context. If a common name can denote several species, give their lowest \
common taxon ("elephant" -> Elephantidae, "deer" -> Cervidae, "zebra" -> Equus, "tiger" -> Panthera tigris, \
"fish" -> Actinopterygii, "echinus" in underwater datasets -> Echinoidea, "holothurian" -> Holothuroidea). \
Correct misspellings ("Columbia livia" -> Columba livia). Domestic animals get their species ("cow" -> Bos taurus, \
"dog" -> Canis familiaris). Use only names at the ranks phylum, class, order, family, genus, species or \
subspecies: for a superfamily, subfamily, suborder, infraclass or similar group give the next higher of these ranks \
("butterflies" -> Lepidoptera, "mice" -> Muridae, "octocorals" -> Anthozoa). Empty string if the entry is not a \
taxon.
- "rank": one of species, genus, family, order, class, phylum, other (subspecies).
- "kind": "taxon"; "non_taxon" for generic or functional groups that map to no clade below Animalia \
("animals", "wild animals", "large mammals" is still class Mammalia so taxon; "plankton", "marine debris", \
"particles", "background"); "not_animal" for humans, plants, algae, fungi, objects.
- "certain": false if you are guessing (unknown name, ambiguous abbreviation).
Return the entries in the given order with the same ids."""

SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {
        "id": {"type": "integer"}, "scientific_name": {"type": "string"},
        "rank": {"type": "string", "enum": ["species", "genus", "family", "order", "class", "phylum", "other"]},
        "kind": {"type": "string", "enum": ["taxon", "non_taxon", "not_animal"]},
        "certain": {"type": "boolean"}},
    "required": ["id", "scientific_name", "rank", "kind", "certain"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False}


def call(model, entries, workdir):
    text = "\n".join(f"{i}\t{e}" for i, e in enumerate(entries))
    cmd = [shutil.which("claude"), "-p", "--model", model, "--output-format", "json", "--system-prompt", PROTOCOL,
           "--json-schema", json.dumps(SCHEMA), "--tools", "", "--no-session-persistence"]
    res = subprocess.run(cmd, input="Entries (id<TAB>name as written [| scientific name given]):\n" + text,
                         capture_output=True, text=True, encoding="utf-8", cwd=workdir, timeout=1800)
    env = json.loads(res.stdout)
    if res.returncode != 0 or env.get("is_error"):
        raise RuntimeError(str(env.get("result"))[:400])
    out = env.get("structured_output") or json.loads(env["result"])
    return {entries[x["id"]]: {k: x[k] for k in ("scientific_name", "rank", "kind", "certain")}
            for x in out["items"] if 0 <= x["id"] < len(entries)}, env.get("total_cost_usd") or 0


def translate(entries, model="claude-opus-5-5", batch=80, workers=4):
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    todo = sorted(set(entries) - set(cache))
    chunks = [todo[i:i + batch] for i in range(0, len(todo), batch)]
    workdir = tempfile.mkdtemp(prefix="taxa_")
    cost = 0

    def run(chunk):
        for _ in range(3):
            try:
                return call(model, chunk, workdir)
            except Exception as e:  # noqa: BLE001
                print("retry:", e, flush=True)
        return {}, 0
    with ThreadPoolExecutor(workers) as ex:
        for i, (res, c) in enumerate(ex.map(run, chunks)):
            cache.update(res)
            cost += c
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
            print(f"  batch {i + 1}/{len(chunks)}  cached {len(cache)}  ${cost:.2f}", flush=True)
    return cache


def entry(name, sci):
    return f"{name} | {sci}" if sci else name


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--batch", type=int, default=80)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    from review_v2.taxa.normalise import llm_entries
    translate(llm_entries(), a.model, a.batch, a.workers)
