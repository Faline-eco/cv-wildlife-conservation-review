from __future__ import annotations

import logging
from typing import List, Dict

import requests

from ..utils.text import normalize_doi

log = logging.getLogger(__name__)


class OpenCitationsClient:
    def __init__(self, base_url: str, session: requests.Session | None = None, timeout: float = 15.0):
        self.base_url = base_url.rstrip('/')
        self.session = session or requests.Session()
        self.timeout = timeout

    def get_citations(self, doi_or_url: str) -> List[Dict]:
        """Forward search: articles citing the given DOI. Returns list of dicts with 'citing'."""
        doi = normalize_doi(doi_or_url)
        if not doi:
            return []
        url = f"{self.base_url}/citations/{doi}"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.warning("OpenCitations citations failed for %s: %s", doi, e)
            return []

    def get_references(self, doi_or_url: str) -> List[Dict]:
        """Backward search: articles referenced by the given DOI. Returns list of dicts with 'cited'."""
        doi = normalize_doi(doi_or_url)
        if not doi:
            return []
        url = f"{self.base_url}/references/{doi}"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.warning("OpenCitations references failed for %s: %s", doi, e)
            return []
