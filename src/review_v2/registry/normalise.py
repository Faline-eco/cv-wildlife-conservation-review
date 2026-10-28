"""Canonical names and families for algorithms and datasets (no external registry covers them).

Usage: python src/review_v2/registry/normalise.py algorithms|datasets [--model ID] [--batch N] [--workers N]

Names are first collapsed by a key (lower case, letters and digits only: "ResNet-50" = "ResNet50"). The distinct
keys, sorted alphabetically so that variants of one name land in the same batch, go to the LLM, which returns the
canonical name and the family. Pure string rules cannot do this ("Faster-RCNN" vs "FRCNN", "MS COCO" vs
"Microsoft COCO", "URPC2019" vs "URPC 2019 dataset"). Output: registry/<kind>.json {key: {canonical, family, ...}}.
Only eligible papers. Datasets coded as "collected_by_authors" are not sent; they are counted as own data.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

RUN = ROOT / "review_output" / "v2" / "extraction" / "corpus_v2_opus"
DIR = ROOT / "review_output" / "v2" / "registry"

PROTOCOL = {
    "algorithms": """You normalise names of computer-vision and machine-learning methods extracted from papers \
on animal monitoring. For each entry return:
- "canonical": the standard name of the method with its version but without model size or training variant \
("YOLOv8n" -> YOLOv8, "yolo v5s" -> YOLOv5, "ResNet-50" -> ResNet-50, "resnet50" -> ResNet-50, "Faster-RCNN" -> \
Faster R-CNN, "Swin-T" -> Swin Transformer, "ViT-B/16" -> ViT, "MegaDetector v5a" -> MegaDetector v5). Keep the \
author's own named method as written when it is a new named model.
- "family": the model line without version or depth: YOLO, ResNet, VGG, Faster R-CNN, Mask R-CNN, SSD, RetinaNet, \
DETR, EfficientNet, EfficientDet, MobileNet, DenseNet, Inception, Xception, U-Net, DeepLab, ViT, Swin Transformer, \
ConvNeXt, CLIP, SAM, DINO, MegaDetector, SVM, Random Forest, k-means, HOG, SIFT, background subtraction, CNN \
(generic or custom CNN), Transformer (generic), etc. Use these spellings when they apply; otherwise a short \
standard family name. For an author's own new model, use the family of its base architecture if the name shows it \
("YOLO-Fish" -> YOLO), else "own model".
- "generic": true when the entry names only a generic technique class without a specific method ("CNN", \
"deep learning", "neural network", "transfer learning", "data augmentation").""",
    "datasets": """You normalise names of image datasets extracted from papers on animal monitoring. For each \
entry return:
- "canonical": the standard name of the dataset with its edition or year when it identifies a distinct release \
("URPC2019" -> URPC 2019, "MS COCO" / "Microsoft COCO" / "COCO 2017" -> COCO, "ImageNet-1k" / "ILSVRC 2012" -> \
ImageNet, "iWildCam 2020" -> iWildCam 2020, "Snapshot Serengeti season 1-6" -> Snapshot Serengeti).
- "family": the dataset series without edition (URPC, COCO, ImageNet, iWildCam, iNaturalist, Snapshot Safari \
for all Snapshot projects, LILA camera-trap collections keep their own names, Fish4Knowledge, FathomNet, ...).
- "generic": true when the entry is not a named dataset ("own images", "Google images", "unnamed field data", \
"images from the internet").""",
}

SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "integer"}, "canonical": {"type": "string"},
                                     "family": {"type": "string"}, "generic": {"type": "boolean"}},
    "required": ["id", "canonical", "family", "generic"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False}


def key(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def names(kind):
    """Distinct keys of the eligible papers (corpus/papers.csv), each with its most frequent spelling."""
    eligible = set(pd.read_csv(ROOT / "review_output" / "v2" / "corpus" / "papers.csv").query("eligible")["doi"])
    c, example = Counter(), {}
    for f in RUN.glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        if norm_doi(r["doi"]) not in eligible:
            continue
        for x in (r.get("record") or {}).get(kind, []):
            if kind == "datasets" and x["role"] == "collected_by_authors":
                continue
            k = key(x["name"])
            if k:
                c[k] += 1
                example.setdefault(k, Counter())[x["name"]] += 1
    return {k: example[k].most_common(1)[0][0] for k in c}


def call(kind, model, entries, workdir):
    text = "\n".join(f"{i}\t{e}" for i, e in enumerate(entries))
    cmd = [shutil.which("claude"), "-p", "--model", model, "--output-format", "json", "--system-prompt",
           PROTOCOL[kind] + "\nReturn every entry with its id.", "--json-schema", json.dumps(SCHEMA), "--tools", "",
           "--no-session-persistence"]
    res = subprocess.run(cmd, input="Entries (id<TAB>name):\n" + text, capture_output=True, text=True,
                         encoding="utf-8", cwd=workdir, timeout=1800)
    env = json.loads(res.stdout)
    if res.returncode != 0 or env.get("is_error"):
        raise RuntimeError(str(env.get("result"))[:400])
    out = env.get("structured_output") or json.loads(env["result"])
    return {x["id"]: x for x in out["items"]}, env.get("total_cost_usd") or 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=list(PROTOCOL))
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--batch", type=int, default=150)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    DIR.mkdir(parents=True, exist_ok=True)
    out_file = DIR / f"{a.kind}.json"
    reg = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
    ex_names = names(a.kind)
    todo = sorted(k for k in ex_names if k not in reg)
    chunks = [todo[i:i + a.batch] for i in range(0, len(todo), a.batch)]
    workdir = tempfile.mkdtemp(prefix="registry_")
    cost = 0

    def run(chunk):
        for _ in range(3):
            try:
                res, c = call(a.kind, a.model, [ex_names[k] for k in chunk], workdir)
                return {k: {"name": ex_names[k], **{f: res[i][f] for f in ("canonical", "family", "generic")}}
                        for i, k in enumerate(chunk) if i in res}, c
            except Exception as e:  # noqa: BLE001
                print("retry:", e, flush=True)
        return {}, 0
    print(f"{len(ex_names)} keys, {len(todo)} to do in {len(chunks)} batches", flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        for i, (res, c) in enumerate(ex.map(run, chunks)):
            reg.update(res)
            cost += c
            out_file.write_text(json.dumps(reg, ensure_ascii=False, indent=0), encoding="utf-8")
            print(f"  batch {i + 1}/{len(chunks)}  {len(reg)} keys  ${cost:.2f}", flush=True)
