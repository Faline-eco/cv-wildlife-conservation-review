"""Title, abstract, year and venue for a list of DOIs (OpenAlex, then Scopus for the gaps).

Usage: python src/review_v2/search/fetch_by_doi.py <name>
  reads  review_output/v2/search/<name>_dois.txt   (one DOI per line)
  writes review_output/v2/search/<name>_meta.jsonl (resumable)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.fetch import OUT, _openalex_abstract, get, load_env  # noqa: E402
from review_v2.search.merge import norm_doi  # noqa: E402


def openalex_batch(dois):
    r = get("https://api.openalex.org/works", params={
        "filter": "doi:" + "|".join("https://doi.org/" + d for d in dois), "per-page": 100,
        "select": "id,doi,title,publication_year,type,primary_location,abstract_inverted_index,language",
    })
    out = {}
    if r.status_code != 200:
        return out
    for w in r.json()["results"]:
        doi = norm_doi(w.get("doi"))
        src = ((w.get("primary_location") or {}).get("source") or {})
        out[doi] = {
            "doi": doi, "title": w.get("title"),
            "abstract": _openalex_abstract(w.get("abstract_inverted_index")),
            "year": w.get("publication_year"), "venue": src.get("display_name"),
            "doc_type": w.get("type"), "language": w.get("language"), "meta_source": "openalex",
        }
    return out


def scopus_one(doi):
    r = get("https://api.elsevier.com/content/search/scopus",
            headers={"X-ELS-APIKey": os.environ["SCOPUS_API_KEY"], "Accept": "application/json"},
            params={"query": f"DOI({doi})", "count": 1, "view": "COMPLETE"})
    if r.status_code != 200:
        return None
    e = (r.json()["search-results"].get("entry") or [{}])[0]
    if "error" in e or not e.get("dc:title"):
        return None
    return {"doi": doi, "title": e.get("dc:title"), "abstract": e.get("dc:description"),
            "year": (e.get("prism:coverDate") or "")[:4], "venue": e.get("prism:publicationName"),
            "doc_type": e.get("subtypeDescription"), "language": None, "meta_source": "scopus"}


if __name__ == "__main__":
    load_env()
    name = sys.argv[1]
    dois = [d for d in map(norm_doi, (OUT / f"{name}_dois.txt").read_text().splitlines()) if d]
    dois = list(dict.fromkeys(dois))
    target = OUT / f"{name}_meta.jsonl"
    done = set()
    if target.exists():
        done = {json.loads(line)["doi"] for line in target.read_text(encoding="utf-8").splitlines() if line}
    todo = [d for d in dois if d not in done]
    print(f"{len(dois)} DOIs, {len(done)} done, {len(todo)} to fetch")
    with open(target, "a", encoding="utf-8") as f:
        for i in range(0, len(todo), 40):
            chunk = [d for d in todo[i:i + 40] if "," not in d and "|" not in d]
            found = openalex_batch(chunk)
            for d in todo[i:i + 40]:
                rec = found.get(d)
                if rec is None or not rec.get("abstract"):
                    rec = scopus_one(d) or rec
                if rec is None:
                    rec = {"doi": d, "title": None, "abstract": None, "year": None, "venue": None,
                           "doc_type": None, "language": None, "meta_source": None}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if (i // 40) % 10 == 0:
                print(f"  {min(i + 40, len(todo))}/{len(todo)}")
