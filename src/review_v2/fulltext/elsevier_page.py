"""Page for saving Elsevier PDFs by hand (ScienceDirect refuses scripted download).

Usage: python src/review_v2/fulltext/elsevier_page.py <dois.txt> <out.html>

Takes the 10.1016 DOIs of the list that have no PDF yet, looks up title, journal, year and PII at Crossref, adds the
PIIs to fetch/elsevier_pii.json (import_elsevier.py maps the saved 1-s2.0-<PII>-main.pdf files back to DOIs) and
writes a checklist page. Ticks are kept in the browser.
"""
import json
import re
import sys
from html import escape
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.fulltext.import_elsevier import PII  # noqa: E402
from review_v2.fulltext.prepare import OUT  # noqa: E402
from review_v2.search.merge import norm_doi  # noqa: E402


def crossref(doi):
    r = requests.get(f"https://api.crossref.org/works/{doi}", timeout=30)
    if r.status_code != 200:   # DataCite DOIs etc.: OpenAlex has the metadata
        w = requests.get(f"https://api.openalex.org/works/doi:{doi}", timeout=30)
        w = w.json() if w.status_code == 200 else {}
        return {"title": w.get("title") or doi, "year": w.get("publication_year"), "pii": "",
                "journal": ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""}
    m = r.json()["message"]
    pii = next((re.sub(r"[^A-Z0-9]", "", a.upper()) for a in m.get("alternative-id", []) if re.match(r"^S?\d", a)), "")
    year = (m.get("issued", {}).get("date-parts") or [[None]])[0][0]
    return {"title": (m.get("title") or [""])[0], "journal": (m.get("container-title") or [""])[0], "year": year,
            "pii": pii}


if __name__ == "__main__":
    have = set(pd.read_csv(OUT / "zotero_pdfs.csv")["doi"].map(norm_doi))
    dois = [d for d in map(norm_doi, Path(sys.argv[1]).read_text().split()) if d.startswith("10.1016/") and d not in have]
    piis = json.loads(PII.read_text()) if PII.exists() else {}
    rows = []
    for d in dois:
        m = crossref(d)
        if m["pii"]:
            piis[d] = m["pii"]
        rows.append({"doi": d, **m})
    PII.write_text(json.dumps(piis, indent=1))
    rows.sort(key=lambda r: -(r["year"] or 0))
    items = "".join(
        f'<label><input type=checkbox data-doi="{escape(r["doi"])}"> <span>{i}.</span> '
        f'<a href="https://doi.org/{escape(r["doi"])}" target=_blank rel=noreferrer>{escape(r["title"])}</a> '
        f'<small>{r["year"]} · {escape(r["journal"])}{"" if r["pii"] else " · no PII, rename the file to the DOI"}'
        f'</small></label>' for i, r in enumerate(rows, 1))
    html = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Elsevier by hand</title>
<style>:root{{--bg:#fff;--fg:#1d1d1f;--mut:#666}}@media (prefers-color-scheme:dark){{:root{{--bg:#1b1b1d;--fg:#eee;--mut:#aaa}}}}
body{{background:var(--bg);color:var(--fg);font:15px system-ui;max-width:900px;margin:20px auto;padding:0 16px}}
label{{display:block;padding:4px 0}}small{{color:var(--mut)}}span{{color:var(--mut);display:inline-block;width:2.5em}}
a{{color:inherit}}input:checked~a{{color:var(--mut);text-decoration:line-through}}</style>
<h1>Elsevier papers to save by hand ({len(rows)})</h1>
<p>Captive / zoo papers (widened scope) that no free copy or Zotero could fetch. Click a title (opens ScienceDirect),
then "View PDF" and save the PDF into Downloads, keeping the file name <code>1-s2.0-&lt;PII&gt;-main.pdf</code>. Tick the
box once saved (<b id=n>0</b> / {len(rows)}); ticks are remembered in this browser. Then tell Claude, who runs
<code>import_elsevier.py</code> and the corpus update.</p>
{items}
<script>const K='elsevier_captive';let s={{}};try{{s=JSON.parse(localStorage.getItem(K)||'{{}}')}}catch(e){{}}
const n=()=>document.getElementById('n').textContent=Object.values(s).filter(Boolean).length;
document.querySelectorAll('input').forEach(i=>{{i.checked=!!s[i.dataset.doi];i.onchange=()=>{{s[i.dataset.doi]=i.checked;
try{{localStorage.setItem(K,JSON.stringify(s))}}catch(e){{}};n()}}}});n();</script>"""
    Path(sys.argv[2]).write_text(html, encoding="utf-8")
    print(len(rows), "papers,", sum(bool(r["pii"]) for r in rows), "with PII ->", sys.argv[2])
