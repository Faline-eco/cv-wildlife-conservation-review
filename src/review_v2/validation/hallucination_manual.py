"""Validation 5.3 (final design): manually verified hallucination rate, built on the comparison of 5.2.

Usage: python src/review_v2/validation/hallucination_manual.py build    (items + human sheet + AI task package)
       python src/review_v2/validation/hallucination_manual.py report   (after human.csv and/or ai_*.csv exist)

Idea: of the values the extraction (Opus) coded for the manually coded papers (5.2, verified items, canonical values),
those the manual coding also has are confirmed by an independent human coder and cannot be hallucinated. Only the
values the manual coding lacks ("auto_only", 1,519) can be. Each of them is checked against the full paper:
  supported   the paper supports the value for the study itself, as the coding protocol defines the field
  partly      close but not exact (too broad / too narrow, applies to part of the study only, role clearly wrong)
  unsupported the paper does not support it, or it belongs to cited / related work only (a hallucination)
  unclear     cannot be decided from the paper
The same item list and rules go to a human rater (sheet.html) and, as a second independent check, to any AI tool
(ai_task.md + items.jsonl -> ai_<tool>.csv). The adjudicator verdict of 5.2 is not shown to either.
Papers are in a seeded random order, so a check that stops early is still a random sample of papers.

Units: one item = (paper, field, canonical value) as in 5.2. Taxa are compared at species, genus and class level,
so one species item can appear up to three times; the report gives the rate with and without the duplicates.
Output: validation/hallucination_v2/{items.csv, items.jsonl, sheet.html, ai_task.md, report.json}
"""
import ast
import hashlib
import json
import random
import sys
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.extraction.verify import verified  # noqa: E402
from review_v2.fulltext.prepare import TEXT, paper_id  # noqa: E402
from review_v2.registry.normalise import key  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402
from review_v2.validation.compare_manual import HABITAT_MAP, PLATFORM_MAP, TASK_MAP  # noqa: E402
from review_v2.validation.fields import _REG, COUNTRY_ALIAS, taxa, taxon_class  # noqa: E402
from review_v2.validation.stats import wilson  # noqa: E402

V2 = ROOT / "review_output" / "v2"
RUN = V2 / "extraction" / "corpus_v2_opus"
VAL = V2 / "validation"
OUT = VAL / "hallucination_v2"
PROTOCOL = Path(__file__).resolve().parents[1] / "extraction" / "protocol_extract.md"
VERDICTS = ["supported", "partly", "unsupported", "unclear"]
SEED = 20261026

FIELD_RULE = {
    "platform": "the imaging platform that recorded the study's own analysed images (mapped to the manual "
                "vocabulary, e.g. 'Stationary Camera')",
    "habitat": "the habitat of the analysed images (manual vocabulary, e.g. 'Marine')",
    "spectrum": "a light spectrum of the analysed images (RGB, thermal infrared, ...)",
    "country": "a country where the analysed images were recorded",
    "task": "a primary computer-vision task of the study (manual vocabulary)",
    "algorithm": "an algorithm (family) the study actually uses in its experiments; new, existing, pre-trained or "
                 "a processing step all count; the role counts against it only if clearly wrong",
    "taxon_species": "a target species whose images are analysed (GBIF backbone name)",
    "taxon_genus": "the genus of a target taxon whose images are analysed",
    "taxon_class": "the class of a target taxon whose images are analysed",
    "own_data": "'yes' = the authors collected (part of) the analysed images themselves",
    "public_dataset": "'yes' = the study uses a public dataset (wildlife dataset or generic benchmark)",
}


def sources(rec):
    """{(field, canonical value): [raw items]} with the same rules as extraction_agreement.auto_values."""
    r = rec["record"]
    out = {}

    def add(field, value, label, item):
        out.setdefault((field, value), []).append(
            {"label": label, "quote": item.get("quote"), "page": item.get("page")})
    for s in r["settings"]:
        if verified(s["evidence"]):
            add("platform", PLATFORM_MAP.get(s["platform"], s["platform"]), f"setting: {s['platform']}", s)
            add("habitat", HABITAT_MAP.get(s["habitat"], s["habitat"]), f"setting: {s['habitat']}", s)
            for c in s["countries"]:
                c2 = COUNTRY_ALIAS.get(c, c)
                add("country", {"United States": "USA", "United Kingdom": "UK"}.get(c2, c2), f"setting: {c}", s)
        for sp in s["spectra"]:
            if verified(sp["evidence"]):
                add("spectrum", sp["value"], f"spectrum: {sp['value']}", sp)
    for t in r["tasks"]:
        if verified(t["evidence"]) and t["role"] == "primary":
            add("task", TASK_MAP.get(t["task"], t["task"]), f"task: {t['task']} ({t['role']})", t)
    for a in r["algorithms"]:
        m = _REG["algorithms"].get(key(a["name"]), {})
        if verified(a["evidence"]) and not m.get("generic", False):
            add("algorithm", m.get("family") or key(a["name"]), f"algorithm: {a['name']} ({a['type']}, {a['role']})", a)
    for sp in r["species"]:
        if not verified(sp["evidence"]) or sp["role"] != "target":
            continue
        for m in taxa(sp["name"], sp["scientific_name"]):
            lab = f"species: {sp['name']} ({sp['scientific_name']})"
            for field, v in (("taxon_species", m.get("species")), ("taxon_genus", m.get("genus")),
                             ("taxon_class", taxon_class(m))):
                if v:
                    add(field, {"Pisces": "Actinopterygii", "Actinopteri": "Actinopterygii"}.get(v, v), lab, sp)
    for d in r["datasets"]:
        lab = f"dataset: {d['name']} (role {d['role']}, availability {d['availability']})"
        if d["role"] == "collected_by_authors":
            add("own_data", "yes", lab, d)
        if d["role"] in ("public_wildlife_dataset", "generic_benchmark"):
            add("public_dataset", "yes", lab, d)
    return out


def build():
    items = pd.read_csv(VAL / "extraction_agreement_items.csv")
    papers = pd.read_csv(V2 / "corpus" / "papers.csv").drop_duplicates("doi").set_index("doi")
    pdfs = pd.read_csv(V2 / "fulltext" / "zotero_pdfs.csv")
    pdfs = pdfs.assign(doi=pdfs["doi"].map(norm_doi)).drop_duplicates("doi").set_index("doi")["pdf"]
    dois = sorted(items["doi"].unique())
    random.Random(SEED).shuffle(dois)
    order = {d: i for i, d in enumerate(dois)}
    rows = []
    for doi in dois:
        src = sources(json.loads((RUN / f"{paper_id(doi)}.json").read_text(encoding="utf-8")))
        for r in items[items["doi"] == doi].itertuples():
            for v in ast.literal_eval(r.auto_only):
                rows.append({"doi": doi, "paper_no": order[doi] + 1, "field": r.field, "value": v,
                             "extracted": src.get((r.field, v), []),
                             "title": papers["title"].get(doi), "year": papers["year"].get(doi),
                             "pdf": pdfs.get(doi), "text": str(TEXT / f"{paper_id(doi)}.json")})
    df = pd.DataFrame(rows)
    df.insert(0, "id", range(1, len(df) + 1))
    missing = df["extracted"].map(len).eq(0).sum()
    assert missing == 0, f"{missing} items without a source item"
    OUT.mkdir(parents=True, exist_ok=True)
    df.assign(extracted=df["extracted"].map(json.dumps)).to_csv(OUT / "items.csv", index=False, encoding="utf-8")
    with open(OUT / "items.jsonl", "w", encoding="utf-8") as f:
        for r in df.to_dict("records"):
            f.write(json.dumps({k: r[k] for k in ("id", "doi", "title", "year", "field", "value", "extracted",
                                                  "pdf", "text")}, ensure_ascii=False, default=str) + "\n")
    ai_task(df)
    sheet(df)
    print(f"{len(df)} items, {df['doi'].nunique()} papers -> {OUT}")


def rules_text():
    return ("Question for every item: does the paper support that THE STUDY ITSELF has this value for the field, "
            "as the coding protocol defines the field? Use the whole paper (methods, data, results), not only the "
            "quote; the quote and page only show where the extractor found it.\n"
            "- supported: the paper states or clearly shows it.\n"
            "- partly: close but not exact (too broad or too narrow, applies to only part of the study, or a role "
            "that is clearly wrong).\n"
            "- unsupported: the paper does not support it, or it belongs only to cited or related work "
            "(a hallucination).\n"
            "- unclear: cannot be decided from the paper.\n"
            "Fields:\n" + "\n".join(f"- {k}: {v}" for k, v in FIELD_RULE.items()))


def ai_task(df):
    (OUT / "ai_task.md").write_text(f"""# Hallucination check, independent AI rating

You check values that an extraction model coded for scientific papers on computer vision for wild animal monitoring.
Items: `items.jsonl` ({len(df)} items, {df['doi'].nunique()} papers), one JSON object per line with
`id`, `doi`, `title`, `field`, `value` (the coded value), `extracted` (the raw extracted item(s) behind the value,
each with the extractor's quote and page), `pdf` (local PDF) and `text` (the paper's text as JSON, `pages[].text`,
one-based page numbers).

Read each paper in full (text file, or the PDF where the text is garbled) and rate every item of that paper.
Do not use any other verdicts; rate independently.

{rules_text()}

Output: one CSV `ai_<tool>.csv` in this folder with the header
`id,verdict,reason,evidence_page,evidence_excerpt`
- verdict: one of {", ".join(VERDICTS)}
- reason: at most 25 words
- evidence_page / evidence_excerpt: the page and a short verbatim excerpt (at most 30 words) of the passage that
  decides the verdict (for unsupported: the passage closest to it, or empty)
One row per item, all {len(df)} items.

## Coding protocol given to the extractor

{PROTOCOL.read_text(encoding="utf-8")}
""", encoding="utf-8")


def pdf_link(pdf, page):
    if not isinstance(pdf, str):
        return ""
    url = "file:///" + pdf.replace("\\", "/") + (f"#page={page}" if page else "")
    return f"<a href='{escape(url)}' target='_blank'>p. {page}</a>"


def sheet(df):
    groups = []
    for doi, g in df.groupby("doi", sort=False):
        g = g.sort_values("id")
        r0 = g.iloc[0]
        rows = []
        for r in g.itertuples():
            ex = "".join(f"<div class='ex'>{escape(e['label'])}<div class='q'>“{escape(str(e['quote']))}” "
                         f"{pdf_link(r.pdf, e['page'])}</div></div>" for e in r.extracted)
            rows.append(f"<tr data-id='{r.id}'><td class='m'>{r.id}</td><td>{escape(r.field)}</td>"
                        f"<td><b>{escape(str(r.value))}</b></td><td>{ex}</td><td class='v'>"
                        + "".join(f"<label><input type='radio' name='v{r.id}' value='{o}'>{o}</label>"
                                  for o in VERDICTS) + "</td></tr>")
        pdf = (f"<a href='{escape('file:///' + r0.pdf.replace(chr(92), '/'))}' target='_blank'>open PDF</a> · "
               if isinstance(r0.pdf, str) else "<span class='bad'>no PDF</span> · ")
        groups.append(f"<tbody class='paper'><tr class='ph'><td colspan='5'><b>Paper {r0.paper_no}</b> · "
                      f"{escape(str(r0.title))} ({r0.year}) · {pdf}<a href='https://doi.org/{escape(doi)}' "
                      f"target='_blank'>{escape(doi)}</a></td></tr>{''.join(rows)}</tbody>")
    key_ = hashlib.sha1(str(sorted(df["id"])).encode()).hexdigest()[:8]
    rules = escape(rules_text()).replace("\n", "<br>")
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Hallucination check</title>
<style>
:root{{--bg:#fff;--fg:#1d1d1f;--mut:#666;--line:#ddd;--ph:#f3f3f5;--bad:#c62828}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1b1b1d;--fg:#eee;--mut:#aaa;--line:#333;--ph:#26262a}}}}
body{{background:var(--bg);color:var(--fg);font:14px system-ui;margin:16px}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid var(--line);padding:6px;vertical-align:top}}
tr.ph td{{background:var(--ph);padding-top:14px}}.m{{color:var(--mut);font-size:12px}}.bad{{color:var(--bad)}}
.ex{{font-size:13px;margin-bottom:4px}}.q{{color:var(--mut);max-width:620px}}label{{display:block;white-space:nowrap}}
tr.cur{{outline:3px solid #1e88e5;outline-offset:-3px;background:rgba(30,136,229,.08)}}tr.done td{{opacity:.55}}
#bar{{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);z-index:1}}
kbd{{border:1px solid var(--line);border-radius:3px;padding:0 4px;font-size:12px}}button{{font-size:14px;padding:6px 12px}}
details{{margin:8px 0}}
</style></head><body>
<h2>Hallucination check: values only the extraction coded ({len(df)} items, {df['doi'].nunique()} papers)</h2>
<details><summary>Rules (same as for the AI check)</summary><p class="m">{rules}</p></details>
<div id="bar"><button id="exp">Export CSV</button> <span id="cnt"></span><br>
<span class="m">Keys: <kbd>s</kbd> supported · <kbd>p</kbd> partly · <kbd>u</kbd> unsupported · <kbd>c</kbd> unclear
(then the next open item) · <kbd>o</kbd> open PDF at the quote · <kbd>j</kbd>/<kbd>k</kbd> next/previous ·
<kbd>z</kbd> undo · click a row to select it. Export saves <code>human.csv</code>; put it in
<code>review_output/v2/validation/hallucination_v2/</code>. Papers are in random order: stopping early keeps a
random sample.</span></div>
<table><tr><th>id</th><th>field</th><th>coded value</th><th>extracted item, quote and page</th><th>your verdict</th></tr>
{''.join(groups)}</table>
<script>const K='halluc2_{key_}', N={len(df)};</script>
<script>{SHEET_JS}</script></body></html>"""
    (OUT / "sheet.html").write_text(html, encoding="utf-8")


SHEET_JS = r"""
let s = {}; try { s = JSON.parse(localStorage.getItem(K) || '{}') } catch (e) {}
const rows = [...document.querySelectorAll('tr[data-id]')], hist = [];
const keys = {s: 'supported', p: 'partly', u: 'unsupported', c: 'unclear'};
let cur = null;
const save = () => { try { localStorage.setItem(K, JSON.stringify(s)) } catch (e) {} };
function paint() {
  rows.forEach(r => r.classList.toggle('done', r.dataset.id in s));
  document.getElementById('cnt').textContent = Object.keys(s).length + ' / ' + N + ' done';
}
function select(r) {
  if (cur) cur.classList.remove('cur');
  cur = r || null;
  if (cur) { cur.classList.add('cur'); cur.scrollIntoView({block: 'center', behavior: 'smooth'}) }
}
const nextOpen = (from) => { const i = from ? rows.indexOf(from) : -1;
  return rows.slice(i + 1).find(r => !(r.dataset.id in s)) || rows.find(r => !(r.dataset.id in s)) };
function set(r, v) {
  hist.push([r, s[r.dataset.id]]);
  s[r.dataset.id] = v; r.querySelector('input[value="' + v + '"]').checked = true; save(); paint();
}
rows.forEach(r => {
  r.querySelectorAll('input[type=radio]').forEach(i => {
    if (s[r.dataset.id] === i.value) i.checked = true;
    i.onchange = () => { set(r, i.value); select(nextOpen(r)) };
  });
  r.addEventListener('click', ev => { if (ev.target.tagName !== 'INPUT' && ev.target.tagName !== 'A') select(r) });
});
document.addEventListener('keydown', ev => {
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const k = ev.key.toLowerCase();
  if (k in keys && cur) { ev.preventDefault(); set(cur, keys[k]); select(nextOpen(cur)) }
  else if (k === 'j' || k === 'k') { ev.preventDefault();
    const i = cur ? rows.indexOf(cur) : -1; select(rows[Math.min(rows.length - 1, Math.max(0, i + (k === 'j' ? 1 : -1)))]) }
  else if (k === 'o' && cur) { const a = cur.querySelector('a'); if (a) { ev.preventDefault(); window.open(a.href, '_blank') } }
  else if (k === 'z' && hist.length) { ev.preventDefault();
    const [r, old] = hist.pop();
    if (old === undefined) { delete s[r.dataset.id]; r.querySelectorAll('input').forEach(i => i.checked = false) }
    else { s[r.dataset.id] = old; r.querySelector('input[value="' + old + '"]').checked = true }
    save(); paint(); select(r) }
});
document.getElementById('exp').onclick = () => {
  const t = 'id,verdict\n' + Object.entries(s).map(([k, v]) => k + ',' + v).join('\n');
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([t], {type: 'text/csv'}));
  a.download = 'human.csv'; a.click();
};
paint(); select(nextOpen(null));
"""


def kappa(a, b):
    labels = sorted(set(a) | set(b))
    a, b = np.asarray(a), np.asarray(b)
    po = (a == b).mean()
    pe = sum((a == lab).mean() * (b == lab).mean() for lab in labels)
    return float((po - pe) / (1 - pe)) if pe < 1 else 1.0


def rate(df, col, both_total, auto_total, rng, b=2000):
    """Hallucination rate over all extracted values: unsupported share among rated auto_only items, scaled by
    auto_only / all values (the values also in the manual coding count as supported). Paper-level bootstrap."""
    d = df[df[col].notna() & (df[col] != "unclear")]
    if d.empty:
        return None
    papers = d["doi"].unique()
    by = {p: g[col].to_numpy() for p, g in d.groupby("doi")}
    scale = auto_total / (auto_total + both_total)

    def share(ps, labels):
        v = np.concatenate([by[p] for p in ps])
        return np.isin(v, labels).mean()
    res = {"rated": len(d), "papers": len(papers)}
    for name, labels in (("unsupported", ["unsupported"]), ("not_supported", ["unsupported", "partly"])):
        boots = [share(rng.choice(papers, len(papers)), labels) for _ in range(b)]
        p = share(papers, labels)
        res[name] = {"among_auto_only": p, "overall": p * scale, "overall_lo": float(np.percentile(boots, 2.5)) * scale,
                     "overall_hi": float(np.percentile(boots, 97.5)) * scale}
    return res


def report():
    df = pd.read_csv(OUT / "items.csv")
    items = pd.read_csv(VAL / "extraction_agreement_items.csv")
    # the rated items are frozen; the comparison sample of 5.2 changed afterwards (papers added by the final rounds,
    # papers dropped by the scope rules). Rates use the papers that are in both, with totals over the same papers.
    df = df[df["doi"].isin(set(items["doi"]))]
    items = items[items["doi"].isin(set(df["doi"]))]
    both = sum(len(ast.literal_eval(x)) for x in items["both"])
    auto = sum(len(ast.literal_eval(x)) for x in items["auto_only"])
    raters = {"human": OUT / "human.csv"} | {f.stem: f for f in sorted(OUT.glob("ai_*.csv"))}
    for name, f in raters.items():
        if f.exists():
            r = pd.read_csv(f)
            col = "verdict" if "verdict" in r else r.columns[1]
            df = df.merge(r[["id", col]].rename(columns={col: name}), on="id", how="left")
    # 5.2 model adjudicator, for comparison only
    adj = pd.DataFrame([x for f in (VAL / "adjudication").glob("*.json")
                        for x in json.loads(f.read_text(encoding="utf-8"))["items"]])
    adj = adj[adj["side"] == "auto_only"].set_index(["doi", "field", "value"])["verdict"]
    df["adjudicator_5_2"] = [adj.get((d, f, v)) for d, f, v in zip(df["doi"], df["field"], df["value"].astype(str))]
    # PLATFORM_MAP turns Opus's "Not reported" / "Web / citizen-science images" into "Non-specialized Camera" for
    # the comparison with the manual coding; such items are not a claim Opus made and are left out of the rates
    raw = df["extracted"].map(lambda x: {e["label"].removeprefix("setting: ") for e in json.loads(x)})
    no_claim = {"Not reported", "Web / citizen-science images"}
    mapped = (df["field"] == "platform") & np.array([v not in r and r <= no_claim for v, r in zip(df["value"], raw)])
    rng = np.random.default_rng(SEED)
    names = [n for n in raters if n in df]
    res = {"papers": int(df["doi"].nunique()), "values_extracted": both + auto, "confirmed_by_manual": both,
           "auto_only": auto,
           "excluded_mapped_platform": int(mapped.sum()), "raters": {}}
    all_df, df = df, df[~mapped]
    dedup = df.drop_duplicates(["doi", "extracted"]) if "extracted" in df else df
    for n in names:
        res["raters"][n] = {"all_items": rate(df, n, both, auto, rng),
                            "taxa_deduplicated": rate(dedup, n, both, auto, rng),
                            "counts": df[n].value_counts().to_dict(),
                            "by_field": {f: {"n": int(g[n].notna().sum()),
                                             "unsupported": wilson(int((g[n] == "unsupported").sum()),
                                                                   int(g[n].notna().sum()))}
                                         for f, g in df.groupby("field") if g[n].notna().any()}}
    pairs = {}
    for i, a in enumerate(names + ["adjudicator_5_2"]):
        for b in (names + ["adjudicator_5_2"])[i + 1:]:
            d = all_df.dropna(subset=[a, b])
            if b == "adjudicator_5_2" or a == "adjudicator_5_2":   # 5.2 uses correct / wrong / unclear
                m = {"correct": "supported", "wrong": "unsupported", "unclear": "unclear"}
                d = d.assign(**{"adjudicator_5_2": d["adjudicator_5_2"].map(m)})
                bin_ = lambda s: s.map({"supported": "ok", "partly": "ok", "unsupported": "bad", "unclear": "?"})  # noqa
                d = d.assign(**{a: bin_(d[a]), b: bin_(d[b])})
            if len(d):
                pairs[f"{a}_vs_{b}"] = {"n": len(d), "agreement": wilson(int((d[a] == d[b]).sum()), len(d)),
                                        "kappa": kappa(d[a], d[b])}
    res["agreement"] = pairs
    (OUT / "report.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    print(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    {"build": build, "report": report}[sys.argv[1]]()
