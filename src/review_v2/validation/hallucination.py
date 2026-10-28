"""Validation 5.3: are the coded values supported by the papers?

Usage: python src/review_v2/validation/hallucination.py sample      (draw the sample)
       python src/review_v2/validation/hallucination.py judge       (independent model check, one call per paper)
       python src/review_v2/validation/hallucination.py sheet       (HTML sheet for the human check)
       python src/review_v2/validation/hallucination.py report      (rates, after the human check CSV exists)

Sample: 40 items per field from the eligible papers (seeded), drawn among all items, verified or not, so the rate
covers the whole output. Fields: platform, habitat, spectrum, country, species, dataset, task, algorithm, flag.
Judge: a fresh headless call (claude-sonnet-5-5, i.e. not the extracting model) reads the paper text and rates each
item: supported / partly / unsupported, with a short reason. Versions (all kept, compared in the report):
v1 (judge/) read "proposed" as "newly invented" and rated applied pre-trained models as partly; v2 (judge_v2/,
2026-10-25) added the role definitions but still applied its own standards (e.g. "auxiliary step"); v3 (judge_v3/)
reads the full extraction protocol and rates an algorithm by whether the study used it. Human check: the sheet lists every item with the
quote and the judge's verdict; the user's verdicts are exported as validation/hallucination_human.csv.
"""
import hashlib
import json
import random
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from html import escape
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.extraction.verify import verified  # noqa: E402
from review_v2.fulltext.prepare import TEXT, paper_id, render  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402
from review_v2.validation.stats import wilson  # noqa: E402

V2 = ROOT / "review_output" / "v2"
RUN = V2 / "extraction" / "corpus_v2_opus"
OUT = V2 / "validation" / "hallucination"
PER_FIELD = 40
MODEL = "claude-sonnet-5-5"

PROTOCOL_V2 = """You check data extracted from a scientific paper on computer vision for animal monitoring. For each \
numbered item you get the field, the coded value and the quote the extractor gave as evidence. Decide from the \
paper text whether the paper supports the coded value for the study itself (not only for cited work):
- "supported": the paper states or clearly shows it.
- "partly": the value is close but not exact (e.g. too broad or too narrow a taxon, a related platform).
- "unsupported": the paper does not support it, or it belongs to cited work only.
Judge the role in the value by the definitions of the coding protocol, not by everyday meaning:
- algorithm role: "proposed" = the paper's own method or the model it builds on, including an existing or pre-trained architecture the study applies or fine-tunes as its main model (it need not be newly invented); "backbone" = feature extractor inside the main model; "baseline" = compared against.
- species role: "target" = animals the study is about and whose images are analysed; "benchmark_class" = classes inside a generic or fine-grained benchmark used only to test a general method; "mentioned" = named but not analysed.
- dataset role: "collected_by_authors", "public_wildlife_dataset", "generic_benchmark" (ImageNet, COCO, ...), "pretraining_only".
- task role: "primary" = the task the paper is about, "auxiliary" = a processing step that serves another task.
Reason in at most 20 words."""

# v3: the judge reads the extraction protocol itself, so it applies the coding rules instead of its own standards
PROTOCOL = """You check data extracted from a scientific paper on computer vision for animal monitoring. For each numbered item you get the field, the coded value and the quote the extractor gave as evidence. Decide from the paper text whether the paper supports the coded value for the study itself (not only for cited work), judged by the coding protocol below (what counts as correct is what the protocol asks for, not your own standard):
- "supported": the paper states or clearly shows it, and the value follows the protocol.
- "partly": the value is close but not exact (e.g. too broad or too narrow a taxon, a related platform).
- "unsupported": the paper does not support it, or it belongs to cited work only.
Algorithms: the review asks which algorithms the studies use, not which ones they invent. An algorithm the study used is "supported", whether it is new, existing, pre-trained or a processing step of the authors' pipeline. Its role counts against it only if clearly wrong (e.g. a method the paper only compares against coded as "proposed", or a method the paper never runs).
Reason in at most 20 words.

Coding protocol given to the extractor:
""" + (Path(__file__).resolve().parents[1] / "extraction" / "protocol_extract.md").read_text(encoding="utf-8")
JUDGE = "judge_v3"   # v1 (judge/): no role definitions; v2 (judge_v2/): role definitions only

SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "integer"},
                                     "verdict": {"type": "string", "enum": ["supported", "partly", "unsupported"]},
                                     "reason": {"type": "string"}},
    "required": ["id", "verdict", "reason"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False}


def items_of(doi, rec):
    for i, s in enumerate(rec["settings"]):
        yield "platform", s["platform"], s
        yield "habitat", s["habitat"], s
        for sp in s["spectra"]:
            yield "spectrum", sp["value"], sp
        for c in s["countries"]:
            yield "country", c, s
    for s in rec["species"]:
        yield "species", f"{s['name']} ({s['scientific_name']}), role {s['role']}", s
    for d in rec["datasets"]:
        yield "dataset", f"{d['name']} (role {d['role']}, availability {d['availability']})", d
    for t in rec["tasks"]:
        yield "task", f"{t['task']} ({t['role']})", t
    for a in rec["algorithms"]:
        yield "algorithm", f"{a['name']} ({a['type']}, {a['role']})", a
    for k, v in rec["flags"].items():
        if v["value"]:
            yield "flag", k, v


def sample():
    eligible = set(pd.read_csv(V2 / "corpus" / "papers.csv").query("eligible")["doi"])
    pool = {}
    for f in sorted(RUN.glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        doi = norm_doi(r["doi"])
        if "record" not in r or doi not in eligible:
            continue
        for field, value, item in items_of(doi, r["record"]):
            pool.setdefault(field, []).append({"doi": doi, "field": field, "value": value, "quote": item["quote"],
                                               "page": item["page"], "evidence": item["evidence"]["status"],
                                               "verified": verified(item["evidence"])})
    rng = random.Random(20261022)
    rows = [x for field in sorted(pool) for x in rng.sample(pool[field], min(PER_FIELD, len(pool[field])))]
    df = pd.DataFrame(rows)
    df.insert(0, "id", range(len(df)))
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "sample.csv", index=False, encoding="utf-8")
    print(df["field"].value_counts().to_string(), "\npapers:", df["doi"].nunique())


def call(text, items, workdir):
    lines = "\n".join(f"{i}. field: {x['field']} | value: {x['value']} | quote: \"{x['quote']}\" (page {x['page']})"
                      for i, x in enumerate(items))
    cmd = [shutil.which("claude"), "-p", "--model", MODEL, "--output-format", "json", "--system-prompt", PROTOCOL,
           "--json-schema", json.dumps(SCHEMA), "--tools", "", "--no-session-persistence"]
    res = subprocess.run(cmd, input=f"Items:\n{lines}\n\nPaper:\n{text}", capture_output=True, text=True,
                         encoding="utf-8", cwd=workdir, timeout=900)
    env = json.loads(res.stdout)
    if res.returncode != 0 or env.get("is_error"):
        raise RuntimeError(str(env.get("result"))[:300])
    out = env.get("structured_output") or json.loads(env["result"])
    return {x["id"]: x for x in out["items"]}, env.get("total_cost_usd") or 0


def judge():
    df = pd.read_csv(OUT / "sample.csv")
    jdir = OUT / JUDGE
    jdir.mkdir(exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="halluc_")

    def run(doi):
        target = jdir / f"{paper_id(doi)}.json"
        if target.exists():
            return 0
        g = df[df["doi"] == doi].to_dict("records")
        text = render(json.loads((TEXT / f"{paper_id(doi)}.json").read_text(encoding="utf-8")))
        for _ in range(3):
            try:
                res, cost = call(text, g, workdir)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", doi, e, flush=True)
        else:
            return 0
        target.write_text(json.dumps({"doi": doi, "model": MODEL, "cost_usd": cost,
                                      "items": [{**res.get(i, {"verdict": None, "reason": None}), "id": x["id"]}
                                                for i, x in enumerate(g)]}, indent=1), encoding="utf-8")
        return cost
    with ThreadPoolExecutor(4) as ex:
        cost = sum(ex.map(run, sorted(df["doi"].unique())))
    print(f"judge done, ${cost:.2f}")


def judged(version=JUDGE):
    df = pd.read_csv(OUT / "sample.csv")
    v = {}
    for f in (OUT / version).glob("*.json"):
        j = json.loads(f.read_text(encoding="utf-8"))
        # items are in the order of the paper's sample rows (the first run stored the call-local id)
        for sid, x in zip(df.loc[df["doi"] == j["doi"], "id"], j["items"]):
            v[sid] = (x["verdict"], x["reason"])
    df["judge"] = df["id"].map(lambda i: v.get(i, (None, None))[0])
    df["judge_reason"] = df["id"].map(lambda i: v.get(i, (None, None))[1])
    return df


# sheet behaviour: radio choices and key strokes write to localStorage; the highlighted row is the first open one
SHEET_JS = r"""
let s = {}; try { s = JSON.parse(localStorage.getItem(K) || '{}') } catch (e) {}
const rows = [...document.querySelectorAll('tr[data-id]')], hist = [];
const keys = {s: 'supported', p: 'partly', u: 'unsupported'};
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
const hide = document.getElementById('hide');
try { hide.checked = localStorage.getItem(K + '_hide') === '1' } catch (e) {}
const applyHide = () => { document.body.classList.toggle('hidej', hide.checked);
  try { localStorage.setItem(K + '_hide', hide.checked ? '1' : '0') } catch (e) {} };
hide.onchange = applyHide; applyHide();
document.addEventListener('keydown', ev => {
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const k = ev.key.toLowerCase();
  if (k in keys && cur) { ev.preventDefault(); set(cur, keys[k]); select(nextOpen(cur)) }
  else if (k === 'j' || k === 'k') { ev.preventDefault();
    const i = cur ? rows.indexOf(cur) : -1; select(rows[Math.min(rows.length - 1, Math.max(0, i + (k === 'j' ? 1 : -1)))]) }
  else if (k === 'o' && cur) { ev.preventDefault(); window.open(cur.querySelector('a').href, '_blank') }
  else if (k === 'z' && hist.length) { ev.preventDefault();
    const [r, old] = hist.pop();
    if (old === undefined) { delete s[r.dataset.id]; r.querySelectorAll('input').forEach(i => i.checked = false) }
    else { s[r.dataset.id] = old; r.querySelector('input[value="' + old + '"]').checked = true }
    save(); paint(); select(r) }
});
document.getElementById('exp').onclick = () => {
  const t = 'id,human\n' + Object.entries(s).map(([k, v]) => k + ',' + v).join('\n');
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([t], {type: 'text/csv'}));
  a.download = 'hallucination_human.csv'; a.click();
};
paint(); select(nextOpen(null));
"""


def sheet():
    df = judged()
    df = df.sort_values(["judge", "field"], key=lambda s: s.map({"unsupported": 0, "partly": 1}).fillna(2)
                        if s.name == "judge" else s)
    rows = "\n".join(
        f"<tr data-id='{r.id}'><td>{r.id}</td><td>{escape(r.field)}</td><td>{escape(str(r.value))}</td>"
        f"<td class='q'>{escape(str(r.quote))}<div class='m'>p. {r.page} · evidence {r.evidence}</div></td>"
        f"<td><a href='https://doi.org/{escape(r.doi)}' target='_blank'>{escape(r.doi)}</a></td>"
        f"<td class='j {r.judge}'>{r.judge}<div class='m'>{escape(str(r.judge_reason))}</div></td>"
        f"<td class='v'>" + "".join(f"<label><input type='radio' name='v{r.id}' value='{o}'>{o}</label>"
                                    for o in ("supported", "partly", "unsupported")) + "</td></tr>"
        for r in df.itertuples())
    key = hashlib.sha1(str(sorted(df["id"])).encode()).hexdigest()[:8]
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Hallucination check</title>
<style>
:root{{--bg:#fff;--fg:#1d1d1f;--mut:#666;--line:#ddd;--bad:#c62828;--mid:#b26a00;--good:#2e7d32}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1b1b1d;--fg:#eee;--mut:#aaa;--line:#333}}}}
body{{background:var(--bg);color:var(--fg);font:14px system-ui;margin:16px}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid var(--line);padding:6px;vertical-align:top}}
.q{{max-width:420px}}.m{{color:var(--mut);font-size:12px}}.unsupported{{color:var(--bad)}}.partly{{color:var(--mid)}}
.supported{{color:var(--good)}}label{{display:block;white-space:nowrap}}button{{font-size:14px;padding:6px 12px}}
tr.cur{{outline:3px solid #1e88e5;outline-offset:-3px;background:rgba(30,136,229,.08)}}
tr.done td{{opacity:.55}}body.hidej tr:not(.done) td.j{{visibility:hidden}}
#bar{{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);z-index:1}}
kbd{{border:1px solid var(--line);border-radius:3px;padding:0 4px;font-size:12px}}
</style></head><body>
<h2>Hallucination check ({len(df)} items)</h2>
<p>Open the paper via the DOI, find the quote on the given page, and decide whether the paper supports the coded
value for the study itself. Items the judge model doubted are listed first. Choices are saved in this browser.
When done, export the CSV and save it as
<code>review_output/v2/validation/hallucination/hallucination_human.csv</code>.</p>
<div id="bar"><button id="exp">Export CSV</button> <span id="cnt"></span> &nbsp;
<label style="display:inline"><input type="checkbox" id="hide"> hide judge verdict until I have decided</label><br>
<span class="m">Keys: <kbd>s</kbd> supported · <kbd>p</kbd> partly · <kbd>u</kbd> unsupported (applied to the
highlighted item, then the next open item is shown) · <kbd>o</kbd> open paper · <kbd>j</kbd>/<kbd>k</kbd> next/previous
item · <kbd>z</kbd> undo last · click a row to select it</span></div>
<table><tr><th>id</th><th>field</th><th>coded value</th><th>quote</th><th>paper</th><th>judge</th><th>your verdict</th></tr>
{rows}</table>
<script>
const K='halluc_{key}', N={len(df)};
</script>
<script>{SHEET_JS}</script></body></html>"""
    (OUT / "sheet.html").write_text(html, encoding="utf-8")
    print("sheet:", OUT / "sheet.html")


def report():
    df = judged()
    human = OUT / "hallucination_human.csv"
    if human.exists():
        df = df.merge(pd.read_csv(human), on="id", how="left")
    res = {}
    for col in [c for c in ("judge", "human") if c in df]:
        d = df[df[col].notna()]
        res[col] = {"all": {"unsupported": wilson(int((d[col] == "unsupported").sum()), len(d)),
                            "not_supported": wilson(int((d[col] != "supported").sum()), len(d))},
                    "by_field": {f: wilson(int((g[col] == "unsupported").sum()), len(g)) for f, g in d.groupby("field")},
                    "by_verified": {str(k): wilson(int((g[col] == "unsupported").sum()), len(g))
                                    for k, g in d.groupby("verified")}}
    if "human" in df:
        d = df.dropna(subset=["judge", "human"])
        res["judge_vs_human_agreement"] = wilson(int((d["judge"] == d["human"]).sum()), len(d))
        for old in ("judge", "judge_v2"):
            v = judged(old).set_index("id")["judge"]
            e = d[d["id"].map(v).notna()]
            res[f"{old}_vs_human_agreement"] = wilson(int((e["id"].map(v) == e["human"]).sum()), len(e))
    (OUT / "report.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    {"sample": sample, "judge": judge, "sheet": sheet, "report": report}[sys.argv[1]]()
