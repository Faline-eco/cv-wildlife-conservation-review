from __future__ import annotations

import logging
from typing import Iterable, Iterator, Tuple, Optional

from ..clients.doi2bib import Doi2BibClient
from ..clients.opencitations import OpenCitationsClient
from ..utils.text import doi_url
from ..models import Publication
from .rate_limit import RateLimiter
from .dedup import Deduper

import bibtexparser
from bibtexparser.bibdatabase import BibDatabase

log = logging.getLogger(__name__)


class TraversalService:
    def __init__(
        self,
        doi2bib: Doi2BibClient,
        oc: OpenCitationsClient,
        rate_limiter: RateLimiter | None = None,
        deduper: Deduper | None = None,
        min_year: int = 2014,
    ) -> None:
        self.doi2bib = doi2bib
        self.oc = oc
        self.limiter = rate_limiter or RateLimiter(6)
        self.deduper = deduper or Deduper()
        self.min_year = min_year
        self.max_citations = 0
        self.max_citations_publication: Optional[str] = None

    def _allow(self, year: Optional[int]) -> bool:
        try:
            return year is not None and int(year) >= int(self.min_year)
        except Exception:
            return False

    def _extract_year(self, db: BibDatabase) -> Optional[int]:
        try:
            if db and db.entries and len(db.entries) >= 1:
                y = db.entries[0].get("year")
                return int(y) if y is not None else None
        except Exception:
            return None
        return None

    def fetch_publication(self, doi_or_url: str) -> Tuple[Optional[str], Optional[BibDatabase], Optional[int]]:
        self.limiter.wait()
        doi, db = self.doi2bib.get_bib_tex(doi_or_url)
        year = self._extract_year(db) if db else None
        return doi, db, year

    def traverse(self, seed_doi_or_url: str) -> Iterator[Tuple[str, str, BibDatabase, int]]:
        """Yield tuples of (doi, relation, bib_db, year). relation in {seed, backward, forward}."""
        # Seed
        doi, db, year = self.fetch_publication(seed_doi_or_url)
        if not doi or not db:
            return
        if doi and self.deduper.seen(doi):
            log.info("Already visited %s", doi)
            return
        self.deduper.add(doi)
        yield (doi, "seed", db, year or -1)  # year may be None; keep -1 for CSV

        if not self._allow(year):
            log.info("Seed %s too old or unknown year: %s", doi, year)
            return

        # Backward search
        self.limiter.wait()
        refs = self.oc.get_references(doi)
        for art in refs:
            ref_doi = art.get("cited")
            if not ref_doi:
                continue
            if self.deduper.seen(ref_doi):
                continue
            self.deduper.add(ref_doi)
            bdoi, bdb, byear = self.fetch_publication(ref_doi)
            if bdoi and bdb and self._allow(byear):
                yield (bdoi, "backward", bdb, byear or -1)

        # Forward search
        self.limiter.wait()
        cits = self.oc.get_citations(doi)
        count = len(cits)
        if count > self.max_citations:
            self.max_citations = count
            self.max_citations_publication = doi
        for art in cits:
            cit_doi = art.get("citing")
            if not cit_doi:
                continue
            if self.deduper.seen(cit_doi):
                continue
            self.deduper.add(cit_doi)
            fdoi, fdb, fyear = self.fetch_publication(cit_doi)
            if fdoi and fdb and self._allow(fyear):
                yield (fdoi, "forward", fdb, fyear or -1)

    def max_citation_stats(self) -> Optional[tuple[str, int]]:
        if self.max_citations_publication is None:
            return None
        return (self.max_citations_publication, self.max_citations)
