from __future__ import annotations

from pathlib import Path
import csv
from typing import Iterable, Optional
from contextlib import contextmanager
import bibtexparser
from bibtexparser.bibdatabase import BibDatabase


@contextmanager
def csv_writer(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline='', encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=';', quotechar='|', quoting=csv.QUOTE_MINIMAL)
        yield writer


@contextmanager
def bibtex_appender(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding='utf-8') as f:
        yield f


def write_bib_entries(fh, db: BibDatabase, remove_comments = True) -> None:
    if remove_comments:
        db.comments = []
    fh.writelines(bibtexparser.dumps(db))
    fh.flush()
