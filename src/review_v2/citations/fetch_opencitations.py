"""One-hop forward and backward citation search over the OpenCitations Index (API v2), as in the paper.

Usage: python src/review_v2/citations/fetch_opencitations.py <seed_dois.txt> <run_name>

Output: review_output/v2/citations/<run_name>/opencitations_edges.jsonl (resumable)
  {seed, direction: forward|backward, doi, openalex, year}   plus one {direction: done} line per seed
OpenCitations returns identifiers only; titles and abstracts are fetched separately.
"""
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.fetch import get  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

API = "https://api.opencitations.net/index/v2"


def parse(ids):
    doi = re.search(r"doi:(\S+)", ids)
    oa = re.search(r"openalex:(\S+)", ids)
    return (norm_doi(doi.group(1)) if doi else None), (oa.group(1) if oa else None)


def fetch(seed, direction):
    op, field = ("citations", "citing") if direction == "forward" else ("references", "cited")
    for attempt in range(5):                       # large responses sometimes break off mid-transfer
        try:
            r = get(f"{API}/{op}/doi:{seed}", headers={"Accept": "application/json"})
            break
        except requests.exceptions.RequestException:
            if attempt == 4:
                raise
            time.sleep(10)
    if r.status_code == 404 or not r.text.strip():
        return []
    r.raise_for_status()
    rows = []
    for c in r.json():
        doi, oa = parse(c[field])
        # creation = publication date of the citing work; unknown for the cited work in backward direction
        year = int(c["creation"][:4]) if direction == "forward" and c.get("creation") else None
        rows.append({"seed": seed, "direction": direction, "doi": doi, "openalex": oa, "year": year})
    return rows


if __name__ == "__main__":
    seed_file, run = sys.argv[1:3]
    out = ROOT / "review_output" / "v2" / "citations" / run / "opencitations_edges.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    seeds = list(dict.fromkeys(d for d in map(norm_doi, Path(seed_file).read_text().splitlines()) if d))
    done = set()
    if out.exists():
        done = {json.loads(line)["seed"] for line in out.read_text(encoding="utf-8").splitlines()
                if '"done"' in line}
    n_f = n_b = 0
    with open(out, "a", encoding="utf-8") as f:
        for i, seed in enumerate(seeds):
            if seed in done:
                continue
            rows = fetch(seed, "forward") + fetch(seed, "backward")
            n_f += sum(r["direction"] == "forward" for r in rows)
            n_b += sum(r["direction"] == "backward" for r in rows)
            for r in rows + [{"seed": seed, "direction": "done"}]:
                f.write(json.dumps(r) + "\n")
            f.flush()
            if i % 50 == 0:
                print(f"  {i}/{len(seeds)}  forward {n_f}  backward {n_b}", flush=True)
    print(f"finished: forward {n_f}, backward {n_b}")
