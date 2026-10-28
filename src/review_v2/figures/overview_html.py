"""Interactive overview page of the corpus (index.html of the GitHub Pages site).

Usage: python src/review_v2/figures/overview_html.py [out.html]   (after corpus/tables.py)

One row per eligible paper, with the verified values of the corpus tables as the paper uses them
(make_figures.load): settings, spectra, countries, tasks, algorithms, datasets and the GBIF-matched target taxa.
The page itself is written by the generator of the first version (review/visualization/html/to_html.py).
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.figures.make_figures import ROOT, load  # noqa: E402
from review.visualization.html.to_html import generate_html  # noqa: E402

CAPTIVITY = {"wild": "Wild", "captive": "Captive", "wild_and_captive": "Wild and captive",
             "not_reported": "Not reported"}


def per_paper(df, col, name, dois):
    """Sorted list of the distinct values of col per paper; papers without a value get an empty list."""
    s = df.dropna(subset=[col]).drop_duplicates(["doi", col]).groupby("doi")[col].agg(lambda v: sorted(map(str, v)))
    return s.reindex(dois).apply(lambda v: v if isinstance(v, list) else []).rename(name)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "index.html"
    p, t = load()
    p = p.sort_values(["year", "doi"], ascending=[False, True])
    dois = p["doi"]
    alg = t["algorithms"]
    ds = t["datasets"]
    tg = t["target"]
    df = pd.DataFrame({"doi": dois.values, "title": p["title"].values, "year": p["year"].astype(str).values,
                       "Venue": p["venue"].values, "Paper type": p["paper_type"].str.capitalize().values,
                       "Setting": p["captivity"].map(CAPTIVITY).values})
    cols = [per_paper(t["settings"], "platform", "Imaging Method", dois),
            per_paper(t["setting_spectra"], "spectrum", "Light Spectra", dois),
            per_paper(t["settings"], "habitat", "Habitat", dois),
            per_paper(t["setting_countries"], "country", "Country", dois),
            per_paper(t["tasks"][t["tasks"]["role"] == "primary"], "task", "CV Tasks", dois),
            per_paper(alg, "type", "Algorithm Type", dois),
            per_paper(alg[alg["role"] == "proposed"], "family", "CV Algorithms (proposed)", dois),
            per_paper(ds[ds["generic"] != 1], "canonical", "Dataset", dois)]
    for c, name in (("gbif_phylum", "Phylum"), ("taxon_class", "Class"), ("gbif_order", "Order"),
                    ("gbif_family", "Family"), ("gbif_genus", "Genus"), ("gbif_species", "Species")):
        cols.append(per_paper(tg, c, name, dois))
    for c in cols:
        df[c.name] = c.values
    generate_html(df, str(out), title=f"Computer Vision in Wildlife Conservation: {len(df):,} papers, "
                                      f"{df['year'].min()}-{df['year'].max()}", year_column="year")
    print(f"{len(df)} papers -> {out}")
