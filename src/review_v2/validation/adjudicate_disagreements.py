"""Validation 5.2, second step: who is right where extraction and manual coding disagree?

Usage: python src/review_v2/validation/adjudicate_disagreements.py run      (one judge call per paper)
       python src/review_v2/validation/adjudicate_disagreements.py report

Input: validation/extraction_agreement_items.csv (values coded only by the extraction or only manually).
A fresh headless call (claude-sonnet-5-5, not the extracting model) reads the paper and decides for each disputed
value whether it is correct for the study itself. Classes:
  auto_only  + correct   -> omission in the manual coding      auto_only  + wrong -> extraction error (false pos.)
  manual_only + correct  -> extraction omission (false neg.)    manual_only + wrong -> manual coding error
Values coded by both are taken as correct. Report: precision and recall of extraction and manual coding against
the adjudicated reference, per field. The human check of the judge is part of the hallucination sheet.
"""
import ast
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
from review_v2.validation.stats import bootstrap_prf  # noqa: E402

V = ROOT / "review_output" / "v2" / "validation"
OUT = V / "adjudication"
MODEL = "claude-sonnet-5-5"
FIELDS = {"platform": "imaging platform", "habitat": "IUCN habitat (level 1) where the images were recorded",
          "spectrum": "light spectrum / sensing modality of the analysed images",
          "country": "country where the analysed images were recorded", "task": "primary computer-vision task",
          "taxon_species": "species studied (target of the analysis)",
          "taxon_genus": "genus of a studied species", "taxon_class": "taxonomic class of the studied animals",
          "algorithm": "computer-vision / ML method family used, proposed or compared",
          "own_data": "the authors collected their own image data ('yes')",
          "public_dataset": "the study uses a public, named dataset ('yes')"}

PROTOCOL = """You adjudicate between two codings of a primary study on computer vision for animal monitoring. For \
each numbered value decide from the paper text whether it is correct for the study itself (not for cited work \
only): "correct", "wrong", or "unclear" if the paper does not allow a decision. Habitats follow the IUCN level-1 \
classes; "Artificial Terrestrial/Aquatic" means human-made environments (farms, cities, zoos, aquaculture). A \
taxon is correct if animals of that taxon are analysed in the study's images. Reason in at most 15 words."""

SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "integer"},
                                     "verdict": {"type": "string", "enum": ["correct", "wrong", "unclear"]},
                                     "reason": {"type": "string"}},
    "required": ["id", "verdict", "reason"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False}


def disputes():
    d = pd.read_csv(V / "extraction_agreement_items.csv")
    rows = []
    for r in d.itertuples():
        for side in ("auto_only", "manual_only"):
            for v in ast.literal_eval(getattr(r, side)):
                rows.append({"doi": r.doi, "field": r.field, "value": v, "side": side})
    return pd.DataFrame(rows)


def call(text, items, workdir):
    lines = "\n".join(f"{i}. {FIELDS[x['field']]}: {x['value']}" for i, x in enumerate(items))
    cmd = [shutil.which("claude"), "-p", "--model", MODEL, "--output-format", "json", "--system-prompt", PROTOCOL,
           "--json-schema", json.dumps(SCHEMA), "--tools", "", "--no-session-persistence"]
    res = subprocess.run(cmd, input=f"Values:\n{lines}\n\nPaper:\n{text}", capture_output=True, text=True,
                         encoding="utf-8", cwd=workdir, timeout=900)
    env = json.loads(res.stdout)
    if res.returncode != 0 or env.get("is_error"):
        raise RuntimeError(str(env.get("result"))[:300])
    out = env.get("structured_output") or json.loads(env["result"])
    return {x["id"]: x for x in out["items"]}, env.get("total_cost_usd") or 0


def run():
    df = disputes()
    OUT.mkdir(parents=True, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="adj_")

    def one(doi):
        target = OUT / f"{paper_id(doi)}.json"
        if target.exists():
            return 0
        g = df[df["doi"] == doi].to_dict("records")
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
        cost = sum(ex.map(one, sorted(df["doi"].unique())))
    print(f"adjudicated {df['doi'].nunique()} papers, ${cost:.2f}")


def report():
    adj = pd.DataFrame([x for f in OUT.glob("*.json") for x in json.loads(f.read_text(encoding="utf-8"))["items"]])
    d = pd.read_csv(V / "extraction_agreement_items.csv")
    print(pd.crosstab([adj["field"], adj["side"]], adj["verdict"]).to_string())
    res = {}
    for field, g in d.groupby("field"):
        a = adj[adj["field"] == field]
        auto, man = [], []
        for r in g.itertuples():
            x = a[a["doi"] == r.doi]
            both = len(ast.literal_eval(r.both))
            ao_ok = int(((x["side"] == "auto_only") & (x["verdict"] == "correct")).sum())
            ao_bad = int(((x["side"] == "auto_only") & (x["verdict"] == "wrong")).sum())
            mo_ok = int(((x["side"] == "manual_only") & (x["verdict"] == "correct")).sum())
            mo_bad = int(((x["side"] == "manual_only") & (x["verdict"] == "wrong")).sum())
            auto.append((both + ao_ok, ao_bad, mo_ok))      # extraction vs adjudicated reference
            man.append((both + mo_ok, mo_bad, ao_ok))       # manual coding vs adjudicated reference
        res[field] = {"extraction": bootstrap_prf(auto), "manual": bootstrap_prf(man),
                      "unclear": int((a["verdict"] == "unclear").sum())}
    (V / "extraction_adjudicated.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    for field, r in res.items():
        e, m = r["extraction"], r["manual"]
        print(f"  {field:15s} extraction P {e['precision']['p']:.3f} R {e['recall']['p']:.3f} F1 {e['f1']['p']:.3f}"
              f" | manual P {m['precision']['p']:.3f} R {m['recall']['p']:.3f} F1 {m['f1']['p']:.3f}"
              f" | unclear {r['unclear']}")


if __name__ == "__main__":
    {"run": run, "report": report}[sys.argv[1]]()
