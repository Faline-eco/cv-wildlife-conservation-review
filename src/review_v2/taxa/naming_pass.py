"""Opus check of the taxon naming per paper (plan 6.4): which names do the paper's taxon labels use?

Usage: python src/review_v2/taxa/naming_pass.py run [<dois.txt>] [--model ID] [--workers N]
       python src/review_v2/taxa/naming_pass.py compare      (against the text search of taxa/naming.py)

Added 2026-10-27 on the user's request. taxa/naming.py says whether a paper's scientific names occur in its text, not
which names the class labels use. This pass asks Opus. One fresh headless call per paper (no tools, no session
persistence, nothing shared between papers) on the prepared text only; the call does not see the extraction or the
text search, so its answer is independent of both. Without a DOI list it runs on all eligible papers.
Output: review_output/v2/taxa/naming_v1/<paper_id>.json, quote located by extraction/verify.py; naming_llm.csv.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.extraction.verify import locate, verified  # noqa: E402
from review_v2.fulltext.prepare import TEXT, paper_id, render  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

V2 = ROOT / "review_output" / "v2"
OUTDIR = V2 / "taxa" / "naming_v1"
CLASSES = ["scientific", "common", "both", "not applicable"]

PROTOCOL = """You code one detail of a primary study for a systematic mapping study on computer vision for animal \
monitoring and conservation. Decide from the paper text only; do not use outside knowledge.

Question: how does the paper name the animal taxa that its computer-vision method works on (the classes it \
classifies, detects, counts or re-identifies, or the target taxa of the study)? Only taxa analysed in the study \
count, not taxa mentioned in the introduction, related work or as future work.
1. `label_naming`: the names the paper uses for these taxa in its own labels, class lists, tables, figures and \
results.
   - "scientific": Latin scientific names (binomials such as "Ursus arctos", genera, or higher ranks such as \
"Cervidae", "Aves").
   - "common": vernacular names only (English or another language, e.g. "red deer", "birds", "sea cucumber").
   - "both": the labels themselves combine both (e.g. "red deer (Cervus elaphus)" in the class list), or some \
labels are scientific and others common.
   - "not applicable": no taxon labels (e.g. animal vs background, a single unnamed "animal" class). A study on \
one species (e.g. re-identification of individuals) is coded by how it names that species.
2. `scientific_given`: does the paper state the scientific name anywhere in its text for the analysed taxa? \
"all", "some", "none", or "not applicable". A scientific name only in the reference list does not count.
3. `examples`: up to 8 taxon labels exactly as the paper writes them.
4. A verbatim quote of at most 30 words that shows how the analysed taxa are named (e.g. the class list), the page \
number from the <<page N>> markers, and a reason of at most 20 words. Empty quote for "not applicable"."""

SCHEMA = {"type": "object", "properties": {
    "label_naming": {"type": "string", "enum": CLASSES},
    "scientific_given": {"type": "string", "enum": ["all", "some", "none", "not applicable"]},
    "examples": {"type": "array", "items": {"type": "string"}},
    "quote": {"type": "string"}, "page": {"type": "integer"}, "reason": {"type": "string"}},
    "required": ["label_naming", "scientific_given", "examples", "quote", "page", "reason"],
    "additionalProperties": False}


def prompt_hash(model):
    return hashlib.sha256((PROTOCOL + json.dumps(SCHEMA, sort_keys=True) + model).encode()).hexdigest()[:12]


def call(model, prompt, workdir):
    cmd = [shutil.which("claude"), "-p", "--model", model, "--output-format", "json", "--system-prompt", PROTOCOL,
           "--json-schema", json.dumps(SCHEMA), "--tools", "", "--no-session-persistence"]
    res = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=workdir,
                         timeout=900)
    env = json.loads(res.stdout)
    if res.returncode != 0 or env.get("is_error"):
        tag = "limit: " if not (env.get("usage") or {}).get("output_tokens") else ""
        raise RuntimeError(tag + str(env.get("result"))[:400])
    return env.get("structured_output") or json.loads(env["result"]), env.get("total_cost_usd")


def run_one(args):
    doi, model, root = args
    target = OUTDIR / f"{paper_id(doi)}.json"
    if target.exists():
        return "cached"
    src = TEXT / f"{paper_id(doi)}.json"
    if not src.exists():
        return "no_text"
    paper = json.loads(src.read_text(encoding="utf-8"))
    workdir = tempfile.mkdtemp(dir=root)   # own empty working directory per paper
    for _ in range(3):
        try:
            out, cost = call(model, f"Paper:\n{render(paper)}", workdir)
            break
        except Exception as e:  # noqa: BLE001
            print("retry", doi, str(e)[:120], flush=True)
            time.sleep(900 if "limit" in str(e).lower() or "overloaded" in str(e).lower() else 5)
    else:
        return "failed"
    out["evidence"] = locate(out["quote"], out["page"], paper) if out["quote"] else None
    target.write_text(json.dumps({"doi": doi, "model": model, "prompt_hash": prompt_hash(model), "cost_usd": cost,
                                  "coded_at": datetime.now(timezone.utc).isoformat(), **out},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    return "ok"


def table():
    rows = []
    for f in OUTDIR.glob("*.json"):
        j = json.loads(f.read_text(encoding="utf-8"))
        rows.append({"doi": norm_doi(j["doi"]), "label_naming": j["label_naming"],
                     "scientific_given": j["scientific_given"], "examples": "; ".join(j["examples"]),
                     "quote_verified": verified(j["evidence"]) if j["evidence"] else None, "cost_usd": j["cost_usd"]})
    df = pd.DataFrame(rows)
    df.to_csv(V2 / "taxa" / "naming_llm.csv", index=False)
    return df


def run(a):
    OUTDIR.mkdir(parents=True, exist_ok=True)
    if a.dois:
        dois = list(dict.fromkeys(d for d in map(norm_doi, Path(a.dois).read_text().split()) if d))
    else:
        p = pd.read_csv(V2 / "corpus" / "papers.csv")
        dois = sorted(set(p.loc[p["eligible"], "doi"]))
    print(len(dois), "papers", flush=True)
    root = tempfile.mkdtemp(prefix="naming_")
    with ThreadPoolExecutor(a.workers) as ex:
        status = list(ex.map(run_one, [(d, a.model, root) for d in dois]))
    df = table()
    print({s: status.count(s) for s in sorted(set(status))}, f"total ${df['cost_usd'].fillna(0).sum():.2f}")
    print(df["label_naming"].value_counts().to_string())


def compare(a):
    df = table().merge(pd.read_csv(V2 / "taxa" / "naming_papers.csv"), on="doi")
    print(len(df), "papers; quote verified:", df["quote_verified"].mean().round(3))
    print(pd.crosstab(df["label_naming"], df["taxon_naming_species"], margins=True).to_string())
    print(pd.crosstab(df["scientific_given"], df["taxon_naming_species"], margins=True).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "compare"])
    ap.add_argument("dois", nargs="?")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    {"run": run, "compare": compare}[a.cmd](a)
