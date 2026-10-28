"""Third screening pass: an adjudicator decides the records the two screeners left unsure.

Usage:
  python src/review_v2/screening/adjudicate.py collect <out.csv> <run_name> [<run_name> ...]
      gathers the unsure records of the given screening runs (ta_decisions.csv) into one input file
  python src/review_v2/screening/adjudicate.py rescue <out.csv> <run_name> [<run_name> ...]
      agreed exclusions of the three lossy groups (coral/benthic, wild animals near farms, fishery catch)
  python src/review_v2/screening/adjudicate.py run <input.csv> <adjudication_name> [--limit N]
      one fresh `claude -p` call per batch; cached per batch in screening/<adjudication_name>/batches/

Output: review_output/v2/screening/<adjudication_name>/adjudicated.csv
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
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.screening.screen import CODES, HERE, OUT  # noqa: E402

MODEL = "claude-opus-5-5"
BATCH = 15
WORKERS = 4
PROTOCOL = (HERE / "protocol_adjudicate.md").read_text(encoding="utf-8")
SUBJECTS = ["wild", "captive_or_zoo", "farmed_or_pet", "laboratory", "specimen_or_catch", "mixed",
            "unclear", "no_animals"]
SCHEMA = {
    "type": "object",
    "properties": {"decisions": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "decision": {"type": "string", "enum": ["include", "exclude", "fulltext"]},
            "criterion": {"type": "string", "enum": CODES},
            "subject": {"type": "string", "enum": SUBJECTS},
            "reason": {"type": "string"},
        },
        "required": ["id", "decision", "criterion", "subject", "reason"],
        "additionalProperties": False,
    }}},
    "required": ["decisions"],
    "additionalProperties": False,
}
PROMPT_HASH = hashlib.sha256((PROTOCOL + json.dumps(SCHEMA, sort_keys=True) + MODEL).encode()).hexdigest()[:12]
KEEP = ["id", "doi", "title", "abstract", "year", "venue", "keywords", "decision_a", "criterion_a", "reason_a",
        "decision_b", "criterion_b", "reason_b"]


def collect(out, runs):
    parts = []
    for run in runs:
        d = pd.read_csv(OUT / run / "ta_decisions.csv", low_memory=False)
        d = d[d["ta_decision"] == "unsure"][KEEP].copy()
        d["run"] = run
        parts.append(d)
    df = pd.concat(parts).drop_duplicates("id").reset_index(drop=True)
    df.to_csv(out, index=False, encoding="utf-8")
    print(f"{len(df)} unsure records ->", out)
    print(df["run"].value_counts().to_string())


def rescue(out, runs):
    """Agreed exclusions of three groups that the calibration showed to be lossy, for re-adjudication:
    coral / benthic fauna coded E-PLANT, wild animals near farms coded E-AGRI, fishery catch coded E-AGRI
    (same keyword rules as the 2026-10-13 rescue of the first runs)."""
    parts = []
    for run in runs:
        t = pd.read_csv(OUT / run / "ta_decisions.csv", low_memory=False)
        t = t[t["ta_decision"] == "exclude"].copy()
        txt = (t["title"].fillna("") + " " + t["abstract"].fillna("")).str.lower()
        cv = txt.str.contains(r"deep learning|neural network|detection|segmentation|classif|computer vision|"
                              r"machine learning|image analysis|yolo")
        coral = (t["criterion_a"] == "E-PLANT") & txt.str.contains(r"coral|benthic|sponge") & cv
        intr = (t["criterion_a"] == "E-AGRI") & txt.str.contains(
            r"wild animal|wildlife|intrusion|human-wildlife|human-animal|elephant|wild boar") & cv
        catch = (t["criterion_a"] == "E-AGRI") & txt.str.contains(
            r"fishing vessel|on-board|onboard|electronic monitoring|bycatch|by-catch|catch") &             txt.str.contains("fish") & cv & ~txt.str.contains("aquaculture|farm")
        k = t[coral | intr | catch][KEEP].copy()
        k["run"] = run
        parts.append(k)
    df = pd.concat(parts).drop_duplicates("id").reset_index(drop=True)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8")
    print(f"{len(df)} agreed exclusions to re-adjudicate ->", out)


def val(r, k):
    v = r.get(k)
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def render(batch):
    parts = []
    for r in batch:
        votes = "\n".join(
            f"Screener {s.upper()}: {val(r, 'decision_' + s) or 'no decision'} "
            f"({val(r, 'criterion_' + s) or 'none'}) - {val(r, 'reason_' + s)}" for s in "ab")
        parts.append(
            f"<record id=\"{r['id']}\">\nTitle: {val(r, 'title')}\nVenue: {val(r, 'venue')} ({val(r, 'year')})\n"
            f"Keywords: {val(r, 'keywords')}\n"
            f"Abstract: {val(r, 'abstract')[:4000] or '[no abstract available]'}\n{votes}\n</record>")
    return f"Adjudicate the following {len(batch)} records.\n\n" + "\n\n".join(parts)


def call_claude(user_prompt, workdir):
    cmd = [shutil.which("claude"), "-p", "--model", MODEL, "--output-format", "json",
           "--system-prompt", PROTOCOL, "--json-schema", json.dumps(SCHEMA),
           "--tools", "", "--no-session-persistence"]
    res = subprocess.run(cmd, input=user_prompt, capture_output=True, text=True, encoding="utf-8",
                         cwd=workdir, timeout=1200)
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
        out = json.loads(env["result"])
    return out["decisions"], {"model_usage": env.get("modelUsage"), "usage": env.get("usage"),
                              "cost_usd": env.get("total_cost_usd")}


def run_batch(args):
    idx, batch, outdir, workdir = args
    target = outdir / f"batch_{idx:05d}.json"
    if target.exists():
        return json.loads(target.read_text(encoding="utf-8"))["decisions"]
    ids = [r["id"] for r in batch]
    err, attempts = None, 0
    while attempts < 3:
        try:
            decisions, meta = call_claude(render(batch), workdir)
            got = {d["id"]: d for d in decisions}
            if set(got) != set(ids):
                raise RuntimeError(f"id mismatch: {len(set(ids) - set(got))} missing")
            target.write_text(json.dumps({"model": MODEL, "prompt_hash": PROMPT_HASH, "meta": meta,
                                          "decisions": [got[i] for i in ids]},
                                         ensure_ascii=False, indent=1), encoding="utf-8")
            return [got[i] for i in ids]
        except Exception as e:  # noqa: BLE001
            err = str(e)[:400]
            if any(w in err.lower() for w in ("limit", "overloaded", "429", "529")):
                time.sleep(900)     # usage limit of the plan: wait, do not count as a failed attempt
            else:
                attempts += 1
    print(f"batch {idx} failed: {err}", file=sys.stderr)
    return []


def run(records, name, limit=None):
    df = pd.read_csv(records, low_memory=False)
    if limit:
        df = df.head(limit)
    rows = df.to_dict("records")
    outdir = OUT / name / "batches"
    outdir.mkdir(parents=True, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="adjudicate_")  # neutral folder: no project memory or settings
    jobs = [(i // BATCH, rows[i:i + BATCH], outdir, workdir) for i in range(0, len(rows), BATCH)]
    with ThreadPoolExecutor(WORKERS) as ex:
        results = [d for batch in ex.map(run_batch, jobs) for d in batch]
    res = pd.DataFrame(results).rename(columns={c: f"{c}_adj" for c in ["decision", "criterion", "subject",
                                                                        "reason"]})
    df.merge(res, on="id", how="left").to_csv(OUT / name / "adjudicated.csv", index=False, encoding="utf-8")
    print(f"{len(res)} of {len(rows)} records adjudicated")
    if len(res):
        print(res["decision_adj"].value_counts().to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["collect", "rescue", "run"])
    ap.add_argument("path")
    ap.add_argument("names", nargs="+")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if a.command == "rescue":
        rescue(a.path, a.names)
    elif a.command == "collect":
        collect(a.path, a.names)
    else:
        run(a.path, a.names[0], a.limit)
