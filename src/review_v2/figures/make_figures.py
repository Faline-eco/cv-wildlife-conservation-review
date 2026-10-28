"""All result figures, regression tables and numbers.tex from the corpus tables (one scripted path).

Usage: python src/review_v2/figures/make_figures.py   (after corpus/build.py and corpus/tables.py)

Corpus: eligible papers of corpus/papers.csv (widened scope); items must be verified (quote found, not in
introduction or related work). Shares are shares of papers, never of labels. Years before 2014 (online-first
dates of 2014 issues) count as 2014. 2026 is partial: shown, but not used in trend fits (LAST_FULL_YEAR).
Output: paper/images/results_v2/*.pdf, paper/tables_v2/*.tex, paper/numbers.tex
"""
import json
import math
import re
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

V2 = ROOT / "review_output" / "v2"
CORPUS = V2 / "corpus"
FIG = ROOT / "paper" / "images" / "results_v2"
TAB = ROOT / "paper" / "tables_v2"
FULL_W = 9.5   # inches; shown at full text width (6.5 in), so fonts keep about the size of the first version
NUMBERS = ROOT / "paper" / "numbers.tex"
FIRST_YEAR, LAST_FULL_YEAR = 2014, 2025
SHORT = {
    "Unmanned aerial vehicle (UAV; e.g. drone)": "UAV / drone",
    "Crewed aerial vehicle (CAV; e.g. plane, helicopter)": "Crewed aircraft",
    "Remotely operated underwater vehicle (ROV)": "ROV", "Autonomous Underwater Vehicle (AUV)": "AUV",
    "Rocky areas (e.g. inland cliffs, mountain peaks)": "Rocky areas",
    "Cave and subterranean habitats (non-aquatic)": "Caves / subterranean",
    "Long-wave Infrared / Thermal (LWIR)": "Thermal (LWIR)", "Near Infrared (NIR)": "Near infrared (NIR)",
    "Short-wave Infrared (SWIR)": "SWIR", "Mid-wave Infrared (MWIR)": "MWIR", "Ultraviolet (UV-A/B)": "UV",
    "Radar / Synthetic-Aperture Radar (SAR)": "Radar / SAR", "Active Imaging Sonar (multibeam)": "Sonar",
    "Web / citizen-science images": "Web / citizen science", "Non-specialized Camera": "Non-specialised camera",
    "classical_image_processing": "Classical image processing", "classical_machine_learning": "Classical ML",
    "cnn": "CNN", "transformer": "Transformer", "foundation_model": "Foundation model", "other": "Other",
}
NUM = {}


def short(x):
    return SHORT.get(x, x)


def num(name, value):
    """Register a macro for numbers.tex (name: letters only)."""
    NUM[name] = value
    return value


def fmt_int(n):
    return f"{int(n):,}"


def load():
    p = pd.read_csv(CORPUS / "papers.csv")
    p = p[p["eligible"]].drop_duplicates("doi").copy()
    p["year"] = p["year"].fillna(FIRST_YEAR).astype(int).clip(lower=FIRST_YEAR)
    t = {k: pd.read_parquet(CORPUS / f"{k}.parquet") for k in
         ("settings", "setting_countries", "setting_spectra", "setting_species", "species", "datasets", "tasks",
          "algorithms", "flags")}
    keep = set(p["doi"])
    for k, df in t.items():
        df = df[df["doi"].isin(keep)]
        t[k] = df[df["verified"]] if "verified" in df else df
    sp = t["species"]
    t["target"] = sp[(sp["role"] == "target") & sp["gbif_usageKey"].notna()]
    return p, t


def papers_per(df, col, n_total):
    """Number and share of papers per value of col (each paper counted once per value)."""
    c = df.drop_duplicates(["doi", col]).groupby(col)["doi"].nunique().sort_values(ascending=False)
    return pd.DataFrame({"papers": c, "share": c / n_total})


def top_numbers(prefix, c, k=5):
    """Macros for the k most frequent values: \\<prefix>A..E with Name, count and Pct."""
    for letter, (v, r) in zip("ABCDEFGHIJ", c.head(k).iterrows()):
        num(f"{prefix}{letter}Name", short(v))
        num(f"{prefix}{letter}", fmt_int(r["papers"]))
        num(f"{prefix}{letter}Pct", f"{100 * r['share']:.1f}")


def save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)


def barh(c, name, xlabel_n, top=None, italic=False, hatch=None):
    c = c.head(top) if top else c
    fig, ax = plt.subplots(figsize=(FULL_W, 0.32 * len(c) + 1))
    labels = [short(x) for x in c.index]
    bars = ax.barh(labels[::-1], 100 * c["share"].values[::-1], color=sns.color_palette("tab10")[0])
    if hatch is not None:
        for b, h in zip(bars, list(hatch.reindex(c.index).fillna(False))[::-1]):
            if h:
                b.set_hatch("///")
                b.set_facecolor(sns.color_palette("tab10")[7])
    for b, n in zip(bars, c["papers"].values[::-1]):
        ax.text(b.get_width() + 0.3, b.get_y() + b.get_height() / 2, fmt_int(n), va="center", fontsize=8)
    if italic:
        for t in ax.get_yticklabels():
            t.set_fontstyle("italic")
    ax.set_xlabel(f"Share of papers (%; n = {fmt_int(xlabel_n)})")
    ax.set_xlim(0, 100 * c["share"].max() * 1.15)
    save(fig, name)


def stacked_share(pairs, row, col, name, row_order=None, col_order=None, unit="settings", prefix=None):
    """100% stacked bars of col within each row value; labels: n pairs (n papers).
    With prefix, every cell becomes a macro \\<prefix><Row><Col>Pct (share of col within row)."""
    ct = pd.crosstab(pairs[row], pairs[col])
    papers = pairs.groupby(row)["doi"].nunique()
    if row_order is not None:
        ct = ct.reindex([r for r in row_order if r in ct.index])
    if col_order is not None:
        ct = ct[[c for c in col_order if c in ct.columns]]
    share = ct.div(ct.sum(1), axis=0) * 100
    if prefix:
        key = lambda x: re.sub(r"[^A-Za-z]", "", short(x).title())
        for r in share.index:
            num(f"{prefix}{key(r)}Links", fmt_int(ct.loc[r].sum()))
            for c in share.columns[ct.loc[r] > 0]:
                num(f"{prefix}{key(r)}{key(c)}Pct", f"{share.loc[r, c]:.1f}")
    fig, ax = plt.subplots(figsize=(13, 5.5))
    bottom = np.zeros(len(share))
    colors = sns.color_palette("tab20", len(share.columns))
    for c, colr in zip(share.columns, colors):
        ax.bar(range(len(share)), share[c], bottom=bottom, label=short(c), color=colr, edgecolor="white", lw=0.5)
        bottom += share[c].values
    ax.set_xticks(range(len(share)))
    ax.set_xticklabels([f"{short(r)}\n{fmt_int(ct.loc[r].sum())} ({fmt_int(papers[r])})" for r in share.index],
                       rotation=90)
    ax.set_ylabel(f"Share of {unit} (%)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.22), ncol=4, fontsize=9, frameon=True)
    save(fig, name)


def trend(df, col, name, table, title, categories=None):
    """Papers per year and category (log scale), OLS slope over FIRST_YEAR..LAST_FULL_YEAR with 95% CI.
    "Not reported" is left out (it is not a category whose trend means anything)."""
    df = df[df[col] != "Not reported"]
    years = list(range(FIRST_YEAR, int(df["year"].max()) + 1))
    ct = pd.crosstab(df.drop_duplicates(["doi", col])[col], df.drop_duplicates(["doi", col])["year"])
    ct = ct.reindex(columns=years, fill_value=0)
    if categories is not None:
        ct = ct.reindex([c for c in categories if c in ct.index])
    ct = ct.loc[ct.sum(1).sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    colors = sns.color_palette("tab20", len(ct))
    rows = []
    fit = [y for y in years if y <= LAST_FULL_YEAR]
    for (cat, r), colr in zip(ct.iterrows(), colors):
        ax.plot(fit, r[fit].replace(0, np.nan), marker="o", ms=3, color=colr, label=short(cat))
        if years[-1] > LAST_FULL_YEAR:
            ax.plot(years[-2:], r[years[-2:]].replace(0, np.nan), ls=":", color=colr)
        y = r[fit].values.astype(float)
        lr = stats.linregress(fit, y)
        tcrit = stats.t.ppf(0.975, len(fit) - 2)
        rows.append({"category": short(cat), "papers": int(r.sum()), "slope": lr.slope,
                     "lo": lr.slope - tcrit * lr.stderr, "hi": lr.slope + tcrit * lr.stderr, "r2": lr.rvalue ** 2,
                     "p": lr.pvalue})
    ax.set_yscale("log")
    ax.set_ylabel("Papers per year (log scale)")
    ax.set_xticks(years)
    ax.set_xticklabels([str(y) if y <= LAST_FULL_YEAR else f"{y}*" for y in years], rotation=45)
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=9)
    save(fig, name)
    t = pd.DataFrame(rows)
    for r in t.itertuples():
        k = "slope" + name.split("/")[-1].title() + re.sub(r"[^A-Za-z]", "", r.category.title())
        num(k, f"{r.slope:.1f}")
        num(k + "CI", f"{r.lo:.1f}--{r.hi:.1f}")
    TAB.mkdir(parents=True, exist_ok=True)
    lines = [r"\begin{tabular}{lrrrrl}", r"\toprule",
             rf"\textbf{{{title}}} & \textbf{{Papers}} & \textbf{{Slope}} & \textbf{{95% CI}} & $\mathbf{{R^2}}$ & "
             r"\textbf{$p$} \\", r"\midrule"]
    for r in t.itertuples():
        p = "$<$0.001" if r.p < 0.001 else f"{r.p:.3f}"
        lines.append(f"{r.category} & {fmt_int(r.papers)} & {r.slope:.1f} & [{r.lo:.1f}, {r.hi:.1f}] & {r.r2:.2f} & "
                     f"{p} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TAB / f"{table}.tex").write_text("\n".join(lines).replace("&", "&").replace("%", r"\%"), encoding="utf-8")
    return t


def fig_years(p):
    years = list(range(FIRST_YEAR, p["year"].max() + 1))
    tot = p["year"].value_counts().reindex(years, fill_value=0)
    fig, ax = plt.subplots(figsize=(FULL_W, 4))
    c = sns.color_palette("tab10")
    bars = ax.bar(years, tot.values, color=c[0])
    for b, y in zip(bars, years):
        if y > LAST_FULL_YEAR:   # incomplete year
            b.set_facecolor("white")
            b.set_edgecolor(c[0])
            b.set_hatch("///")
    for y, n in tot.items():
        ax.text(y, n + 8, fmt_int(n), ha="center", fontsize=8)
    ax.set_xticks(years)
    ax.set_xticklabels([str(y) if y <= LAST_FULL_YEAR else f"{y}*" for y in years], rotation=45)
    ax.set_ylabel("Papers")
    save(fig, "years")
    for y in years:
        num(f"papersYear{y}", fmt_int(tot[y]))


def fig_captivity(p):
    order = ["wild", "wild_and_captive", "captive", "not_reported"]
    labels = {"wild": "Wild", "wild_and_captive": "Wild and captive", "captive": "Captive",
              "not_reported": "Not reported"}
    years = list(range(FIRST_YEAR, p["year"].max() + 1))
    ct = pd.crosstab(p["year"], p["captivity"]).reindex(years, fill_value=0)[[o for o in order if o in
                                                                               set(p["captivity"])]]
    share = ct.div(ct.sum(1), axis=0) * 100
    fig, ax = plt.subplots(figsize=(8, 4))
    bottom = np.zeros(len(share))
    for o, colr in zip(share.columns, sns.color_palette("tab10")):
        ax.bar(years, share[o], bottom=bottom, label=labels[o], color=colr)
        bottom += share[o].values
    ax.set_xticks(years)
    ax.set_xticklabels([str(y) if y <= LAST_FULL_YEAR else f"{y}*" for y in years], rotation=45)
    ax.set_ylabel("Share of papers (%)")
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left")
    save(fig, "captivity_years")
    for o in order:
        k = re.sub(r"_(\w)", lambda m: m.group(1).upper(), o)
        num(f"captivity{k[0].upper() + k[1:]}", fmt_int((p["captivity"] == o).sum()))
        num(f"captivity{k[0].upper() + k[1:]}Pct", f"{100 * (p['captivity'] == o).mean():.1f}")


def taxa_figs(t, n):
    tg = t["target"]
    cls = papers_per(tg.dropna(subset=["taxon_class"]), "taxon_class", n)
    barh(cls, "class", n, top=20)
    for c in ("Mammalia", "Aves", "Actinopterygii", "Insecta", "Reptilia", "Amphibia", "Anthozoa"):
        if c in cls.index:
            num(f"class{c}", fmt_int(cls.loc[c, "papers"]))
            num(f"class{c}Pct", f"{100 * cls.loc[c, 'share']:.1f}")
    num("papersWithTaxon", fmt_int(tg["doi"].nunique()))
    for rank, top in (("gbif_order", 20), ("gbif_family", 20)):
        barh(papers_per(tg.dropna(subset=[rank]), rank, n), rank.split("_")[1], n, top=top)
    sp = tg.dropna(subset=["gbif_species"]).copy()
    # domestic forms share the species with their wild ancestor in the backbone (dog = Canis lupus); the
    # extraction's domestic flag keeps them apart
    sp["label"] = sp["gbif_species"] + np.where(sp["domestic"].fillna(False).astype(bool), " (domestic)", "")
    c = papers_per(sp, "label", n)
    barh(c, "species", n, top=30, italic=True, hatch=pd.Series(c.index.str.endswith("(domestic)"), index=c.index))
    top_numbers("topSpecies", c, 8)
    num("speciesDistinct", fmt_int(sp["gbif_species"].nunique()))
    num("papersWithSpecies", fmt_int(sp["doi"].nunique()))
    num("papersDomesticOnly", fmt_int(tg.groupby("doi")["domestic"].all().sum()))


def platform_class(t):
    st, ss, tg = t["settings"], t["setting_species"], t["target"][["doi", "name", "taxon_class"]].rename(
        columns={"taxon_class": "gbif_class"})
    m = ss.merge(tg[["doi", "name", "gbif_class"]], on=["doi", "name"]).merge(st[["doi", "setting", "platform"]],
                                                                            on=["doi", "setting"])
    m = m.dropna(subset=["gbif_class"]).drop_duplicates(["doi", "setting", "gbif_class"])
    top = m["gbif_class"].value_counts().head(9).index
    m["class"] = m["gbif_class"].where(m["gbif_class"].isin(top), "Other classes")
    order = m["platform"].value_counts().index
    stacked_share(m, "platform", "class", "platform_class", row_order=order,
                  col_order=list(top) + ["Other classes"], unit="setting-class links", prefix="pc")


def algorithms(t, p, n):
    a = t["algorithms"]
    # "own model" (new architecture without a recognisable base) is not a family; CNN = custom CNN
    named = a[a["generic"].eq(False) & a["family"].notna() & (a["family"] != "own model")]
    named = named.assign(family=named["family"].replace({"CNN": "Custom CNN"}))
    num("papersOwnModel", fmt_int(a[a["family"] == "own model"]["doi"].nunique()))
    fam = papers_per(named, "family", n)
    barh(fam, "algorithms", n, top=20)
    top_numbers("topAlgo", fam, 8)
    ty = a.merge(p[["doi", "year"]], on="doi").drop_duplicates(["doi", "type"])
    years = list(range(FIRST_YEAR, p["year"].max() + 1))
    per_year = p.groupby("year")["doi"].nunique().reindex(years)
    ct = pd.crosstab(ty["type"], ty["year"]).reindex(columns=years, fill_value=0)
    fig, ax = plt.subplots(figsize=(FULL_W, 4))
    for (typ, r), colr in zip(ct.iterrows(), sns.color_palette("tab10")):
        ax.plot(years, 100 * r / per_year, marker="o", ms=3, label=short(typ), color=colr)
    ax.set_ylabel("Share of papers (%)")
    ax.set_xticks(years)
    ax.set_xticklabels([str(y) if y <= LAST_FULL_YEAR else f"{y}*" for y in years], rotation=45)
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left")
    save(fig, "algorithm_type_year")
    for typ in ("transformer", "foundation_model", "cnn"):
        k = {"transformer": "Transformer", "foundation_model": "Foundation", "cnn": "Cnn"}[typ]
        for y in (2020, LAST_FULL_YEAR):
            num(f"algo{k}{y}Pct", f"{100 * ct.loc[typ, y] / per_year[y]:.1f}" if typ in ct.index else "0")


def datasets(t, n):
    d = t["datasets"]
    named = d[d["generic"].eq(False) & d["family"].notna() & (d["role"] != "pretraining_only")]
    fam = papers_per(named, "family", n)
    barh(fam, "dataset", n, top=20)
    top_numbers("topDataset", fam, 6)
    own = d[d["role"] == "collected_by_authors"]["doi"].nunique()
    pub = d[d["role"].isin(["public_wildlife_dataset", "generic_benchmark"])]["doi"].nunique()
    own_avail = d[(d["role"] == "collected_by_authors") & (d["availability"] == "public")]["doi"].nunique()
    num("papersOwnData", fmt_int(own))
    num("papersOwnDataPct", f"{100 * own / n:.1f}")
    num("papersPublicDataset", fmt_int(pub))
    num("papersPublicDatasetPct", f"{100 * pub / n:.1f}")
    num("papersOwnDataReleased", fmt_int(own_avail))
    num("papersOwnDataReleasedPct", f"{100 * own_avail / max(own, 1):.1f}")


def prisma(p_all):
    ta = pd.read_csv(V2 / "screening" / "ta_final.csv", low_memory=False)
    num("recordsScreened", fmt_int(len(ta)))
    for run, k in (("index_2014_2026", "Index"), ("libraries_2024_2026", "Libraries"), ("citations_hop1", "Citations"),
                   ("citations_hop2", "CitationsHopTwo")):
        num(f"recordsScreened{k}", fmt_int((ta["run"] == run).sum()))
    num("recordsExcludedTA", fmt_int((ta["final"] == "exclude").sum()))
    num("recordsInclude", fmt_int((ta["final"] == "include").sum()))
    num("recordsFulltext", fmt_int((ta["final"] == "fulltext").sum()))
    num("papersCoded", fmt_int(len(p_all)))
    num("papersEligible", fmt_int(p_all["eligible"].sum()))
    num("papersEligibleStrict", fmt_int(p_all["eligible_strict"].sum()))
    num("papersOldCorpusCoded", fmt_int(p_all["in_old_corpus"].sum()))
    num("papersOldCorpusEligible", fmt_int((p_all["in_old_corpus"] & p_all["eligible"]).sum()))
    ex = p_all[~p_all["eligible"]]["criterion"].value_counts()
    for c, v in ex.items():
        num("excludedFT" + re.sub(r"[^A-Za-z]", "", c.title()), fmt_int(v))
    num("excludedFT", fmt_int((~p_all["eligible"]).sum()))
    num("papersCaptiveAdded", fmt_int((p_all["eligible"] & ~p_all["eligible_strict"]).sum()))


def prisma_figure(p_all):
    """PRISMA 2020 flow diagram from the logged counts."""
    def lines(path):
        return sum(1 for _ in open(path, encoding="utf-8"))
    src = {json.loads(x)["source"]: json.loads(x)["stored"] for x in
           open(V2 / "search" / "retrieval_log.jsonl", encoding="utf-8")}
    libs = {k: lines(V2 / "search" / f"{k}.jsonl") for k in ("ieee", "sciencedirect", "wiley", "acm")}
    ta = pd.read_csv(V2 / "screening" / "ta_final.csv", low_memory=False)
    runs = ta["run"].value_counts()
    seeds, works = lines(V2 / "citations" / "hop1" / "seeds.jsonl"), lines(V2 / "citations" / "hop1" / "works.jsonl")
    seeds2, works2 = lines(V2 / "citations" / "hop2" / "seeds.jsonl"), lines(V2 / "citations" / "hop2" / "works.jsonl")
    passed = ta[ta["final"] != "exclude"]
    coded_scr = p_all[p_all["screening"].isin(["include", "fulltext"])]
    not_retrieved = len(passed) - len(coded_scr)
    old = p_all[p_all["screening"] == "not screened"]
    check = p_all[p_all["screening"] == "exclude"]
    assessed = len(p_all)
    excl = p_all[~p_all["eligible"]]["criterion"].value_counts()
    names = {"E-NOCV": "no image analysis", "E-LAB": "laboratory animals", "E-GENERIC": "no specific animals",
             "E-AGRI": "livestock / aquaculture", "E-CAPTIVE": "dead specimens", "E-PLANT": "plants / habitat only",
             "E-REVIEW": "review", "E-AUDIO": "audio only", "E-HUMAN": "humans", "E-YEAR": "outside 2014-2026",
             "none": "other"}
    num("prismaSeeds", fmt_int(seeds))
    num("prismaCitationWorks", fmt_int(works))
    num("prismaSeedsHopTwo", fmt_int(seeds2))
    num("prismaCitationWorksHopTwo", fmt_int(works2))
    num("prismaNotRetrieved", fmt_int(not_retrieved))
    num("prismaAssessed", fmt_int(assessed))
    num("prismaOldNotRefound", fmt_int(len(old)))
    # papers of the earlier search that went to full text without re-screening (already known): found by hand
    # (manual arm) or by the earlier automated citation search; how many of the latter the new searches found again
    manual = {norm_doi(d) for d in pd.read_parquet(ROOT / "review_output" / "gapminder" / "2026130_manual.parquet")
              ["doi"] if isinstance(d, str)}
    old_manual = old[old["doi"].isin(manual)]
    old_auto = old[~old["doi"].isin(manual)]
    found = set()
    for f in ("records.csv", "library_records.csv"):
        found |= {norm_doi(d) for d in pd.read_csv(V2 / "search" / f, usecols=["doi"], low_memory=False)["doi"]
                  if isinstance(d, str)}
    for hop in ("hop1", "hop2"):
        found |= {norm_doi(json.loads(x).get("doi") or "") for x in
                  open(V2 / "citations" / hop / "works.jsonl", encoding="utf-8")}
    num("prismaKnownManual", fmt_int(len(old_manual)))
    num("prismaKnownAuto", fmt_int(len(old_auto)))
    num("prismaKnownAutoRefound", fmt_int(old_auto["doi"].isin(found).sum()))
    num("prismaCheckSample", fmt_int(len(check)))
    label = {"scopus": "Scopus", "openalex": "OpenAlex", "pubmed": "PubMed", "ieee": "IEEE Xplore",
             "sciencedirect": "ScienceDirect", "wiley": "Wiley", "acm": "ACM"}
    n_excl_ft = len(p_all) - p_all["eligible"].sum()
    # three columns: sources and additions (left), main flow (centre), exclusions and losses (right)
    W, XL, XC, XR = 0.297, 0.197, 0.52, 0.843
    SRC, MAIN, EXCL, INCL = "#dbe8f5", "#ffffff", "#eeeeee", "#dcefd6"
    boxes = {   # key: (x centre, y centre, height, fill, heading, details)
        "index": (XL, 0.905, 0.15, SRC, "Index search, 2014–2026",
                  "\n".join(f"{label.get(k, k)}: {fmt_int(v)}" for k, v in src.items())
                  + f"\nAfter de-duplication: {fmt_int(runs.get('index_2014_2026', 0))}"),
        "library": (XC, 0.905, 0.15, SRC, "Library exports, 2024–2026",
                    "\n".join(f"{label.get(k, k)}: {fmt_int(v)}" for k, v in libs.items())
                    + f"\nNew records to screen: {fmt_int(runs.get('libraries_2024_2026', 0))}"),
        "citation": (XR, 0.905, 0.15, SRC, "Citation search",
                     f"OpenAlex, two hops\n"
                     f"Hop 1: {fmt_int(seeds)} seeds, {fmt_int(works)} works\n"
                     f"Hop 2: {fmt_int(seeds2)} seeds, {fmt_int(works2)} new\n"
                     f"To screen: {fmt_int(runs.get('citations_hop1', 0))} + "
                     f"{fmt_int(runs.get('citations_hop2', 0))}"),
        "screen": (XC, 0.70, 0.095, MAIN, "Title/abstract screening",
                   f"Two LLM screeners, adjudicator\nfor disagreements\nRecords screened: {fmt_int(len(ta))}"),
        "excluded": (XR, 0.70, 0.075, EXCL, "Excluded", f"{fmt_int((ta['final'] == 'exclude').sum())} records\n"
                                                        f"({fmt_int(len(check))} coded in full text as a check)"),
        "sought": (XC, 0.565, 0.07, MAIN, "Full texts sought",
                   f"{fmt_int(len(passed))} (include {fmt_int((ta['final'] == 'include').sum())}, "
                   f"unclear {fmt_int((ta['final'] == 'fulltext').sum())})"),
        "notret": (XR, 0.565, 0.06, EXCL, "Not retrieved", f"{fmt_int(not_retrieved)} records"),
        "auto": (XL, 0.575, 0.118, SRC, "Earlier automated\ncitation search",
                 f"Known papers, not re-screened:\n{fmt_int(len(old_auto))} "
                 f"({fmt_int(old_auto['doi'].isin(found).sum())} found again\nby the new searches)"),        "manual": (XL, 0.41, 0.085, SRC, "Earlier hand search",
                   f"Papers found and coded\nby hand: {fmt_int(len(old_manual))}"),
        "assessed": (XC, 0.43, 0.07, MAIN, "Full texts assessed and coded",
                     f"Frozen extraction protocol: {fmt_int(assessed)}"),
        "exft": (XR, 0.40, 0.23, EXCL, f"Excluded at full text: {fmt_int(n_excl_ft)}",
                 "\n".join(f"{names.get(k, k)}: {fmt_int(v)}" for k, v in excl.items())),
        "included": (XC, 0.215, 0.07, INCL, f"Included: {fmt_int(p_all['eligible'].sum())}",
                     f"wild {fmt_int(p_all['eligible_strict'].sum())}, captive added "
                     f"{fmt_int((p_all['eligible'] & ~p_all['eligible_strict']).sum())}"),
    }
    fig, ax = plt.subplots(figsize=(7.6, 7.4))
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0.165, 1)
    for x, y, h, fill, head, body in boxes.values():
        ax.add_patch(mpatches.FancyBboxPatch((x - W / 2, y - h / 2), W, h, boxstyle="round,pad=0,rounding_size=0.008",
                                             facecolor=fill, edgecolor="#333333", lw=0.8))
        top = y + h / 2 - 0.012
        ax.text(x, top, head, ha="center", va="top", fontsize=7.8, fontweight="bold", linespacing=1.15)
        ax.text(x, top - 0.021 * (head.count("\n") + 1), body, ha="center", va="top", fontsize=7.4,
                linespacing=1.25)
    # PRISMA phases on the left
    for y0, y1, name in ((0.825, 0.985, "Identification"), (0.26, 0.75, "Screening"), (0.175, 0.255, "Included")):
        ax.add_patch(mpatches.FancyBboxPatch((0.005, y0), 0.03, y1 - y0, boxstyle="round,pad=0,rounding_size=0.006",
                                             facecolor="#9fb8d3", edgecolor="none"))
        ax.text(0.02, (y0 + y1) / 2, name, rotation=90, ha="center", va="center", fontsize=7.8,
                fontweight="bold", color="white")

    def edge(k, side):
        x, y, h = boxes[k][:3]
        return {"top": (x, y + h / 2), "bottom": (x, y - h / 2), "left": (x - W / 2, y), "right": (x + W / 2, y)}[side]

    def arrow(*pts):
        xs, ys = zip(*pts)
        ax.plot(xs[:-1], ys[:-1], color="#333333", lw=0.9, solid_capstyle="butt")
        ax.annotate("", xy=pts[-1], xytext=pts[-2],
                    arrowprops={"arrowstyle": "-|>", "lw": 0.9, "color": "#333333", "shrinkA": 0, "shrinkB": 0})

    top_screen = edge("screen", "top")[1]
    for k, dx in (("index", -0.07), ("citation", 0.07)):
        x0, y0 = edge(k, "bottom")
        arrow((x0, y0), (x0, 0.795), (XC + dx, 0.795), (XC + dx, top_screen))
    arrow(edge("library", "bottom"), (XC, top_screen))
    arrow(edge("screen", "right"), edge("excluded", "left"))
    arrow(edge("screen", "bottom"), edge("sought", "top"))
    arrow(edge("sought", "right"), edge("notret", "left"))
    arrow(edge("sought", "bottom"), edge("assessed", "top"))
    gap = (XL + W / 2 + XC - W / 2) / 2   # vertical lane between the left and the centre column
    arrow(edge("auto", "right"), (gap, boxes["auto"][1]), (gap, 0.45), (XC - W / 2, 0.45))
    arrow(edge("manual", "right"), (XC - W / 2, boxes["manual"][1]))
    arrow(edge("assessed", "right"), (XR - W / 2, boxes["assessed"][1]))
    arrow(edge("assessed", "bottom"), edge("included", "top"))
    save(fig, "prisma")


def task_cooccurrence(t):
    """R4: tasks are not independent. Cell (A, B): share of papers with task A that also have task B (primary or
    auxiliary); 1 - cell is the 'A not B' share."""
    tk = t["tasks"][t["tasks"]["task"] != "Other"][["doi", "task"]].drop_duplicates()
    order = tk["task"].value_counts().index
    m = pd.crosstab(tk["doi"], tk["task"]).clip(upper=1)[order]
    co = (m.T @ m).astype(float)
    cond = co.div(np.diag(co), axis=0) * 100
    fig, ax = plt.subplots(figsize=(FULL_W, 6))
    sns.heatmap(cond, annot=True, fmt=".0f", cmap="Blues", vmin=0, vmax=100, cbar_kws={"label": "% of row papers"},
                ax=ax, annot_kws={"fontsize": 8})
    ax.set_yticklabels([f"{r} ({fmt_int(co.loc[r, r])})" for r in cond.index], rotation=0)
    ax.set_xlabel("... also has task")
    ax.set_ylabel("Papers with task (n)")
    save(fig, "task_cooccurrence")
    for a, b in (("Segmentation", "Detection"), ("Counting", "Detection"), ("Tracking", "Detection"),
                 ("Re-Identification", "Detection"), ("Pose Estimation", "Detection"),
                 ("Detection", "Classification")):
        num(f"co{re.sub('[^A-Za-z]', '', a)}{b}Pct", f"{cond.loc[a, b]:.1f}")


def habitat_by_origin(t, n):
    """R4: is the habitat missing mostly for web-scraped data? Share of papers without any habitat, by the origin
    of the image data the paper uses (a paper counts in every origin it uses)."""
    st = t["settings"]
    known = st[~st["habitat"].isin(["Not reported", "Other"])].groupby("doi").size()
    ds = t["datasets"][t["datasets"]["role"] != "pretraining_only"][["doi", "origin"]].drop_duplicates()
    ds["no_habitat"] = ~ds["doi"].isin(known.index)
    g = ds.groupby("origin").agg(papers=("doi", "nunique"), no_habitat=("no_habitat", "mean"))
    g = g.sort_values("no_habitat", ascending=False)
    labels = {"web_scraped": "Web-scraped", "citizen_science": "Citizen science", "field_deployment": "Field",
              "captive_or_lab": "Captive / lab", "mixed": "Mixed", "synthetic": "Synthetic",
              "not_stated": "Origin not stated"}
    fig, ax = plt.subplots(figsize=(FULL_W, 3.2))
    bars = ax.barh([labels.get(i, i) for i in g.index][::-1], 100 * g["no_habitat"].values[::-1],
                   color=sns.color_palette("tab10")[0])
    for b, k in zip(bars, g["papers"].values[::-1]):
        ax.text(b.get_width() + 0.5, b.get_y() + b.get_height() / 2, f"n = {fmt_int(k)}", va="center", fontsize=8)
    ax.set_xlabel("Papers without a reported habitat (%)")
    ax.set_xlim(0, 100)
    save(fig, "habitat_missing_by_origin")
    for o, r in g.iterrows():
        num(f"noHabitat{labels.get(o, o).title().replace(' ', '').replace('/', '').replace('-', '')}Pct",
            f"{100 * r['no_habitat']:.1f}")
    num("noHabitatAllPct", f"{100 * (1 - len(known) / n):.1f}")


def validation_numbers(t):
    vdir = V2 / "validation"
    f = vdir / "screening_accuracy.json"
    if f.exists():
        s = json.loads(f.read_text())
        c = s["calibration"]["eligible"]
        num("taSensitivity", f"{100 * c['sensitivity']['p']:.1f}")
        num("taSensitivityCI", f"{100 * c['sensitivity']['lo']:.1f}--{100 * c['sensitivity']['hi']:.1f}")
        num("taSpecificity", f"{100 * c['specificity']['p']:.1f}")
        num("taCalibrationN", fmt_int(s["calibration"]["n"]))
        num("screenerKappa", f"{s['screener_agreement']['kappa']:.2f}")
    f = vdir / "extraction_adjudicated.json"
    if f.exists():
        for field, r in json.loads(f.read_text()).items():
            k = "".join(w.title() for w in field.split("_"))
            for who in ("extraction", "manual"):
                for m in ("precision", "recall", "f1"):
                    num(f"adj{who.title()}{k}{m.title().replace('1', 'One')}", f"{r[who][m]['p']:.2f}")
    # 5.3 (redesigned 2026-10-26): the values Opus coded beyond the manual coding, rated by a human on the extracted
    # quote and by a second AI tool (Codex) on the full paper; rates over all extracted values
    f = vdir / "hallucination_v2" / "report.json"
    if f.exists():
        h = json.loads(f.read_text(encoding="utf-8"))
        num("hallValues", fmt_int(h["values_extracted"]))
        num("hallConfirmed", fmt_int(h["confirmed_by_manual"]))
        num("hallConfirmedPct", f"{100 * h['confirmed_by_manual'] / h['values_extracted']:.1f}")
        num("hallItems", fmt_int(h["auto_only"]))
        num("hallMappedExcluded", fmt_int(h.get("excluded_mapped_platform", 0)))
        for rater, k in (("human", "Human"), ("ai_codex", "Codex")):
            r = h["raters"].get(rater)
            if not r:
                continue
            a = r["all_items"]
            for m, mk in (("unsupported", "Unsupported"), ("not_supported", "NotSupported")):
                num(f"hall{k}{mk}Pct", f"{100 * a[m]['overall']:.2f}")
                num(f"hall{k}{mk}CI", f"{100 * a[m]['overall_lo']:.2f}--{100 * a[m]['overall_hi']:.2f}")
            c = r["counts"]
            num(f"hall{k}Unclear", fmt_int(c.get("unclear", 0)))
            num(f"hall{k}SupportedPct", f"{100 * c.get('supported', 0) / sum(c.values()):.1f}")
        ag = h["agreement"].get("human_vs_ai_codex")
        if ag:
            num("hallAgreementPct", f"{100 * ag['agreement']['p']:.1f}")
    f = vdir / "corrected_shares.json"
    if f.exists():
        for field, r in json.loads(f.read_text()).items():
            k = "".join(w.title() for w in field.split("_"))
            for v, x in r.items():
                kv = re.sub(r"[^A-Za-z]", "", short(v).title())
                num(f"corr{k}{kv}Pct", f"{100 * x['corrected']:.1f}")
                num(f"corr{k}{kv}CI", f"{100 * x['lo']:.1f}--{100 * x['hi']:.1f}")
    f = vdir / "citation_coverage.json"
    if f.exists():
        c = json.loads(f.read_text())
        num("covIndexArmPct", f"{100 * c['index_arm']['p']:.1f}")
        num("covCitationArmPct", f"{100 * c['citation_arm']['p']:.1f}")
        num("covOneLinkPct", f"{100 * c['seed_bias']['one_link_only']['p']:.1f}")
        num("covMedianLinks", f"{c['seed_bias']['median_links']:.0f}")
        lo = c["leave_one_out_manual_arm"]
        num("covLooManualPct", f"{100 * lo['p']:.1f}")
        num("covLooManualN", fmt_int(lo["n"]))
        for k, x in c["capture_recapture"].items():
            kk = {"all": "All", "2014-2023": "Early", "2024-2026": "Late"}[k]
            num(f"cr{kk}Estimate", fmt_int(round(x["estimate"])))
            num(f"cr{kk}CoveredPct", f"{100 * x['covered_share']:.1f}")
            num(f"cr{kk}CoveredRange", f"{100 * x['covered_share_range'][0]:.1f}--{100 * x['covered_share_range'][1]:.1f}")
    f = V2 / "extraction" / "platform_check.json"
    if f.exists():
        v = [x["verdict"] for g in json.loads(f.read_text(encoding="utf-8")).values() for x in g
             if x["value"] != "Other"]
        num("platformPassChecked", fmt_int(len(v)))
        num("platformPassUnsupportedPct", f"{100 * v.count('unsupported') / len(v):.1f}")
        num("platformPassSettings", fmt_int((t["settings"]["platform_source"] == "platform_pass").sum()))
    for name, macro in (("extraction_agreement.json", "agree"), ("stability.json", "stab")):
        f = vdir / name
        if f.exists():
            for field, r in json.loads(f.read_text())["fields"].items():
                k = "".join(w.title() for w in field.split("_"))
                num(f"{macro}{k}FOne", f"{r['f1']['p']:.2f}")


AGREE_FIELDS = [("platform", "Platform"), ("spectrum", "Spectrum"), ("habitat", "Habitat"), ("country", "Country"),
                ("taxon_class", "Taxonomic class"), ("taxon_genus", "Genus"), ("taxon_species", "Species"),
                ("task", "Task"), ("algorithm", "Algorithm family"), ("own_data", "Own data"),
                ("public_dataset", "Public dataset")]


def agreement_raw_table():
    """Reviewer 2 (R2.1b): raw agreement of the extraction with the manual coding, per field: matched and unmatched
    values, precision and recall with paper-level bootstrap intervals, F1 for verified and for all items, share of
    papers with identical value sets and unmatched values per paper (appendix table)."""
    f = V2 / "validation" / "extraction_agreement.json"
    if not f.exists():
        return
    r = json.loads(f.read_text())
    lines = [r"\begin{tabular}{lrrrcccccc}", r"\toprule",
             r" & \multicolumn{3}{c}{\textbf{Values}} & \multicolumn{3}{c}{\textbf{Verified values}} & "
             r"\textbf{All values} & \textbf{Identical} & \textbf{Unmatched} \\",
             r"\cmidrule(lr){2-4}\cmidrule(lr){5-7}",
             r"\textbf{Field} & \textbf{Both} & \textbf{Extr.} & \textbf{Manual} & \textbf{P (95\% CI)} & "
             r"\textbf{R (95\% CI)} & \textbf{F1} & \textbf{F1} & \textbf{papers (\%)} & \textbf{per paper} \\",
             r"\midrule"]
    tot = {"tp": 0, "fp": 0, "fn": 0}
    for field, label in AGREE_FIELDS:
        x, a = r["fields"][field], r["all_items"][field]
        for k in tot:
            tot[k] += x[k]
        unm = (x["fp"] + x["fn"]) / x["papers"]
        k = "".join(w.title() for w in field.split("_"))
        num(f"agree{k}Precision", f"{x['precision']['p']:.2f}")
        num(f"agree{k}Recall", f"{x['recall']['p']:.2f}")
        num(f"agree{k}IdenticalPct", f"{100 * x['identical']['p']:.1f}")
        num(f"agree{k}UnmatchedPerPaper", f"{unm:.2f}")
        lines.append(f"{label} & {x['tp']:,} & {x['fp']:,} & {x['fn']:,} & "
                     f"{x['precision']['p']:.2f} ({x['precision']['lo']:.2f}--{x['precision']['hi']:.2f}) & "
                     f"{x['recall']['p']:.2f} ({x['recall']['lo']:.2f}--{x['recall']['hi']:.2f}) & "
                     f"{x['f1']['p']:.2f} & {a['f1']['p']:.2f} & {100 * x['identical']['p']:.1f} & {unm:.2f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TAB / "agreement_raw.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    n = r["papers_compared"]
    num("agreeUnmatchedPerPaper", f"{(tot['fp'] + tot['fn']) / n:.1f}")
    num("agreeExtractionOnlyPerPaper", f"{tot['fp'] / n:.1f}")
    num("agreeManualOnlyPerPaper", f"{tot['fn'] / n:.1f}")


def arm_composition(p, t, n):
    """Reviewer 2 (seed bias): do the papers found only through citations differ from those found by the index and
    library searches? Share of papers per category in each group, for the five most frequent categories of each
    field, with a two-proportion z-test of the difference (Holm-corrected over all rows)."""
    f = V2 / "validation" / "coverage_arms.csv"
    if not f.exists():
        return
    arms = pd.read_csv(f).set_index("doi")
    arms = arms[arms.index.isin(set(p["doi"]))]
    groups = {"index": set(arms.index[arms["in_index"]]),
              "citation": set(arms.index[~arms["in_index"] & arms["in_citation"]])}
    num("armIndexN", fmt_int(len(groups["index"])))
    num("armCitationOnlyN", fmt_int(len(groups["citation"])))
    num("armNeitherN", fmt_int(len(p) - len(groups["index"] | groups["citation"])))
    st = t["settings"]
    fields = [("Platform", st[~st["platform"].isin(["Not reported", "Other"])][["doi", "platform"]]),
              ("Spectral band", t["setting_spectra"][["doi", "spectrum"]]),
              ("Habitat", st[~st["habitat"].isin(["Not reported", "Other"])][["doi", "habitat"]]),
              ("Taxonomic class", t["target"][["doi", "taxon_class"]].dropna()),
              ("Task", t["tasks"][(t["tasks"]["role"] == "primary") & (t["tasks"]["task"] != "Other")][["doi", "task"]])]
    rows = []
    for field, df in fields:
        df = df.drop_duplicates()
        col = df.columns[1]
        for cat in df[col].value_counts().head(5).index:
            d = set(df[df[col] == cat]["doi"])
            k1, n1 = len(d & groups["index"]), len(groups["index"])
            k2, n2 = len(d & groups["citation"]), len(groups["citation"])
            p1, p2 = k1 / n1, k2 / n2
            pp = (k1 + k2) / (n1 + n2)
            se = (pp * (1 - pp) * (1 / n1 + 1 / n2)) ** 0.5
            z = (p1 - p2) / se if se else 0.0
            pv = math.erfc(abs(z) / 2 ** 0.5)
            rows.append({"field": field, "category": short(cat), "index": 100 * p1, "citation": 100 * p2,
                         "diff": 100 * (p1 - p2), "p": pv})
    for field, d in (("Published 2024--2026", set(p[p["year"] >= 2024]["doi"])),):
        p1, p2 = len(d & groups["index"]) / len(groups["index"]), len(d & groups["citation"]) / len(groups["citation"])
        num("armIndexLatePct", f"{100 * p1:.1f}")
        num("armCitationOnlyLatePct", f"{100 * p2:.1f}")
    r = pd.DataFrame(rows)
    # Holm correction over all rows
    order = r["p"].sort_values().index
    m, adj, run = len(r), pd.Series(index=r.index, dtype=float), 0.0
    for i, idx in enumerate(order):
        run = max(run, min(1.0, (m - i) * r.loc[idx, "p"]))
        adj[idx] = run
    r["p_holm"] = adj
    num("armRowsSignificant", str(int((r["p_holm"] < 0.05).sum())))
    num("armRows", str(m))
    num("armMaxAbsDiff", f"{r['diff'].abs().max():.1f}")
    for _, x in r.iterrows():
        k = re.sub(r"[^A-Za-z]", "", x["field"].title()) + re.sub(r"[^A-Za-z]", "", x["category"].title())
        num(f"arm{k}IndexPct", f"{x['index']:.1f}")
        num(f"arm{k}CitationPct", f"{x['citation']:.1f}")
    lines = [r"\begin{tabular}{llrrr}", r"\toprule",
             r"\textbf{Field} & \textbf{Category} & \textbf{Index arm (\%)} & \textbf{Citations only (\%)} & "
             r"\textbf{Difference (pp)} \\", r"\midrule"]
    for field, g in r.groupby("field", sort=False):
        for i, (_, x) in enumerate(g.iterrows()):
            star = "*" if x["p_holm"] < 0.05 else ""
            diff = (f"{x['diff']:+.1f}" if abs(x["diff"]) >= 0.05 else "0.0").replace("-", "$-$")
            lines.append(f"{field if i == 0 else ''} & {x['category']} & {x['index']:.1f} & {x['citation']:.1f} & "
                         f"{diff}{star} \\\\")
        lines.append(r"\addlinespace")
    lines[-1] = r"\bottomrule"
    lines.append(r"\end{tabular}")
    (TAB / "arm_composition.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(r.round(3).to_string())


def revision_numbers(p, p_all, t, n):
    """Numbers asked for by the reviewer check of 2026-10-27 (sample sizes, left-out values, scope, benchmarks)."""
    vdir = V2 / "validation"
    num("papersScopeDropped", fmt_int(p_all["scope_dropped"].sum()))
    num("papersScopeDroppedSpecimen", fmt_int((p_all["scope_dropped"] & p_all["criterion"].isin(["E-CAPTIVE", "E-AGRI"])).sum()))
    num("papersScopeDroppedYear", fmt_int((p_all["scope_dropped"] & (p_all["criterion"] == "E-YEAR")).sum()))
    # papers without any verified setting count in every denominator but in no setting-based category
    no_set = n - t["settings"]["doi"].nunique()
    num("papersNoSetting", fmt_int(no_set))
    num("papersNoSettingPct", f"{100 * no_set / n:.1f}")
    # domestic forms among the targets
    tg = t["target"]
    dom = set(tg[tg["domestic"]]["doi"])
    wild = set(tg[~tg["domestic"]]["doi"])
    num("papersDomesticAny", fmt_int(len(dom)))
    num("papersDomesticAnyPct", f"{100 * len(dom) / n:.1f}")
    num("papersDomesticWithWildPct", f"{100 * len(dom & wild) / max(len(dom), 1):.1f}")
    # marine invertebrate classes and the two underwater benchmarks that label them
    ds = t["datasets"]
    bench = set(ds[ds["family"].fillna(ds["canonical"]).astype(str).str.contains(r"^(?:URPC|DUO|RUOD)", regex=True)]["doi"])
    shares = {}
    for c in ("Asteroidea", "Echinoidea", "Holothuroidea", "Bivalvia"):
        d = set(tg[tg["taxon_class"] == c]["doi"])
        if d:
            shares[c] = 100 * len(d & bench) / len(d)
    if shares:
        num("invertBenchmarkLowPct", f"{min(shares.values()):.0f}")
        num("invertBenchmarkHighPct", f"{max(shares.values()):.0f}")
    f = vdir / "extraction_agreement.json"
    if f.exists():
        num("agreePapersN", fmt_int(json.loads(f.read_text())["papers_compared"]))
    f = vdir / "extraction_adjudicated.json"
    if f.exists():
        r = json.loads(f.read_text())
        num("adjFieldsN", str(len(r)))
        better = [k for k, x in r.items() if x["extraction"]["f1"]["p"] > x["manual"]["f1"]["p"]]
        num("adjFieldsExtractionBetter", str(len(better)))
        num("adjExtractionMinPrecision", f"{min(x['extraction']['precision']['p'] for x in r.values()):.2f}")
        items = pd.read_csv(vdir / "extraction_agreement_items.csv")
        adj = pd.DataFrame([x for g in (vdir / "adjudication").glob("*.json")
                            for x in json.loads(g.read_text(encoding="utf-8"))["items"]])
        adj = adj[adj["doi"].isin(set(items["doi"]))]
        num("adjDisputed", fmt_int(len(adj)))
        num("adjUnclear", fmt_int((adj["verdict"] == "unclear").sum()))
        num("adjUnclearPct", f"{100 * (adj['verdict'] == 'unclear').mean():.1f}")
    f = vdir / "hallucination_v2" / "report.json"
    if f.exists():
        h = json.loads(f.read_text(encoding="utf-8"))
        num("hallPapers", fmt_int(h["papers"]))
        num("hallRated", fmt_int(h["auto_only"] - h.get("excluded_mapped_platform", 0)))
    ta = pd.read_csv(V2 / "screening" / "ta_final.csv", usecols=["stage"], low_memory=False)
    num("taWidenedCaptive", fmt_int((ta["stage"] == "widened scope (captive)").sum()))
    num("taReadjudicated", fmt_int((ta["stage"] == "re-adjudicated exclusion").sum()))
    f = vdir / "screening_accuracy.json"
    if f.exists():
        num("taMissedPct", f"{100 - 100 * json.loads(f.read_text())['calibration']['eligible']['sensitivity']['p']:.1f}")
        m = json.loads(f.read_text())["manual"]["manual_include_eligible_v2"]["two_screeners_passed"]
        num("taManualN", fmt_int(m["n"]))
        num("taManualPassed", fmt_int(m["k"]))
        num("taManualPassedPct", f"{100 * m['p']:.1f}")
        num("taManualPassedCI", f"{100 * m['lo']:.1f}--{100 * m['hi']:.1f}")
    f = vdir / "stability.json"
    if f.exists():
        s = json.loads(f.read_text())
        num("stabPapers", fmt_int(s["papers"]))
        num("stabSameInclude", fmt_int(s["same_include"]["k"]))
    f = vdir / "citation_coverage.json"
    if f.exists():
        c = json.loads(f.read_text())
        num("crMissedPct", f"{100 * (1 - min(1.0, c['capture_recapture']['all']['covered_share'])):.1f}")
        for k, x in c.get("publishers", {}).items():
            kk = k.title()
            num(f"pub{kk}Eligible", fmt_int(x["eligible"]))
            num(f"pub{kk}EligiblePct", f"{100 * x['eligible'] / n:.1f}")
            num(f"pub{kk}InIndex", fmt_int(x["in_index"]))
            num(f"pub{kk}InCitation", fmt_int(x["in_citation"]))
    f = vdir / "review_overlap.json"
    if f.exists():
        # studies cited by the earlier reviews of Table 1 (2014-2026, with DOI) that are in the corpus
        o = {k: v for k, v in json.loads(f.read_text()).items() if v.get("refs")}
        for k, v in o.items():
            kk = re.sub(r"[^A-Za-z0-9]", "", k).title()
            num(f"ovl{kk}Refs", fmt_int(v["refs_2014_2026"]))
            num(f"ovl{kk}Corpus", fmt_int(v["in_corpus"]))
        r = pd.read_csv(vdir / "review_overlap_refs.csv").drop_duplicates("doi")
        num("ovlRefs", fmt_int(len(r)))
        for s, kk in (("eligible", "Corpus"), ("coded, not eligible", "Coded"), ("screened, not coded", "Screened"),
                      ("not found", "NotFound")):
            num(f"ovl{kk}", fmt_int((r["status"] == s).sum()))
            num(f"ovl{kk}Pct", f"{100 * (r['status'] == s).mean():.1f}")
        num("ovlReviews", str(len(o)))
    f = vdir / "domestic_role.json"
    if f.exists():
        d = json.loads(f.read_text())
        num("domCheckPapers", fmt_int(d["papers"]))
        num("domCheckTaxa", fmt_int(d["checked"]))
        num("domCheckSubjectPct", f"{100 * d['subject']['p']:.1f}")
        num("domCheckSubjectCI", f"{100 * d['subject']['lo']:.1f}--{100 * d['subject']['hi']:.1f}")
        for k in ("benchmark_class", "mentioned", "unclear"):
            num("domCheck" + "".join(w.title() for w in k.split("_")), fmt_int(d["counts"].get(k, 0)))
        num("domCheckPapersAfter", fmt_int(d["papers_domestic_after_check"]))
        num("domCheckOnlyAfter", fmt_int(d["papers_domestic_only_after_check"]))


def taxon_naming(p):
    """Taxon naming per paper (taxa/naming.py): scientific names in the text, common names only, or mixed."""
    f = CORPUS.parent / "taxa" / "naming_papers.csv"
    if not f.exists():
        return
    nm = p[["doi"]].merge(pd.read_csv(f), on="doi", how="left")
    for col, pre in (("taxon_naming", "naming"), ("taxon_naming_species", "namingSpecies")):
        for v in ("scientific", "common", "mixed", "not applicable"):
            k = pre + "".join(w.title() for w in v.split())
            num(k, fmt_int((nm[col] == v).sum()))
            num(k + "Pct", f"{100 * (nm[col] == v).mean():.1f}")
    f = CORPUS.parent / "taxa" / "naming_llm.csv"   # Opus check of the labels (taxa/naming_pass.py)
    if f.exists():
        lb = p[["doi"]].merge(pd.read_csv(f), on="doi", how="left")
        for col, pre, vals in (("label_naming", "labels", ("scientific", "common", "both", "not applicable")),
                               ("scientific_given", "sciGiven", ("all", "some", "none", "not applicable"))):
            for v in vals:
                k = pre + "".join(w.title() for w in v.split())
                num(k, fmt_int((lb[col] == v).sum()))
                num(k + "Pct", f"{100 * (lb[col] == v).mean():.1f}")


def write_numbers():
    lines = ["% generated by src/review_v2/figures/make_figures.py; do not edit"]
    for k, v in sorted(NUM.items()):
        k = re.sub(r"\d", lambda m: "ABCDEFGHIJ"[int(m.group())], k)  # TeX macro names cannot contain digits
        lines.append(f"\\newcommand{{\\{k}}}{{{v}}}")
    NUMBERS.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sns.set_theme(style="darkgrid", context="paper", font_scale=1.2)
    p_all = pd.read_csv(CORPUS / "papers.csv").drop_duplicates("doi")
    p, t = load()
    n = num("papersN", len(p))
    NUM["papersN"] = fmt_int(n)
    prisma(p_all)
    prisma_figure(p_all)
    fig_years(p)
    fig_captivity(p)
    taxon_naming(p)

    st = t["settings"].merge(p[["doi", "year"]], on="doi")
    plat = papers_per(st, "platform", n)
    barh(plat, "imaging_method", n)
    hab = papers_per(st, "habitat", n)
    barh(hab, "habitats", n)
    spec = papers_per(t["setting_spectra"], "spectrum", n)
    barh(spec, "spectra", n)
    tasks = t["tasks"][t["tasks"]["role"] == "primary"]
    barh(papers_per(tasks, "task", n), "cv_tasks", n)
    ctry = t["setting_countries"]
    cc = papers_per(ctry[ctry["country"] != "Global / web"], "country", n)
    barh(cc, "countries", n, top=25)
    top_numbers("topCountry", cc, 8)
    num("papersWithCountry", fmt_int(ctry[ctry["country"] != "Global / web"]["doi"].nunique()))
    num("countriesDistinct", fmt_int(cc.shape[0]))
    for name, c in (("platform", plat), ("habitat", hab), ("spectrum", spec),
                    ("task", papers_per(tasks, "task", n))):
        for v, r in c.iterrows():
            k = name + re.sub(r"[^A-Za-z]", "", short(v).title())
            num(k, fmt_int(r["papers"]))
            num(k + "Pct", f"{100 * r['share']:.1f}")

    stacked_share(st, "platform", "habitat", "imaging_method_habitat", row_order=plat.index, prefix="ph")
    sh = t["setting_spectra"].merge(st[["doi", "setting", "habitat"]], on=["doi", "setting"])
    stacked_share(sh, "spectrum", "habitat", "spectrum_habitat", row_order=spec.index, prefix="sh")
    th = tasks[["doi", "task"]].drop_duplicates().merge(st[["doi", "habitat"]].drop_duplicates(), on="doi")
    stacked_share(th, "task", "habitat", "cv_task_habitat", unit="paper-level task-habitat links")
    taxa_figs(t, n)
    platform_class(t)
    algorithms(t, p, n)
    datasets(t, n)

    (FIG / "trends").mkdir(parents=True, exist_ok=True)
    trend(st, "platform", "trends/modality", "regression_modality", "Imaging method")
    trend(st, "habitat", "trends/habitats", "regression_habitat", "Habitat")
    trend(tasks.merge(p[["doi", "year"]], on="doi"), "task", "trends/task", "regression_task", "CV task")
    fl = t["flags"]
    for k in ("cost_reported", "ethics_statement", "explainability"):
        kk = "".join(w.title() for w in k.split("_"))
        num(f"flag{kk}", fmt_int(fl[k].sum()))
        num(f"flag{kk}Pct", f"{100 * fl[k].mean():.1f}")
    task_cooccurrence(t)
    habitat_by_origin(t, n)
    validation_numbers(t)
    revision_numbers(p, p_all, t, n)
    arm_composition(p, t, n)
    agreement_raw_table()
    write_numbers()
    print(f"{len(list(FIG.rglob('*.pdf')))} figures in {FIG}, {len(NUM)} numbers in {NUMBERS}")
