"""PDFs that Zotero could not retrieve, fetched over sanctioned routes only.

Usage: python src/review_v2/fulltext/fetch_direct.py <dois.txt> [--limit N]

Routes, in this order:
  1. Elsevier article retrieval API for 10.1016 (works only if the key in .env.revision carries a
     full-text entitlement; on 2026-10-13 it did not: 403 "configuration settings insufficient")
  2. open-access copies listed by OpenAlex: Europe PMC, repositories, then the publisher's open PDF
A request that is refused (403, login page, captcha) is recorded and not retried in another way.

Output: <PDF_STORE>/pdf_direct/<paper_id>.pdf and direct_fetch.jsonl (one line per DOI).
inventory.py adds these files to zotero_pdfs.csv.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import pymupdf as fitz
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.fulltext.prepare import OUT, PDF_STORE, paper_id  # noqa: E402
from review_v2.search.fetch import get, load_env  # noqa: E402
from review_v2.search.merge import norm_doi  # noqa: E402

PDF_DIR = PDF_STORE / "pdf_direct"
LOG = OUT / "direct_fetch.jsonl"
UA = {"User-Agent": "LiteratureReviewCVinWC/2.0 (systematic review; open-access retrieval)"}


def is_pdf(content, min_pages=2):
    if not content.startswith(b"%PDF"):
        return False
    try:
        return fitz.open(stream=content, filetype="pdf").page_count >= min_pages
    except Exception:  # noqa: BLE001
        return False


def elsevier(doi):
    r = get(f"https://api.elsevier.com/content/article/doi/{doi}",
            headers={"X-ELS-APIKey": os.environ["SCOPUS_API_KEY"], "Accept": "application/pdf"})
    # without entitlement the API returns the first page only
    return (r.content, "elsevier_api") if r.status_code == 200 and is_pdf(r.content) else (None, None)


def openalex_locations(dois):
    r = get("https://api.openalex.org/works", params={
        "filter": "doi:" + "|".join("https://doi.org/" + d for d in dois), "per-page": 100,
        "select": "doi,ids,locations,open_access", "api_key": os.environ["OPENALEX_API_KEY"]})
    out = {}
    if r.status_code != 200:
        return out
    for w in r.json()["results"]:
        urls = []
        for x in w.get("locations") or []:
            m = re.search(r"/pmc/articles/(?:PMC)?(\d+)", x.get("landing_page_url") or "")
            if m:
                urls.append(("europepmc", "https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC"
                             + m.group(1) + "&blobtype=pdf"))
                break
        locs = [x for x in (w.get("locations") or []) if x.get("is_oa") and x.get("pdf_url")]
        locs.sort(key=lambda x: ((x.get("source") or {}).get("type") != "repository"))
        for x in locs:
            kind = "repository" if (x.get("source") or {}).get("type") == "repository" else "publisher_oa"
            urls.append((kind, x["pdf_url"]))
        out[norm_doi(w.get("doi"))] = urls
    return out


def open_access(urls):
    tried = []
    for kind, url in urls[:5]:
        try:
            r = requests.get(url, headers=UA, timeout=90, allow_redirects=True)
        except requests.exceptions.RequestException as e:
            tried.append(f"{kind}:{type(e).__name__}")
            continue
        if r.status_code == 200 and is_pdf(r.content):
            return r.content, kind, tried
        tried.append(f"{kind}:{r.status_code}")
    return None, None, tried


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dois")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    load_env()
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    done = set()
    if LOG.exists():
        done = {json.loads(line)["doi"] for line in LOG.read_text(encoding="utf-8").splitlines() if line}
    todo = [d for d in dict.fromkeys(map(norm_doi, Path(a.dois).read_text().split())) if d and d not in done]
    todo = todo[:a.limit] if a.limit else todo
    counts = {}
    with open(LOG, "a", encoding="utf-8") as log:
        for i in range(0, len(todo), 40):
            chunk = todo[i:i + 40]
            locations = openalex_locations([d for d in chunk if "," not in d and "|" not in d])
            for doi in chunk:
                content, route, tried = None, None, []
                if doi.startswith("10.1016/"):
                    content, route = elsevier(doi)
                if content is None:
                    content, route, tried = open_access(locations.get(doi, []))
                if content is not None:
                    (PDF_DIR / f"{paper_id(doi)}.pdf").write_bytes(content)
                counts[route] = counts.get(route, 0) + 1
                log.write(json.dumps({"doi": doi, "route": route, "tried": tried}) + "\n")
                log.flush()
                time.sleep(1)
            print(f"  {min(i + 40, len(todo))}/{len(todo)}  {counts}", flush=True)
