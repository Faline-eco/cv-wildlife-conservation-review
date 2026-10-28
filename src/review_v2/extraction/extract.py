"""Full-text extraction with Claude Code in headless mode, one paper per fresh call.

Usage: python src/review_v2/extraction/extract.py <dois.txt> <run_name> [--model ID] [--workers N] [--limit N]

Reads the prepared text (fulltext/prepare.py) and writes one record per paper to
review_output/v2/extraction/<run_name>/<paper_id>.json, with provenance and checked evidence.
Existing records are skipped, failures are listed in <run_name>/failures.jsonl.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.extraction.schema import SCHEMA, SCHEMA_VERSION  # noqa: E402
from review_v2.extraction.verify import check_record  # noqa: E402
from review_v2.fulltext.prepare import TEXT, paper_id, render  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = ROOT / "review_output" / "v2" / "extraction"
PROTOCOL = (HERE / "protocol_extract.md").read_text(encoding="utf-8")


def prompt_hash(model):
    blob = PROTOCOL + json.dumps(SCHEMA, sort_keys=True) + model
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def call_claude(model, text, workdir):
    cmd = [shutil.which("claude"), "-p", "--model", model, "--output-format", "json",
           "--system-prompt", PROTOCOL, "--json-schema", json.dumps(SCHEMA),
           "--tools", "", "--no-session-persistence"]
    res = subprocess.run(cmd, input="Code the following paper.\n\n" + text, capture_output=True, text=True,
                         encoding="utf-8", cwd=workdir, timeout=1800)
    try:
        env = json.loads(res.stdout)
    except ValueError:
        raise RuntimeError(res.stderr[:500] or res.stdout[:500]) from None
    if res.returncode != 0 or env.get("is_error"):
        # a call rejected before any tokens were used is the plan's usage limit, whatever the wording
        tag = "limit: " if not (env.get("usage") or {}).get("output_tokens") else ""
        raise RuntimeError(tag + str(env.get("result"))[:400])
    out = env.get("structured_output")
    if out is None:
        if env.get("is_error"):
            raise RuntimeError(str(env.get("result"))[:500])
        out = json.loads(env["result"])
    return out, {"usage": env.get("usage"), "model_usage": env.get("modelUsage"),
                 "cost_usd": env.get("total_cost_usd"), "duration_ms": env.get("duration_ms")}


def run_one(args):
    doi, model, outdir, workdir = args
    target = outdir / f"{paper_id(doi)}.json"
    if target.exists():
        return "cached"
    src = TEXT / f"{paper_id(doi)}.json"
    if not src.exists():
        return "no_text"
    paper = json.loads(src.read_text(encoding="utf-8"))
    if paper["status"] != "ok":
        return paper["status"]
    err, attempts = None, 0
    while attempts < 2:
        try:
            record, meta = call_claude(model, render(paper), workdir)
            break
        except Exception as e:  # noqa: BLE001
            err = str(e)[:400]
            if any(w in err.lower() for w in ("limit", "overloaded", "429", "529")):
                time.sleep(900)     # usage limit of the plan: wait, do not count as a failed attempt
            else:
                attempts += 1
                time.sleep(5)
    else:
        with open(outdir / "failures.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"doi": doi, "error": err}) + "\n")
        return "failed"
    check_record(record, paper)
    out = {"doi": doi, "provenance": {
        "model": model, "schema_version": SCHEMA_VERSION, "prompt_hash": prompt_hash(model),
        "pdf_sha256": paper["sha256"], "extracted_at": datetime.now(timezone.utc).isoformat(), **meta,
    }, "record": record}
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return "ok"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dois")
    ap.add_argument("run_name")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    dois = list(dict.fromkeys(d for d in map(norm_doi, Path(a.dois).read_text().splitlines()) if d))
    if a.limit:
        dois = dois[:a.limit]
    outdir = OUT / a.run_name
    outdir.mkdir(parents=True, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="extract_")  # neutral folder: no project memory or settings
    with ThreadPoolExecutor(a.workers) as ex:
        status = list(ex.map(run_one, [(d, a.model, outdir, workdir) for d in dois]))
    print({s: status.count(s) for s in sorted(set(status))})
