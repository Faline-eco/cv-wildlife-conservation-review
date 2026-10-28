"""One-hop forward and backward citation search over OpenAlex.

Usage: python src/review_v2/citations/fetch_citations.py <seed_dois.txt> <run_name>
(works already stored by another run in citations/*/works.jsonl are not fetched again)

Output in review_output/v2/citations/<run_name>/ (resumable):
  seeds.jsonl     seed DOI -> OpenAlex id, reference list, citation count
  edges.jsonl     {seed, direction: forward|backward, work: OpenAlex id}
  works.jsonl     metadata of every candidate work (title, abstract, year, venue, type, DOI)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import os

from review_v2.search.fetch import _openalex_abstract, load_env  # noqa: E402
from review_v2.search.fetch import get as _get  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402
from review_v2.search.queries import YEAR_FROM, YEAR_TO  # noqa: E402

API = "https://api.openalex.org/works"
SELECT = "id,doi,title,publication_year,type,language,primary_location,abstract_inverted_index"
WINDOW = f"publication_year:{YEAR_FROM}-{YEAR_TO}"


def get(url, params):
    """OpenAlex request; uses OPENALEX_API_KEY from .env.revision if present (own daily budget)."""
    if os.environ.get("OPENALEX_API_KEY"):
        params = {**params, "api_key": os.environ["OPENALEX_API_KEY"]}
    return _get(url, params=params)


def short(oid):
    return oid.rsplit("/", 1)[-1]


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def work_row(w):
    src = ((w.get("primary_location") or {}).get("source") or {})
    return {"id": short(w["id"]), "doi": norm_doi(w.get("doi")), "title": w.get("title"),
            "abstract": _openalex_abstract(w.get("abstract_inverted_index")),
            "year": w.get("publication_year"), "venue": src.get("display_name"),
            "doc_type": w.get("type"), "language": w.get("language")}


def resolve_seeds(dois, out):
    done = {s["doi"] for s in read_jsonl(out)}
    todo = [d for d in dois if d not in done and "," not in d and "|" not in d]
    with open(out, "a", encoding="utf-8") as f:
        for i in range(0, len(todo), 40):
            chunk = todo[i:i + 40]
            r = get(API, {"filter": "doi:" + "|".join("https://doi.org/" + d for d in chunk),
                                 "per-page": 100, "select": "id,doi,referenced_works,cited_by_count"})
            r.raise_for_status()
            found = {norm_doi(w.get("doi")): w for w in r.json()["results"]}
            for d in chunk:
                w = found.get(d)
                f.write(json.dumps({"doi": d, "id": short(w["id"]) if w else None,
                                    "refs": [short(x) for x in w["referenced_works"]] if w else [],
                                    "cited_by": w["cited_by_count"] if w else 0}) + "\n")
    return read_jsonl(out)


def forward(seeds, edges_path, works_path, known):
    done = {e["seed"] for e in read_jsonl(edges_path) if e["direction"] in ("forward", "forward_done")}
    with open(edges_path, "a", encoding="utf-8") as fe, open(works_path, "a", encoding="utf-8") as fw:
        for n, s in enumerate(seeds):
            if s["id"] is None or s["doi"] in done:
                continue
            cursor = "*"
            while cursor:
                r = get(API, {"filter": f"cites:{s['id']},{WINDOW}", "per-page": 200,
                                     "cursor": cursor, "select": SELECT})
                r.raise_for_status()
                js = r.json()
                for w in js["results"]:
                    row = work_row(w)
                    fe.write(json.dumps({"seed": s["doi"], "direction": "forward", "work": row["id"]}) + "\n")
                    if row["id"] not in known:
                        known.add(row["id"])
                        fw.write(json.dumps(row, ensure_ascii=False) + "\n")
                cursor = js["meta"].get("next_cursor") if js["results"] else None
            fe.write(json.dumps({"seed": s["doi"], "direction": "forward_done", "work": None}) + "\n")
            fe.flush()
            fw.flush()
            if n % 100 == 0:
                print(f"  forward {n}/{len(seeds)}", flush=True)


def backward(seeds, edges_path, works_path, known):
    have_edges = {e["seed"] for e in read_jsonl(edges_path) if e["direction"] == "backward"}
    with open(edges_path, "a", encoding="utf-8") as fe:
        for s in seeds:
            if s["doi"] not in have_edges:
                for ref in s["refs"]:
                    fe.write(json.dumps({"seed": s["doi"], "direction": "backward", "work": ref}) + "\n")
    todo = sorted({ref for s in seeds for ref in s["refs"]} - known)
    with open(works_path, "a", encoding="utf-8") as fw:
        for i in range(0, len(todo), 50):
            # works outside the year window are stored as stubs so that they are not asked for again
            chunk = todo[i:i + 50]
            r = get(API, {"filter": "openalex:" + "|".join(chunk) + "," + WINDOW, "per-page": 100,
                                 "select": SELECT})
            r.raise_for_status()
            got = {short(w["id"]): work_row(w) for w in r.json()["results"]}
            for wid in chunk:
                fw.write(json.dumps(got.get(wid, {"id": wid, "out_of_window": True}), ensure_ascii=False) + "\n")
            fw.flush()
            if (i // 50) % 50 == 0:
                print(f"  backward {i}/{len(todo)}", flush=True)


if __name__ == "__main__":
    load_env()
    seed_file, run = sys.argv[1:3]
    out = ROOT / "review_output" / "v2" / "citations" / run
    out.mkdir(parents=True, exist_ok=True)
    dois = list(dict.fromkeys(d for d in map(norm_doi, Path(seed_file).read_text().splitlines()) if d))
    seeds = resolve_seeds(dois, out / "seeds.jsonl")
    print(f"{len(seeds)} seeds, {sum(s['id'] is not None for s in seeds)} found in OpenAlex, "
          f"{sum(len(s['refs']) for s in seeds)} references, {sum(s['cited_by'] for s in seeds)} citations")
    # works stored by earlier runs (e.g. hop1) are not fetched again; candidates are read from all runs
    known = {w["id"] for p in out.parent.glob("*/works.jsonl") for w in read_jsonl(p)}
    forward(seeds, out / "edges.jsonl", out / "works.jsonl", known)
    backward(seeds, out / "edges.jsonl", out / "works.jsonl", known)
    print("works stored:", len(read_jsonl(out / "works.jsonl")))
