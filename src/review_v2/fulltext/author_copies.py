"""Free author copies of papers without institutional access (mainly Springer book chapters).

Usage: python src/review_v2/fulltext/author_copies.py <dois.txt>

The publisher version is not used. For each DOI the title is searched in
  1. OpenAlex: other works with the same title (arXiv, repository or conference versions) that have an
     open-access PDF,
  2. Semantic Scholar: openAccessPdf of the DOI,
  3. arXiv: title search.
A candidate is kept only if the title matches (normalised, similarity >= 0.9) and the downloaded file is a
PDF of at least two pages whose first page contains the title words. Files go to <PDF_STORE>/pdf_direct/
(inventory.py picks them up); every DOI gets one line in fulltext/author_copies.jsonl.
"""
import argparse
import difflib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import pymupdf as fitz
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.fulltext.fetch_direct import PDF_DIR, UA, is_pdf  # noqa: E402
from review_v2.fulltext.prepare import OUT, paper_id  # noqa: E402
from review_v2.search.fetch import get, load_env  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

LOG = OUT / "author_copies.jsonl"
TA = ROOT / "review_output" / "v2" / "screening" / "ta_final.csv"


def norm(t):
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"<[^>]+>", "", str(t)).lower()).split()


def same_title(a, b):
    # numbers (years, editions) must agree: "LifeCLEF 2014" is not "LifeCLEF 2015"
    if {w for w in norm(a) if w.isdigit()} != {w for w in norm(b) if w.isdigit()}:
        return False
    return difflib.SequenceMatcher(None, " ".join(norm(a)), " ".join(norm(b))).ratio() >= 0.9


def openalex(doi, title):
    urls = []
    q = " ".join(norm(title)[:20])
    r = get("https://api.openalex.org/works", params={"search": q, "per-page": 10,
            "select": "doi,title,locations", "api_key": os.environ["OPENALEX_API_KEY"]})
    if r.status_code != 200:
        return urls
    for w in r.json()["results"]:
        if not same_title(title, w.get("title") or ""):
            continue
        for x in w.get("locations") or []:
            if x.get("is_oa") and x.get("pdf_url") and "springer" not in x["pdf_url"]:
                urls.append(("openalex", x["pdf_url"]))
    return urls


def semantic_scholar(doi):
    try:
        r = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                         params={"fields": "openAccessPdf,externalIds"}, headers=UA, timeout=60)
    except requests.exceptions.RequestException:
        return []
    if r.status_code != 200:
        return []
    j = r.json()
    urls = []
    arxiv = (j.get("externalIds") or {}).get("ArXiv")
    if arxiv:
        urls.append(("arxiv_s2", f"https://arxiv.org/pdf/{arxiv}"))
    u = (j.get("openAccessPdf") or {}).get("url")
    if u and "springer" not in u:
        urls.append(("s2_oa", u))
    return urls


def arxiv(title):
    words = [w for w in norm(title) if len(w) > 3][:10]
    if not words:
        return []
    q = " AND ".join(f"ti:{w}" for w in words)
    try:
        r = requests.get("https://export.arxiv.org/api/query", params={"search_query": q, "max_results": 5},
                         headers=UA, timeout=60)
    except requests.exceptions.RequestException:
        return []
    time.sleep(3)
    if r.status_code != 200:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    urls = []
    for e in ET.fromstring(r.content).findall("a:entry", ns):
        if same_title(title, e.findtext("a:title", "", ns)):
            urls.append(("arxiv", e.findtext("a:id", "", ns).replace("/abs/", "/pdf/")))
    return urls


def first_page_matches(content, title):
    try:
        text = " ".join(norm(fitz.open(stream=content, filetype="pdf")[0].get_text()[:3000]))
    except Exception:  # noqa: BLE001
        return False
    words = [w for w in norm(title) if len(w) > 3]
    return bool(words) and sum(w in text for w in words) / len(words) >= 0.8


def download(urls, title):
    tried = []
    for kind, url in dict.fromkeys(urls):
        try:
            r = requests.get(url, headers=UA, timeout=90, allow_redirects=True)
        except requests.exceptions.RequestException as e:
            tried.append(f"{kind}:{type(e).__name__}")
            continue
        if r.status_code == 200 and is_pdf(r.content) and first_page_matches(r.content, title):
            return r.content, kind, url, tried
        tried.append(f"{kind}:{r.status_code}")
        time.sleep(1)
    return None, None, None, tried


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dois")
    a = ap.parse_args()
    load_env()
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    titles = pd.read_csv(TA, low_memory=False).dropna(subset=["doi"])
    titles = dict(zip(titles["doi"].map(norm_doi), titles["title"]))
    done = set()
    if LOG.exists():
        done = {json.loads(x)["doi"] for x in LOG.read_text(encoding="utf-8").splitlines() if x}
    todo = [d for d in dict.fromkeys(map(norm_doi, Path(a.dois).read_text().split())) if d not in done]
    counts = {}
    with open(LOG, "a", encoding="utf-8") as log:
        for i, doi in enumerate(todo, 1):
            title = titles.get(doi) if isinstance(titles.get(doi), str) else ""
            if not title:
                r = get(f"https://api.openalex.org/works/https://doi.org/{doi}",
                        params={"select": "title", "api_key": os.environ["OPENALEX_API_KEY"]})
                title = (r.json().get("title") or "") if r.status_code == 200 else ""
            urls = openalex(doi, title) + semantic_scholar(doi) if title else []
            content, route, url, tried = download(urls, title) if urls else (None, None, None, [])
            if content is None and title:
                more = arxiv(title)
                if more:
                    content, route, url, more_tried = download(more, title)
                    tried += more_tried
            if content is not None:
                (PDF_DIR / f"{paper_id(doi)}.pdf").write_bytes(content)
            counts[route] = counts.get(route, 0) + 1
            log.write(json.dumps({"doi": doi, "route": route, "url": url, "tried": tried}) + "\n")
            log.flush()
            time.sleep(1)
            if i % 20 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}  {counts}", flush=True)
