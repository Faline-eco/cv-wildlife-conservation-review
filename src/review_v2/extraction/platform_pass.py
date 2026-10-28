"""Supplementary pass: imaging platform for study settings the main extraction coded "Not reported".

Usage: python src/review_v2/extraction/platform_pass.py run [<dois.txt>] [--model ID] [--workers N]
       python src/review_v2/extraction/platform_pass.py check      (independent judge on a sample of changed settings)

Added 2026-10-22 after the hallucination check (validation 5.3): a quarter of the sampled platform items were
"Not reported" although the paper names the platform, mostly when the study uses an existing dataset and states
how it was recorded, or describes its own device in the methods. The frozen main protocol is not changed; this pass
asks only about settings whose platform is "Not reported", with the same platform classes and the same rule that
only the paper text counts. Without a DOI list it runs on all eligible papers with such a setting.
One fresh headless call per paper on the prepared text; output in extraction/platform_v1/<paper_id>.json, with the
quote located by extraction/verify.py. corpus/tables.py replaces "Not reported" by the pass value when the quote is
verified (column platform_source).
"""
import argparse
import hashlib
import json
import random
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
from review_v2.extraction.schema import PLATFORMS  # noqa: E402
from review_v2.extraction.verify import locate, verified  # noqa: E402
from review_v2.fulltext.prepare import TEXT, paper_id, render  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

V2 = ROOT / "review_output" / "v2"
RUN = V2 / "extraction" / "corpus_v2_opus"
OUTDIR = V2 / "extraction" / "platform_v1"
NR = "Not reported"

PROTOCOL = """You code one detail of a primary study for a systematic mapping study on computer vision for animal \
monitoring and conservation. Decide from the paper text only.

The study's image data were split into settings (one combination of imaging platform, place and habitat). For the \
settings listed, an earlier coder found no imaging platform. Decide for each listed setting where the camera or \
sensor that recorded the analysed images was carried or mounted, using these classes:
- "Camera Trap": motion- or time-triggered cameras left in the field (trail cameras, camera traps).
- "Non-specialized Camera": a handheld, tripod, fixed, smartphone or ordinary video camera; also cameras fixed \
above a tank, pen or enclosure, and underwater cameras held by divers.
- "Unmanned aerial vehicle (UAV; e.g. drone)", "Crewed aerial vehicle (CAV; e.g. plane, helicopter)", "Satellite".
- "Remotely operated underwater vehicle (ROV)", "Autonomous Underwater Vehicle (AUV)", "Stationary underwater \
camera" (fixed or baited underwater cameras, cabled observatories), "Ground Robot" (robots on land only; an \
underwater robot is an ROV or AUV), "Animal-mounted Camera", "Depth Sensor / Lidar".
- "Web / citizen-science images": images collected from the internet, image search, social media or platforms \
such as iNaturalist, Flickr, eBird.
- "Other": a platform that fits none of these (e.g. a microscope, a conveyor-belt or fishing-vessel camera, sonar).
- "Not reported": the paper does not say how the images were taken.
Count what the paper itself states about the data it analyses, including what it says about an existing dataset \
(e.g. "the dataset contains camera-trap images"). Do not use outside knowledge about a named dataset. A platform \
mentioned only as a future application, or only for cited work, does not count. Do not infer a platform: "aerial \
images" without the vehicle, "underwater images", "wild" or "unconstrained" images, or a benchmark name alone are \
"Not reported"; a benchmark counts as "Web / citizen-science images" only if the paper says its images come from \
the internet or such a platform. Give exactly one entry per listed setting, with a verbatim quote of at most 30 \
words that itself names the platform or the image source (empty for "Not reported"), the page number from the \
<<page N>> markers, and a reason of at most 20 words."""

SCHEMA = {"type": "object", "properties": {"settings": {"type": "array", "items": {
    "type": "object", "properties": {"setting": {"type": "integer"},
                                     "platform": {"type": "string", "enum": PLATFORMS},
                                     "quote": {"type": "string"}, "page": {"type": "integer"},
                                     "reason": {"type": "string"}},
    "required": ["setting", "platform", "quote", "page", "reason"], "additionalProperties": False}}},
    "required": ["settings"], "additionalProperties": False}


def prompt_hash(model):
    return hashlib.sha256((PROTOCOL + json.dumps(SCHEMA, sort_keys=True) + model).encode()).hexdigest()[:12]


def record(doi):
    f = RUN / f"{paper_id(doi)}.json"
    return json.loads(f.read_text(encoding="utf-8")).get("record") if f.exists() else None


def open_settings(rec):
    return [(i, s) for i, s in enumerate(rec["settings"]) if s["platform"] == NR]


def describe(rec):
    lines = []
    for i, s in open_settings(rec):
        lines.append(f"Setting {i}: habitat {s['habitat']}; place {s['location_detail'] or '-'}; countries "
                     f"{', '.join(s['countries']) or '-'}; species {', '.join(s['species'][:8]) or '-'}")
    names = [d["name"] for d in rec["datasets"]]
    return "\n".join(lines) + (f"\nDatasets named by the coder: {'; '.join(names)}" if names else "")


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
    doi, model, workdir = args
    target = OUTDIR / f"{paper_id(doi)}.json"
    if target.exists():
        return "cached"
    rec = record(doi)
    if not rec or not open_settings(rec):
        return "nothing_open"
    src = TEXT / f"{paper_id(doi)}.json"
    if not src.exists():
        return "no_text"
    paper = json.loads(src.read_text(encoding="utf-8"))
    prompt = f"Settings without a platform:\n{describe(rec)}\n\nPaper:\n{render(paper)}"
    for _ in range(3):
        try:
            out, cost = call(model, prompt, workdir)
            break
        except Exception as e:  # noqa: BLE001
            print("retry", doi, str(e)[:120], flush=True)
            time.sleep(900 if "limit" in str(e).lower() or "overloaded" in str(e).lower() else 5)
    else:
        return "failed"
    wanted = {i for i, _ in open_settings(rec)}
    first = {}
    for s in out["settings"]:
        if s["setting"] in wanted:
            first.setdefault(s["setting"], {**s, "evidence": locate(s["quote"], s["page"], paper)})
    rows = list(first.values())
    target.write_text(json.dumps({"doi": doi, "model": model, "prompt_hash": prompt_hash(model), "cost_usd": cost,
                                  "coded_at": datetime.now(timezone.utc).isoformat(), "settings": rows},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    return "ok"


def default_dois():
    p = pd.read_csv(V2 / "corpus" / "papers.csv")
    return [d for d in p.loc[p["eligible"], "doi"] if (r := record(d)) and open_settings(r)]


def results():
    """{(doi, setting): (platform, verified)} for settings the pass coded with a platform.

    "Other" is not used: in the check (60 changed settings, 2026-10-22) 4 of 6 such values were unsupported
    (documentary footage, a sonar dataset, a web shop); the rest had 5 of 54 unsupported."""
    res = {}
    for f in OUTDIR.glob("*.json"):
        j = json.loads(f.read_text(encoding="utf-8"))
        for s in j["settings"]:
            if s["platform"] not in (NR, "Other"):
                res[(norm_doi(j["doi"]), s["setting"])] = (s["platform"], verified(s["evidence"]))
    return res


def run(a):
    OUTDIR.mkdir(parents=True, exist_ok=True)
    dois = (list(dict.fromkeys(d for d in map(norm_doi, Path(a.dois).read_text().split()) if d)) if a.dois
            else default_dois())
    print(len(dois), "papers", flush=True)
    workdir = tempfile.mkdtemp(prefix="platform_")
    with ThreadPoolExecutor(a.workers) as ex:
        status = list(ex.map(run_one, [(d, a.model, workdir) for d in dois]))
    cost = sum(json.loads(f.read_text(encoding="utf-8"))["cost_usd"] or 0 for f in OUTDIR.glob("*.json"))
    print({s: status.count(s) for s in sorted(set(status))}, f"total ${cost:.2f}")
    res = results()
    print("settings with a platform now:", len(res), "verified:", sum(v for _, v in res.values()))
    print(pd.Series([p for p, v in res.values() if v]).value_counts().to_string())


def check(a):
    """Independent judge (hallucination.py protocol) on 60 changed, verified settings."""
    from review_v2.validation import hallucination as h
    from review_v2.validation.stats import wilson
    rows = [{"doi": d, "setting": i, "field": "platform", "value": p} for (d, i), (p, v) in results().items() if v]
    rng = random.Random(20261022)
    sample = rng.sample(sorted(rows, key=lambda x: (x["doi"], x["setting"])), min(60, len(rows)))
    for x in sample:
        s = next(s for s in json.loads((OUTDIR / f"{paper_id(x['doi'])}.json").read_text(encoding="utf-8"))
                 ["settings"] if s["setting"] == x["setting"])
        x.update(quote=s["quote"], page=s["page"])
    out = OUTDIR.parent / "platform_check.json"
    done = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    workdir = tempfile.mkdtemp(prefix="platform_check_")

    def one(doi):
        if doi in done:
            return 0
        g = [x for x in sample if x["doi"] == doi]
        text = render(json.loads((TEXT / f"{paper_id(doi)}.json").read_text(encoding="utf-8")))
        res, cost = h.call(text, g, workdir)
        done[doi] = [{**x, **{k: res.get(i, {}).get(k) for k in ("verdict", "reason")}} for i, x in enumerate(g)]
        return cost
    with ThreadPoolExecutor(4) as ex:
        cost = sum(ex.map(one, sorted({x["doi"] for x in sample})))
    out.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
    v = [x["verdict"] for g in done.values() for x in g]
    print(f"judge ${cost:.2f}:", {k: v.count(k) for k in set(v)},
          "unsupported", wilson(v.count("unsupported"), len(v)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "check"])
    ap.add_argument("dois", nargs="?")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    {"run": run, "check": check}[a.cmd](a)
