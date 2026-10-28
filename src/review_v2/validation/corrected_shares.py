"""Validation 5.6: the main shares corrected for the measured extraction error, with intervals.

Usage: python src/review_v2/validation/corrected_shares.py [plot]   (after adjudicate_disagreements.py and
       corpus/tables.py; "plot" only redraws the figures from corrected_shares.json)

For a value v of a field (e.g. platform = camera trap), the adjudicated sample of 5.2 gives, over its papers,
  TP = papers where the extraction codes v and v is correct, FP = extraction codes v wrongly,
  FN = v is correct but the extraction misses it ("unclear" verdicts are left out).
The true share of papers with v is then estimated as observed share x k_v with k_v = (TP + FN) / (TP + FP).
Rare values have few sample papers, so k_v is shrunk towards the field-level factor k_f (pseudo-count M):
  k_v = (TP + FN + M k_f) / (TP + FP + M).
Values that the comparison merged with another (e.g. web images, coded as "non-specialised camera" in the manual
vocabulary) use k_f. Interval: percentile bootstrap that resamples the sample papers (k_v) and the corpus papers
(observed share) independently. Limits: the reference only contains values that at least one coder found, so
values both missed are not counted; the sample is the old manual corpus (2014-2024), not the 2024-2026 papers.
Output: validation/corrected_shares.json, paper/images/results_v2/corrected_shares_<field>.pdf
"""
import ast
import json
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import seaborn as sns  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.figures.make_figures import FIG, load, papers_per, short  # noqa: E402
from review_v2.search.merge import ROOT  # noqa: E402
from review_v2.validation.compare_manual import PLATFORM_MAP, TASK_MAP  # noqa: E402

V = ROOT / "review_output" / "v2" / "validation"
M = 5
B = 2000
TOP = 10
MERGED = {"platform": set(PLATFORM_MAP), "task": set(TASK_MAP)}


def sample_counts():
    """{(field, value): per-paper arrays of tp, fp, fn over the adjudicated sample papers}."""
    items = pd.read_csv(V / "extraction_agreement_items.csv")
    adj = pd.DataFrame([x for f in (V / "adjudication").glob("*.json")
                        for x in json.loads(f.read_text(encoding="utf-8"))["items"]])
    verdict = {(r.doi, r.field, r.value, r.side): r.verdict for r in adj.itertuples()}
    papers = sorted(items["doi"].unique())
    pos = {d: i for i, d in enumerate(papers)}
    counts = {}

    def add(field, value, doi, kind):
        arr = counts.setdefault((field, value), np.zeros((3, len(papers))))
        arr["tp fp fn".split().index(kind), pos[doi]] += 1
    for r in items.itertuples():
        for v in ast.literal_eval(r.both):
            add(r.field, v, r.doi, "tp")
        for v in ast.literal_eval(r.auto_only):
            x = verdict.get((r.doi, r.field, v, "auto_only"))
            if x in ("correct", "wrong"):
                add(r.field, v, r.doi, "tp" if x == "correct" else "fp")
        for v in ast.literal_eval(r.manual_only):
            if verdict.get((r.doi, r.field, v, "manual_only")) == "correct":
                add(r.field, v, r.doi, "fn")
    return counts, len(papers)


def factor(arr_v, arr_f, idx):
    tp, fp, fn = arr_v[:, idx].sum(1) if arr_v is not None else (0, 0, 0)
    ftp, ffp, ffn = arr_f[:, idx].sum(1)
    kf = (ftp + ffn) / max(ftp + ffp, 1)
    return (tp + fn + M * kf) / (tp + fp + M), kf


def observed(p, t):
    st = t["settings"]
    tasks = t["tasks"][t["tasks"]["role"] == "primary"]
    return {"platform": (st, "platform"), "habitat": (st, "habitat"), "spectrum": (t["setting_spectra"], "spectrum"),
            "task": (tasks, "task"), "taxon_class": (t["target"].dropna(subset=["taxon_class"]), "taxon_class")}


def plot(res):
    """One full-width panel per field (corrected_shares_<field>.pdf), shown as subfigures in the paper."""
    sns.set_theme(style="darkgrid", context="paper", font_scale=1.1)
    for field, r in res.items():
        labels = [short(v) for v in r][::-1]
        y = np.arange(len(labels))
        obs = [100 * x["observed"] for x in r.values()][::-1]
        cor = [100 * x["corrected"] for x in r.values()][::-1]
        lo = [100 * x["lo"] for x in r.values()][::-1]
        hi = [100 * x["hi"] for x in r.values()][::-1]
        fig, ax = plt.subplots(figsize=(9.5, 0.26 * len(labels) + 0.9))
        ax.barh(y, obs, color=sns.color_palette("tab10")[0], alpha=0.45, label="Observed (verified items)")
        ax.errorbar(cor, y, xerr=[np.subtract(cor, lo), np.subtract(hi, cor)], fmt="o", color="black", ms=4,
                    capsize=2, label="Corrected, 95% interval")
        ax.set_yticks(y)
        ax.set_yticklabels(labels)
        ax.set_xlabel("Share of papers (%)")
        ax.legend(loc="lower right", fontsize=8)
        fig.tight_layout()
        fig.savefig(FIG / f"corrected_shares_{field}.pdf", bbox_inches="tight")
        plt.close(fig)


if __name__ == "__main__" and sys.argv[1:] == ["plot"]:
    # redraw the figures from the stored results, without re-running the bootstrap
    plot(json.loads((V / "corrected_shares.json").read_text(encoding="utf-8")))
elif __name__ == "__main__":
    p, t = load()
    n = len(p)
    counts, n_sample = sample_counts()
    rng = np.random.default_rng(20261023)
    boot_sample = [rng.integers(0, n_sample, n_sample) for _ in range(B)]
    doi_index = {d: i for i, d in enumerate(p["doi"])}
    boot_corpus = [np.bincount(rng.integers(0, n, n), minlength=n) for _ in range(B)]
    res = {}
    for field, (df, col) in observed(p, t).items():
        arr_f = sum(a for (f, _), a in counts.items() if f == field)
        shares = papers_per(df, col, n).drop(index=["Not reported", "Other"], errors="ignore").head(TOP)
        res[field] = {}
        for v, row in shares.iterrows():
            arr_v = None if v in MERGED.get(field, ()) else counts.get((field, v))
            k, kf = factor(arr_v, arr_f, slice(None))
            has = np.zeros(n)
            has[[doi_index[d] for d in df.loc[df[col] == v, "doi"].unique()]] = 1
            draws = np.array([factor(arr_v, arr_f, bs)[0] * (has * bc).sum() / n
                              for bs, bc in zip(boot_sample, boot_corpus)])
            tp, fp, fn = arr_v.sum(1) if arr_v is not None else (0, 0, 0)
            res[field][v] = {"observed": row["share"], "papers": int(row["papers"]), "k": k, "k_field": kf,
                             "corrected": row["share"] * k, "lo": float(np.percentile(draws, 2.5)),
                             "hi": float(np.percentile(draws, 97.5)), "sample_tp": int(tp), "sample_fp": int(fp),
                             "sample_fn": int(fn)}
    (V / "corrected_shares.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")

    plot(res)
    for field, r in res.items():
        print(field)
        for v, x in r.items():
            print(f"  {short(v):28s} obs {100 * x['observed']:5.1f}  corr {100 * x['corrected']:5.1f} "
                  f"[{100 * x['lo']:5.1f}-{100 * x['hi']:5.1f}]  k {x['k']:.2f} (tp {x['sample_tp']} fp "
                  f"{x['sample_fp']} fn {x['sample_fn']})")
