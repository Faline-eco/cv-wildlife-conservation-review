"""Reviewer 4: overlap of the corpus with the studies reviewed by the earlier surveys of Table 1.

Usage: python src/review_v2/validation/review_overlap.py

For each earlier review, its reference list is taken from OpenAlex (looked up by DOI, otherwise by title) as a proxy
for the studies it reviewed. References published 2014-2026 are matched by DOI to (a) the eligible corpus, (b) the
papers coded in full text, (c) the records screened at title and abstract. A reference in (c) but not in the corpus
was found by our search and excluded; a reference outside (c) was not found by our search. Reviews without a reference
list in OpenAlex are taken from validation/review_overlap_manual/<key>.txt if present (DOIs from the reference
list of the PDF), otherwise reported as such.
Output: validation/review_overlap.json, validation/review_overlap_refs.csv
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.citations.fetch_citations import API, get, short  # noqa: E402
from review_v2.search.fetch import load_env  # noqa: E402
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402

V2 = ROOT / "review_output" / "v2"
OUT = V2 / "validation"

REVIEWS = [  # bib key, DOI if known, title
    ("weinstein2018computer", "10.1111/1365-2656.12780", "A computer vision for animal ecology"),
    ("Schneider2019", "10.1111/2041-210x.13133", "Past, present and future approaches using computer vision for "
                                                  "animal re-identification from camera trap data"),
    ("Magness2018", "10.1007/978-3-319-96978-7_14", "Image Recognition in Wildlife Applications"),
    ("nazir2021advances", None, "Advances in image acquisition and processing technologies transforming animal "
                                "ecological studies"),
    ("ferrante2021understanding", None, "Understanding the state of the Art in Animal detection and classification "
                                        "using computer vision technologies"),
    ("Hye2021", "10.1073/pnas.2002545117", "Deep learning and computer vision will transform entomology"),
    ("9774826", "10.1109/icter53630.2021.9774826", "Detection of Wildlife Animals using Deep Learning Approaches: "
                                                   "A Systematic Review"),
    ("neupane2022literature", None, "A literature review of computer vision techniques in wildlife monitoring"),
    ("petso2022review", None, "Review on methods used for wildlife species and individual identification"),
    ("barbedo2022review", None, "A review on the use of computer vision and artificial intelligence for fish "
                                "recognition, monitoring, and management"),
    ("Xu2024", "10.1016/j.jag.2024.103732", "A review of deep learning techniques for detecting animals in aerial "
                                            "and satellite images"),
]
SELECT = "id,doi,title,publication_year,referenced_works"


def lookup(doi, title):
    if doi:
        r = get(API, {"filter": f"doi:https://doi.org/{doi}", "select": SELECT})
        r.raise_for_status()
        if r.json()["results"]:
            return r.json()["results"][0]
    r = get(API, {"filter": "title.search:" + title.replace(",", " ").replace(":", " "), "select": SELECT,
                  "per-page": 5})
    r.raise_for_status()
    res = [w for w in r.json()["results"] if (w.get("title") or "").lower().strip(". ") == title.lower().strip(". ")]
    return max(res, key=lambda w: len(w["referenced_works"])) if res else None


def works(ids):
    rows = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        r = get(API, {"filter": "openalex:" + "|".join(chunk), "select": "id,doi,publication_year,type",
                      "per-page": 50})
        r.raise_for_status()
        rows += r.json()["results"]
    return rows


if __name__ == "__main__":
    load_env()
    p = pd.read_csv(V2 / "corpus" / "papers.csv")
    eligible, coded = set(p[p["eligible"]]["doi"]), set(p["doi"])
    screened = set(pd.read_csv(V2 / "screening" / "ta_final.csv", usecols=["doi"], low_memory=False)["doi"]
                   .dropna().map(norm_doi))
    res, refs = {}, []
    for key, doi, title in REVIEWS:
        w = lookup(doi, title)
        manual = OUT / "review_overlap_manual" / f"{key}.txt"
        if (not w or not w["referenced_works"]) and manual.exists():
            # reference list read from the PDF: reference number, year, DOI (already 2014-2026)
            rows = [x.split("\t") for x in manual.read_text(encoding="utf-8").splitlines()
                    if x.strip() and not x.startswith("#")]
            d = {norm_doi(x[2]) for x in rows}
            r = {"found": True, "source": "pdf reference list", "refs": len(rows)}
        elif not w or not w["referenced_works"]:
            res[key] = {"found": bool(w), "refs": 0}
            print(f"{key:28s} no reference list in OpenAlex")
            continue
        else:
            ws = works([short(x) for x in w["referenced_works"]])
            window = [x for x in ws if x.get("publication_year") and 2014 <= x["publication_year"] <= 2026
                      and x.get("doi")]
            d = {norm_doi(x["doi"]) for x in window}
            r = {"found": True, "openalex": short(w["id"]), "refs": len(w["referenced_works"])}
        r |= {"refs_2014_2026": len(d), "in_corpus": len(d & eligible), "coded_not_eligible": len(d & coded - eligible),
             "screened_not_coded": len(d & screened - coded), "not_found": len(d - screened - coded)}
        res[key] = r
        refs += [{"review": key, "doi": x, "status": "eligible" if x in eligible else "coded, not eligible"
                  if x in coded else "screened, not coded" if x in screened else "not found"} for x in sorted(d)]
        print(f"{key:28s} refs {r['refs']:4d}  2014-26 {r['refs_2014_2026']:4d}  corpus {r['in_corpus']:4d}  "
              f"excluded at full text {r['coded_not_eligible']:3d}  excluded/not retrieved {r['screened_not_coded']:3d}"
              f"  not found {r['not_found']:3d}")
    (OUT / "review_overlap.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    pd.DataFrame(refs).to_csv(OUT / "review_overlap_refs.csv", index=False, encoding="utf-8")
