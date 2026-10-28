"""Title/abstract screening with Claude Code in headless mode.

Usage:
  python src/review_v2/screening/screen.py <records.csv|jsonl> <run_name> [--screener a|b] [--limit N]

Each batch of records is one fresh `claude -p` call with a pinned model, no tools and a JSON schema.
Results are cached per batch in review_output/v2/screening/<run_name>/<screener>/, so a run resumes.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "review_output" / "v2" / "screening"

MODEL = "claude-sonnet-5-5"
BATCH = 20
WORKERS = 4

CODES = ["none", "E-PLANT", "E-AGRI", "E-LAB", "E-CAPTIVE", "E-HUMAN", "E-NOCV", "E-AUDIO",
         "E-REVIEW", "E-GENERIC"]
SCHEMA = {
    "type": "object",
    "properties": {"decisions": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "decision": {"type": "string", "enum": ["include", "exclude", "unsure"]},
            "criterion": {"type": "string", "enum": CODES},
            "reason": {"type": "string"},
        },
        "required": ["id", "decision", "criterion", "reason"],
        "additionalProperties": False,
    }}},
    "required": ["decisions"],
    "additionalProperties": False,
}

# The two screeners share the protocol and differ only in the order in which they test it.
FRAMING = {
    "a": "Work through each record by first testing the inclusion criteria, then the exclusion criteria.",
    "b": "Work through each record by first looking for any exclusion criterion that applies, "
         "then testing the inclusion criteria. Be strict about the wild / free-ranging requirement.",
}


def system_prompt(screener):
    return (HERE / "protocol_ta.md").read_text(encoding="utf-8") + "\n\n# Procedure\n" + FRAMING[screener]


def prompt_hash(screener):
    blob = system_prompt(screener) + json.dumps(SCHEMA, sort_keys=True) + MODEL
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def load_records(path):
    path = Path(path)
    df = pd.read_json(path, lines=True) if path.suffix == ".jsonl" else pd.read_csv(path)
    if "id" not in df.columns:
        df["id"] = df["doi"].fillna("").astype(str)
        missing = df["id"] == ""
        df.loc[missing, "id"] = ["rec-" + hashlib.sha1(str(t).encode()).hexdigest()[:10]
                                 for t in df.loc[missing, "title"]]
    return df.drop_duplicates("id").reset_index(drop=True)


def render(batch):
    parts = []
    for r in batch:
        def val(k):
            v = r.get(k)
            return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
        parts.append(
            f"<record id=\"{r['id']}\">\nTitle: {val('title')}\nVenue: {val('venue')} ({val('year')})\n"
            f"Keywords: {val('keywords')}\nAbstract: {val('abstract')[:4000] or '[no abstract available]'}\n</record>"
        )
    return f"Screen the following {len(batch)} records.\n\n" + "\n\n".join(parts)


def call_claude(screener, user_prompt, workdir):
    cmd = [shutil.which("claude"), "-p", "--model", MODEL, "--output-format", "json",
           "--system-prompt", system_prompt(screener), "--json-schema", json.dumps(SCHEMA),
           "--tools", "", "--no-session-persistence"]
    res = subprocess.run(cmd, input=user_prompt, capture_output=True, text=True, encoding="utf-8",
                         cwd=workdir, timeout=900)
    if res.returncode != 0:
        raise RuntimeError(res.stderr[:500] or res.stdout[:500])
    env = json.loads(res.stdout)
    out = env.get("structured_output")
    if out is None:
        out = json.loads(env["result"])
    usage = env.get("usage", {})
    return out["decisions"], {"model_usage": env.get("modelUsage"), "usage": usage}


def run_batch(args):
    screener, idx, batch, outdir, workdir = args
    target = outdir / f"batch_{idx:05d}.json"
    if target.exists():
        return json.loads(target.read_text(encoding="utf-8"))["decisions"]
    ids = [r["id"] for r in batch]
    for attempt in range(3):
        try:
            decisions, meta = call_claude(screener, render(batch), workdir)
            got = {d["id"]: d for d in decisions}
            if set(got) != set(ids):
                raise RuntimeError(f"id mismatch: {len(set(ids) - set(got))} missing")
            target.write_text(json.dumps({"model": MODEL, "screener": screener,
                                          "prompt_hash": prompt_hash(screener), "meta": meta,
                                          "decisions": [got[i] for i in ids]},
                                         ensure_ascii=False, indent=1), encoding="utf-8")
            return [got[i] for i in ids]
        except Exception as e:  # noqa: BLE001
            err = str(e)
    print(f"batch {idx} failed: {err}", file=sys.stderr)
    return []


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("records")
    ap.add_argument("run_name")
    ap.add_argument("--screener", default="a", choices=["a", "b"])
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    df = load_records(a.records)
    if a.limit:
        df = df.head(a.limit)
    rows = df.to_dict("records")
    outdir = OUT / a.run_name / a.screener
    outdir.mkdir(parents=True, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="screen_")  # neutral folder: no project memory or settings
    jobs = [(a.screener, i // BATCH, rows[i:i + BATCH], outdir, workdir) for i in range(0, len(rows), BATCH)]
    with ThreadPoolExecutor(WORKERS) as ex:
        results = [d for batch in ex.map(run_batch, jobs) for d in batch]
    res = pd.DataFrame(results)
    res.to_csv(OUT / a.run_name / f"decisions_{a.screener}.csv", index=False, encoding="utf-8")
    print(f"{len(res)} of {len(rows)} records decided")
    if len(res):
        print(res["decision"].value_counts().to_string())
