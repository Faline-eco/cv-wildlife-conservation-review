from __future__ import annotations

import logging
from typing import Optional, Tuple

import requests
import bibtexparser
from bibtexparser.bibdatabase import BibDatabase

from ..utils.text import normalize_doi, doi_url


log = logging.getLogger(__name__)


class Doi2BibClient:
    def __init__(self, base_url: str, session: Optional[requests.Session] = None, timeout: float = 15.0):
        self.base_url = base_url.rstrip('/')
        self.session = session or requests.Session()
        self.timeout = timeout

    def get_bib_tex(self, doi_or_url: str) -> Tuple[Optional[str], Optional[BibDatabase]]:
        """Return (doi, BibDatabase) or (None, None) on failure.
        Ensures each entry has a 'doi' and 'url' field.
        """
        doi = normalize_doi(doi_or_url)
        if not doi:
            log.warning("No DOI in %r", doi_or_url)
            return None, None
        url = f"{self.base_url}/?url={doi}"
        try:
            log.info(f"Fetching {url}")
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except Exception as e:
            log.exception("doi2bib request failed for %s: %s", doi, e)
            return doi, None

        try:
            library = bibtexparser.loads(resp.text)
        except Exception as e:
            log.exception("Failed to parse bibtex for %s: %s", doi, e)
            return doi, None

        # Make sure entries have doi/url
        for entry in getattr(library, 'entries', []):
            if "doi" not in entry:
                entry["doi"] = doi
            if "url" not in entry:
                entry["url"] = doi_url(doi)

        return doi, library
