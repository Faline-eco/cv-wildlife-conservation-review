"""PDFs saved by hand from any publisher: checklist page and import.

Usage: python src/review_v2/fulltext/by_hand.py page <dois.txt> <out.html> [--skip-prefix 10.1016 ...]
       python src/review_v2/fulltext/by_hand.py import <dois.txt> [folder ...]

page:   checklist of the DOIs of the list that have no PDF yet (title, journal, year from Crossref), with the file
        name to save under (<paper_id>.pdf). Ticks are kept in the browser.
import: looks at the PDFs in the folders (default: Downloads and its subfolders) changed in the last 14 days.
        A file belongs to a DOI of the list if its name is <paper_id>.pdf, or else if the DOI is printed on its
        first two pages. Matches are copied to <PDF_STORE>/pdf_chrome/<paper_id>.pdf, where inventory.py picks them up.
"""
import argparse
import re
import sys
import time
from html import escape
from pathlib import Path

import pandas as pd
import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.fulltext.elsevier_page import crossref  # noqa: E402
from review_v2.fulltext.fetch_direct import is_pdf  # noqa: E402
from review_v2.fulltext.prepare import OUT, PDF_STORE, paper_id  # noqa: E402
from review_v2.search.merge import norm_doi  # noqa: E402

DEST = PDF_STORE / "pdf_chrome"


def pending(dois_file):
    have = set(pd.read_csv(OUT / "zotero_pdfs.csv")["doi"].map(norm_doi))
    have |= {norm_doi(p.stem.replace("__", "/").replace("--", ":")) for p in DEST.glob("*.pdf")}
    return [d for d in map(norm_doi, Path(dois_file).read_text().split()) if d and d not in have]


def page(a):
    dois = [d for d in pending(a.dois) if not any(d.startswith(p + "/") for p in a.skip_prefix)]
    rows = [{"doi": d, **crossref(d)} for d in dois]
    pub = lambda r: PUBLISHERS.get(r["doi"].split("/")[0], "Other publishers")  # noqa: E731
    rows.sort(key=lambda r: (pub(r) == "Other publishers", pub(r), -(r["year"] or 0)))
    items, prefix = [], None
    for i, r in enumerate(rows, 1):
        if pub(r) != prefix:
            prefix = pub(r)
            items.append(f"<h2>{escape(prefix)} ({sum(pub(x) == prefix for x in rows)})</h2>")
        items.append(
            f'<label><input type=checkbox data-doi="{escape(r["doi"])}"> <span>{i}.</span> '
            f'<a href="https://doi.org/{escape(r["doi"])}" target=_blank rel=noreferrer>{escape(r["title"])}</a> '
            f'<small>{r["year"]} · {escape(r["journal"])} · save as <code>{escape(paper_id(r["doi"]))}.pdf</code>'
            f'</small></label>')
    html = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>PDFs by hand</title>
<style>:root{{--bg:#fff;--fg:#1d1d1f;--mut:#666}}@media (prefers-color-scheme:dark){{:root{{--bg:#1b1b1d;--fg:#eee;--mut:#aaa}}}}
body{{background:var(--bg);color:var(--fg);font:15px system-ui;max-width:900px;margin:20px auto;padding:0 16px}}
label{{display:block;padding:4px 0}}small{{color:var(--mut)}}span{{color:var(--mut);display:inline-block;width:2.5em}}
a{{color:inherit}}code{{user-select:all}}input:checked~a{{color:var(--mut);text-decoration:line-through}}</style>
<h1>Papers to save by hand ({len(rows)})</h1>
<p>Captive / zoo papers (widened scope) that no free copy or Zotero could fetch. Click a title (opens the publisher),
save the PDF into Downloads. The file name does not matter if the PDF prints its DOI on the first pages (most
journals do); to be safe, save it under the name shown (click the name to select it). Tick the box once saved
(<b id=n>0</b> / {len(rows)}); ticks are remembered in this browser. Leave out papers you cannot open. Then tell
Claude, who runs the import and the corpus update.</p>
{"".join(items)}
<script>const K='by_hand_captive';let s={{}};try{{s=JSON.parse(localStorage.getItem(K)||'{{}}')}}catch(e){{}}
const n=()=>document.getElementById('n').textContent=Object.values(s).filter(Boolean).length;
document.querySelectorAll('input').forEach(i=>{{i.checked=!!s[i.dataset.doi];i.onchange=()=>{{s[i.dataset.doi]=i.checked;
try{{localStorage.setItem(K,JSON.stringify(s))}}catch(e){{}};n()}}}});n();</script>"""
    Path(a.out).write_text(html, encoding="utf-8")
    print(len(rows), "papers ->", a.out)


def import_(a):
    todo = {d: paper_id(d) for d in pending(a.dois)}
    by_name = {v.lower(): d for d, v in todo.items()}
    folders = [Path(f) for f in a.folders] or [Path.home() / "Downloads"]
    since = time.time() - 14 * 86400
    DEST.mkdir(parents=True, exist_ok=True)
    found = {}
    for folder in folders:
        for f in folder.rglob("*.pdf"):
            if f.stat().st_mtime < since:
                continue
            doi = by_name.get(f.stem.lower())
            if not doi:
                try:
                    with fitz.open(f) as pdf:
                        text = " ".join(pdf[i].get_text() for i in range(min(2, len(pdf)))).lower()
                except Exception:  # noqa: BLE001
                    continue
                text = re.sub(r"\s+", "", text)
                doi = next((d for d in todo if d not in found and d in text), None)
            if doi and doi not in found and is_pdf(content := f.read_bytes()):
                (DEST / f"{todo[doi]}.pdf").write_bytes(content)
                found[doi] = f.name
    for d, name in found.items():
        print(f"  {d} <- {name}")
    print(f"imported {len(found)} of {len(todo)} pending")


PUBLISHERS = {"10.1098": "Royal Society", "10.1093": "Oxford University Press", "10.1007": "Springer",
              "10.1242": "Company of Biologists", "10.1002": "Wiley", "10.1111": "Wiley", "10.1109": "IEEE",
              "10.1080": "Taylor & Francis", "10.1017": "Cambridge University Press", "10.1371": "PLOS",
              "10.1038": "Nature", "10.1101": "bioRxiv", "10.1145": "ACM",
              "10.3389": "Frontiers", "10.1071": "CSIRO", "10.1063": "AIP", "10.1117": "SPIE", "10.2139": "SSRN",
              "10.1126": "Science", "10.1139": "Canadian Science Publishing", "10.1163": "Brill"}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["page", "import"])
    ap.add_argument("dois")
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--skip-prefix", nargs="*", default=[])
    a = ap.parse_args()
    if a.cmd == "page":
        a.out = a.rest[0]
        page(a)
    else:
        a.folders = a.rest
        import_(a)
