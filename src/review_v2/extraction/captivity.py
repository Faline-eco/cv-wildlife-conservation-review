"""Supplementary pass: were the animals in the analysed images in the wild or captive?

Usage: python src/review_v2/extraction/captivity.py <dois.txt> [--model ID] [--workers N]

Added after the scope was widened to zoo and captive animals (2026-10-22). The main extraction
(protocol_extract.md, frozen) records subject_type; papers coded "wild_free_ranging" or "captive_or_zoo"
take their tag from there (see corpus build). This pass is run only for papers whose subject_type is
"mixed" or "not_reported", where the main coding cannot tell wild + captive from wild + domestic.
One fresh headless call per paper on the same prepared text; output in extraction/captivity_v1/<paper_id>.json.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.fulltext.prepare import TEXT, paper_id, render  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

OUTDIR = ROOT / "review_output" / "v2" / "extraction" / "captivity_v1"

PROTOCOL = """You code one detail of a primary study for a systematic mapping study on computer vision for animal \
monitoring and conservation. Decide from the paper text only.

Question: where were the animals whose images or videos the paper itself analyses when they were recorded?
- "wild": free-ranging animals in natural or human-modified environments (camera traps, drones, field video, \
underwater surveys, citizen-science or field photographs of free-living animals). Free-roaming domestic animals \
that appear in such field data do not change this.
- "captive": animals held by people: zoos, aquaria, wildlife parks, sanctuaries, rescue or breeding centres, \
enclosures, cages, research tanks or facilities.
- "wild_and_captive": the analysed data contain both.
- "not_reported": the paper does not say, e.g. images from the web or from a public benchmark whose recording \
conditions the paper does not describe. Do not use outside knowledge about a named dataset.
Base the answer on the data the paper analyses, not on the intended application. Give a verbatim quote of at most \
30 words from the paper that supports the answer (empty for "not_reported" if nothing applies), the page number from \
the <<page N>> markers, and a reason of at most 25 words."""

SCHEMA = {
    "type": "object",
    "properties": {
        "captivity": {"type": "string", "enum": ["wild", "captive", "wild_and_captive", "not_reported"]},
        "quote": {"type": "string"},
        "page": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["captivity", "quote", "page", "reason"],
    "additionalProperties": False,
}


def prompt_hash(model):
    return hashlib.sha256((PROTOCOL + json.dumps(SCHEMA, sort_keys=True) + model).encode()).hexdigest()[:12]


def norm(t):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t.lower())).strip()


def call(model, text, workdir):
    cmd = [shutil.which("claude"), "-p", "--model", model, "--output-format", "json", "--system-prompt", PROTOCOL,
           "--json-schema", json.dumps(SCHEMA), "--tools", "", "--no-session-persistence"]
    res = subprocess.run(cmd, input="Code the following paper.\n\n" + text, capture_output=True, text=True,
                         encoding="utf-8", cwd=workdir, timeout=900)
    env = json.loads(res.stdout)
    if res.returncode != 0 or env.get("is_error"):
        tag = "limit: " if not (env.get("usage") or {}).get("output_tokens") else ""
        raise RuntimeError(tag + str(env.get("result"))[:400])
    out = env.get("structured_output") or json.loads(env["result"])
    return out, env.get("total_cost_usd")


def run_one(args):
    doi, model, workdir = args
    target = OUTDIR / f"{paper_id(doi)}.json"
    if target.exists():
        return "cached"
    src = TEXT / f"{paper_id(doi)}.json"
    if not src.exists():
        return "no_text"
    paper = json.loads(src.read_text(encoding="utf-8"))
    if paper["status"] != "ok":
        return paper["status"]
    text = render(paper)
    for attempt in range(3):
        try:
            out, cost = call(model, text, workdir)
            break
        except Exception as e:  # noqa: BLE001
            if "limit" in str(e).lower() or "overloaded" in str(e).lower():
                time.sleep(900)
            else:
                time.sleep(5)
    else:
        return "failed"
    q = norm(out["quote"])
    out["quote_found"] = bool(q) and q in norm(text)
    target.write_text(json.dumps({"doi": doi, "model": model, "prompt_hash": prompt_hash(model), "cost_usd": cost,
                                  "coded_at": datetime.now(timezone.utc).isoformat(), **out},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    return "ok"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dois")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    dois = list(dict.fromkeys(d for d in map(norm_doi, Path(a.dois).read_text().split()) if d))
    workdir = tempfile.mkdtemp(prefix="captivity_")
    with ThreadPoolExecutor(a.workers) as ex:
        status = list(ex.map(run_one, [(d, a.model, workdir) for d in dois]))
    print({s: status.count(s) for s in sorted(set(status))})
