"""All species items of the coded records as a flat table (one row per item and scientific name part)."""
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

RUN = ROOT / "review_output" / "v2" / "extraction" / "corpus_v2_opus"


def split_sci(s):
    """'Cormorants: Phalacrocorax carbo, Microcarbo pygmaeus' -> two names; drops authors in brackets."""
    s = re.sub(r"\([^)]*\)", " ", s or "")
    parts = re.split(r"[,;/]|\band\b|\s&\s", s)
    out = []
    for p in parts:
        p = re.sub(r"\b(spp?|ssp|subsp|var|cf|aff)\.?(?=\s|$)", " ", p)
        p = re.sub(r"\s+", " ", p).strip(" .")
        w = p.split(" ")
        p = " ".join([w[0].capitalize()] + [x.lower() for x in w[1:]])  # "Chromis Chrysura" -> "Chromis chrysura"
        if len(p) > 2 and re.match(r"^[A-Z][a-z]+(\s[a-z][a-z-]+){0,2}$", p):
            out.append(p)
    return out


def common_key(name):
    return re.sub(r"\s+", " ", (name or "").lower().strip())


def load():
    rows = []
    for f in sorted(RUN.glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        if "record" not in r:
            continue
        for i, s in enumerate(r["record"]["species"]):
            sci = split_sci(s["scientific_name"])
            base = {"doi": norm_doi(r["doi"]), "item": i, "name": s["name"], "scientific_name": s["scientific_name"],
                    "rank": s["rank"], "role": s["role"], "domestic": s["domestic"], "n_taxa": s["n_taxa"],
                    "evidence": s["evidence"]["status"]}
            for part in sci or [None]:
                rows.append({**base, "sci": part})
    return pd.DataFrame(rows)
