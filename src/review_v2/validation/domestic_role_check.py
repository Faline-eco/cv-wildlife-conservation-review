"""Validation 5.7 (Reviewer 2): are domestic animals coded as targets really study subjects?

Usage: python src/review_v2/validation/domestic_role_check.py run      (one judge call per paper)
       python src/review_v2/validation/domestic_role_check.py report

Population: every eligible paper with at least one verified target taxon that is a domestic form (corpus/species,
domestic = True). A fresh headless call (claude-sonnet-5-5, not the extracting model) reads the paper and decides for
each such taxon whether the study analyses images of it as a subject ("subject"), whether it is only a class of a
generic or benchmark dataset used to test a general method ("benchmark_class"), whether it is only named in the text
("mentioned"), or "unclear". Report: share of domestic target codings confirmed as subjects, and the number of papers
that keep a domestic target after removing the rejected codings.
Output: validation/domestic_role/<paper>.json, validation/domestic_role.json
"""
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.fulltext.prepare import TEXT, paper_id, render  # noqa: E402
from review_v2.search.merge import ROOT  # noqa: E402
from review_v2.validation.stats import wilson  # noqa: E402

V2 = ROOT / "review_output" / "v2"
V = V2 / "validation"
OUT = V / "domestic_role"
MODEL = "claude-sonnet-5-5"

PROTOCOL = """You check the coding of a primary study on computer vision for animal monitoring. For each numbered \
animal taxon decide from the paper text how it appears in the study: "subject" if the study analyses images of \
this animal as one of the animals it is about (including domestic animals monitored next to wild ones, or as a \
case study); "benchmark_class" if the animal is only one of the classes of a generic or benchmark dataset (for \
example COCO, ImageNet, PASCAL VOC, CIFAR, Animals-10) used to test a general method; "mentioned" if it is only named \
in the text (introduction, related work, discussion) and not in the analysed images; "unclear" if the paper does not \
allow a decision. Reason in at most 15 words."""

SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "integer"},
                                     "verdict": {"type": "string",
                                                 "enum": ["subject", "benchmark_class", "mentioned", "unclear"]},
                                     "reason": {"type": "string"}},
    "required": ["id", "verdict", "reason"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False}


def population():
    p = pd.read_csv(V2 / "corpus" / "papers.csv")
    keep = set(p[p["eligible"]]["doi"])
    sp = pd.read_parquet(V2 / "corpus" / "species.parquet")
    sp = sp[sp["doi"].isin(keep) & sp["verified"] & (sp["role"] == "target") & sp["gbif_usageKey"].notna()]
    dom = sp[sp["domestic"]][["doi", "name", "gbif_canonicalName"]].drop_duplicates(["doi", "gbif_canonicalName"])
    return sp, dom


def call(text, items, workdir):
    lines = "\n".join(f"{i}. {x['name']} ({x['gbif_canonicalName']})" for i, x in enumerate(items))
    cmd = [shutil.which("claude"), "-p", "--model", MODEL, "--output-format", "json", "--system-prompt", PROTOCOL,
           "--json-schema", json.dumps(SCHEMA), "--tools", "", "--no-session-persistence"]
    res = subprocess.run(cmd, input=f"Taxa:\n{lines}\n\nPaper:\n{text}", capture_output=True, text=True,
                         encoding="utf-8", cwd=workdir, timeout=900)
    env = json.loads(res.stdout)
    if res.returncode != 0 or env.get("is_error"):
        raise RuntimeError(str(env.get("result"))[:300])
    out = env.get("structured_output") or json.loads(env["result"])
    return {x["id"]: x for x in out["items"]}, env.get("total_cost_usd") or 0


def run():
    _, dom = population()
    OUT.mkdir(parents=True, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="dom_")

    def one(doi):
        target = OUT / f"{paper_id(doi)}.json"
        if target.exists():
            return 0
        g = dom[dom["doi"] == doi].to_dict("records")
        text = render(json.loads((TEXT / f"{paper_id(doi)}.json").read_text(encoding="utf-8")))
        for _ in range(3):
            try:
                res, cost = call(text, g, workdir)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", doi, e, flush=True)
        else:
            return 0
        target.write_text(json.dumps({"doi": doi, "model": MODEL, "cost_usd": cost, "items": [
            {**x, **{k: res.get(i, {}).get(k) for k in ("verdict", "reason")}} for i, x in enumerate(g)]},
            indent=1, ensure_ascii=False), encoding="utf-8")
        return cost
    with ThreadPoolExecutor(4) as ex:
        cost = sum(ex.map(one, sorted(dom["doi"].unique())))
    print(f"checked {dom['doi'].nunique()} papers, {len(dom)} domestic target taxa, ${cost:.2f}")


def report():
    sp, dom = population()
    chk = pd.DataFrame([x for f in OUT.glob("*.json") for x in json.loads(f.read_text(encoding="utf-8"))["items"]])
    chk = chk[chk["doi"].isin(set(dom["doi"]))]
    counts = chk["verdict"].value_counts().to_dict()
    decided = chk[chk["verdict"] != "unclear"]
    wild = set(sp[~sp["domestic"]]["doi"])
    kept = set(chk[chk["verdict"].isin(["subject", "unclear"])]["doi"])
    res = {"papers": int(dom["doi"].nunique()), "taxa": len(dom), "checked": len(chk), "counts": counts,
           "subject": wilson(int((decided["verdict"] == "subject").sum()), len(decided)),
           "papers_with_wild_target": int(len(set(dom["doi"]) & wild)),
           "papers_domestic_after_check": len(kept),
           "papers_domestic_only_after_check": len(kept - wild),
           "by_taxon": {k: g["verdict"].value_counts().to_dict()
                        for k, g in chk.groupby("gbif_canonicalName") if len(g) >= 20}}
    (V / "domestic_role.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "by_taxon"}, indent=1, default=float))
    for k, v in res["by_taxon"].items():
        print(f"  {k:25s} {v}")


if __name__ == "__main__":
    {"run": run, "report": report}[sys.argv[1]]()
