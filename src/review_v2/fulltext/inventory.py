"""Which papers have a PDF in the local Zotero library?

Reads a copy of zotero.sqlite (the live file is locked while Zotero runs) and writes
review_output/v2/fulltext/zotero_pdfs.csv with one row per DOI and PDF attachment.
PDFs whose Zotero item has no DOI are matched by the old file-name convention (DOI without slashes).
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from review_v2.search.merge import ROOT, norm_doi  # noqa: E402
from review_v2.fulltext.prepare import PDF_STORE  # noqa: E402

ZOTERO = Path(os.environ.get("ZOTERO_DIR", Path.home() / "Zotero"))
OUT = ROOT / "review_output" / "v2" / "fulltext"

SQL = """
SELECT v.value AS doi, a.key AS att_key, ia.path AS path, p.key AS item_key
FROM itemAttachments ia
JOIN items a ON a.itemID = ia.itemID
JOIN items p ON p.itemID = ia.parentItemID
JOIN itemData d ON d.itemID = p.itemID
JOIN fields f ON f.fieldID = d.fieldID AND f.fieldName = 'DOI'
JOIN itemDataValues v ON v.valueID = d.valueID
WHERE ia.contentType = 'application/pdf' AND ia.path LIKE 'storage:%'
  AND a.itemID NOT IN (SELECT itemID FROM deletedItems)
  AND p.itemID NOT IN (SELECT itemID FROM deletedItems)
"""


def zotero_pdfs():
    try:
        tmp = Path(tempfile.mkdtemp()) / "zotero.sqlite"
        shutil.copy(ZOTERO / "zotero.sqlite", tmp)
        con = sqlite3.connect(tmp)
    except PermissionError:
        # Zotero is writing (import running): read the live file without taking locks
        con = sqlite3.connect((ZOTERO / "zotero.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True)
    df = pd.read_sql(SQL, con)
    con.close()
    df["doi"] = df["doi"].map(norm_doi)
    df["pdf"] = [str(ZOTERO / "storage" / k / p.split(":", 1)[1]) for k, p in zip(df["att_key"], df["path"])]
    df = df[df["doi"].notna() & df["pdf"].map(lambda p: Path(p).exists())]
    df["size"] = df["pdf"].map(lambda p: Path(p).stat().st_size)
    # several attachments per DOI: keep the largest (supplements and previews are smaller)
    return df.sort_values("size", ascending=False).drop_duplicates("doi")[["doi", "item_key", "pdf", "size"]]


def by_filename(dois):
    """Old pipeline convention: <storage>/<key>/<doi without slashes>.pdf"""
    index = {p.stem.lower(): str(p) for p in (ZOTERO / "storage").glob("*/*.pdf")}
    rows = [{"doi": d, "item_key": None, "pdf": index[d.replace("/", "")], "size": None}
            for d in dois if d.replace("/", "") in index]
    return pd.DataFrame(rows, columns=["doi", "item_key", "pdf", "size"])


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    pdfs = zotero_pdfs()
    print("DOIs with a PDF attachment in Zotero:", len(pdfs))
    # copies fetched by fetch_direct.py and through the user's browser session (file name = DOI with / -> __ and : -> --)
    direct = [{"doi": f.stem.replace("__", "/").replace("--", ":"), "item_key": None, "pdf": str(f),
               "size": f.stat().st_size} for d in ("pdf_direct", "pdf_chrome") for f in (PDF_STORE / d).glob("*.pdf")]
    direct = pd.DataFrame(direct, columns=["doi", "item_key", "pdf", "size"])
    direct = direct[~direct["doi"].isin(pdfs["doi"])].drop_duplicates("doi")
    print("additional PDFs fetched directly or through the browser session:", len(direct))
    pdfs = pd.concat([pdfs, direct], ignore_index=True)
    pdfs.to_csv(OUT / "zotero_pdfs.csv", index=False, encoding="utf-8")
