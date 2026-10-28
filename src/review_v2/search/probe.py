"""Hit counts per index and year for the reference query. No records are stored."""
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search import queries as q  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


def load_env():
    for line in (ROOT / ".env.revision").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def scopus_count(y0, y1):
    r = requests.get(
        "https://api.elsevier.com/content/search/scopus",
        params={"query": q.scopus_query(y0, y1), "count": 1},
        headers={"X-ELS-APIKey": os.environ["SCOPUS_API_KEY"], "Accept": "application/json"},
        timeout=60,
    )
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:300]}"
    return int(r.json()["search-results"]["opensearch:totalResults"])


def openalex_count(y0, y1):
    r = requests.get(
        "https://api.openalex.org/works",
        params={"filter": q.openalex_filter(y0, y1), "per-page": 1},
        timeout=60,
    )
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:300]}"
    return r.json()["meta"]["count"]


def pubmed_count(y0, y1):
    r = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={"db": "pubmed", "term": q.pubmed_query(y0, y1), "retmode": "json", "retmax": 0},
        timeout=60,
    )
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:300]}"
    return int(r.json()["esearchresult"]["count"])


if __name__ == "__main__":
    load_env()
    print("query:", q.boolean_query())
    print(f"{'years':<12}{'scopus':>10}{'openalex':>10}{'pubmed':>10}")
    spans = [(2014, 2026)] + [(y, y) for y in range(2014, 2027)]
    for y0, y1 in spans:
        label = f"{y0}-{y1}" if y0 != y1 else str(y0)
        print(f"{label:<12}{scopus_count(y0, y1)!s:>10}{openalex_count(y0, y1)!s:>10}{pubmed_count(y0, y1)!s:>10}")
