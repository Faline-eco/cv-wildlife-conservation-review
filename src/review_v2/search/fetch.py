"""Download the metadata records (title, abstract, DOI, year, venue) for the reference query
from Scopus, OpenAlex and PubMed. One JSONL file per source plus a retrieval log.

Usage: python src/review_v2/search/fetch.py [scopus] [openalex] [pubmed]
"""
import datetime as dt
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search import queries as q  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "review_output" / "v2" / "search"


def load_env():
    for line in (ROOT / ".env.revision").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def get(url, **kw):
    for attempt in range(6):
        r = requests.get(url, timeout=90, **kw)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        return r
    return r


def log(source, query, total, stored, note=""):
    entry = {
        "source": source, "query": query, "total_reported": total, "stored": stored,
        "executed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "note": note,
    }
    with open(OUT / "retrieval_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(entry)


def fetch_scopus():
    headers = {"X-ELS-APIKey": os.environ["SCOPUS_API_KEY"], "Accept": "application/json"}
    query = q.scopus_query()
    view, count = "COMPLETE", 25
    probe = get("https://api.elsevier.com/content/search/scopus", headers=headers,
                params={"query": query, "count": 1, "view": view})
    if probe.status_code != 200:
        view, count = "STANDARD", 200  # no subscriber entitlement: abstracts are filled later
    cursor, n, total = "*", 0, None
    with open(OUT / "scopus.jsonl", "w", encoding="utf-8") as f:
        while True:
            r = get("https://api.elsevier.com/content/search/scopus", headers=headers,
                    params={"query": query, "count": count, "view": view, "cursor": cursor})
            r.raise_for_status()
            res = r.json()["search-results"]
            total = int(res["opensearch:totalResults"])
            entries = [e for e in res.get("entry", []) if "error" not in e]
            if not entries:
                break
            for e in entries:
                f.write(json.dumps({
                    "source": "scopus",
                    "source_id": e.get("dc:identifier"),
                    "doi": e.get("prism:doi"),
                    "title": e.get("dc:title"),
                    "abstract": e.get("dc:description"),
                    "year": (e.get("prism:coverDate") or "")[:4],
                    "date": e.get("prism:coverDate"),
                    "venue": e.get("prism:publicationName"),
                    "doc_type": e.get("subtypeDescription"),
                    "keywords": e.get("authkeywords"),
                    "pubmed_id": e.get("pubmed-id"),
                }, ensure_ascii=False) + "\n")
            n += len(entries)
            nxt = res.get("cursor", {}).get("@next")
            if not nxt or nxt == cursor or n >= total:
                break
            cursor = nxt
    log("scopus", query, total, n, f"view={view}")


def _openalex_abstract(inv):
    if not inv:
        return None
    pos = [(i, w) for w, idx in inv.items() for i in idx]
    return " ".join(w for _, w in sorted(pos))


def fetch_openalex():
    flt = q.openalex_filter()
    cursor, n, total = "*", 0, None
    with open(OUT / "openalex.jsonl", "w", encoding="utf-8") as f:
        while cursor:
            r = get("https://api.openalex.org/works", params={
                "filter": flt, "per-page": 200, "cursor": cursor,
                "select": "id,doi,title,publication_year,publication_date,type,primary_location,"
                          "abstract_inverted_index,ids",
            })
            r.raise_for_status()
            js = r.json()
            total = js["meta"]["count"]
            for w in js["results"]:
                src = ((w.get("primary_location") or {}).get("source") or {})
                f.write(json.dumps({
                    "source": "openalex",
                    "source_id": w.get("id"),
                    "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
                    "title": w.get("title"),
                    "abstract": _openalex_abstract(w.get("abstract_inverted_index")),
                    "year": str(w.get("publication_year") or ""),
                    "date": w.get("publication_date"),
                    "venue": src.get("display_name"),
                    "doc_type": w.get("type"),
                    "keywords": None,
                    "pubmed_id": ((w.get("ids") or {}).get("pmid") or "").rsplit("/", 1)[-1] or None,
                }, ensure_ascii=False) + "\n")
            n += len(js["results"])
            cursor = js["meta"].get("next_cursor") if js["results"] else None
    log("openalex", flt, total, n)


def fetch_pubmed():
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    term = q.pubmed_query()
    es = get(base + "esearch.fcgi", params={"db": "pubmed", "term": term, "retmode": "json",
                                            "usehistory": "y", "retmax": 0}).json()["esearchresult"]
    total, n = int(es["count"]), 0
    with open(OUT / "pubmed.jsonl", "w", encoding="utf-8") as f:
        for start in range(0, total, 200):
            r = get(base + "efetch.fcgi", params={"db": "pubmed", "query_key": es["querykey"],
                                                  "WebEnv": es["webenv"], "retstart": start,
                                                  "retmax": 200, "retmode": "xml"})
            r.raise_for_status()
            for art in ET.fromstring(r.content).iter("PubmedArticle"):
                doi = next((i.text for i in art.iter("ArticleId") if i.get("IdType") == "doi"), None)
                abstract = " ".join("".join(a.itertext()) for a in art.iter("AbstractText")) or None
                title = art.find(".//ArticleTitle")
                year = art.find(".//JournalIssue/PubDate/Year")
                if year is None:
                    year = art.find(".//ArticleDate/Year")
                f.write(json.dumps({
                    "source": "pubmed",
                    "source_id": art.findtext(".//PMID"),
                    "doi": doi,
                    "title": "".join(title.itertext()) if title is not None else None,
                    "abstract": abstract,
                    "year": year.text if year is not None else "",
                    "date": None,
                    "venue": art.findtext(".//Journal/Title"),
                    "doc_type": "; ".join(t.text for t in art.iter("PublicationType") if t.text),
                    "keywords": " | ".join(k.text for k in art.iter("Keyword") if k.text) or None,
                    "pubmed_id": art.findtext(".//PMID"),
                }, ensure_ascii=False) + "\n")
                n += 1
            time.sleep(0.4)
    log("pubmed", term, total, n)


if __name__ == "__main__":
    load_env()
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[1:] or ["scopus", "openalex", "pubmed"]
    for name in wanted:
        {"scopus": fetch_scopus, "openalex": fetch_openalex, "pubmed": fetch_pubmed}[name]()
