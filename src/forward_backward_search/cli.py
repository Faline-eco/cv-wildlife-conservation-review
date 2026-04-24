from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Dict, Any

import requests

from forward_backward_search.config import Config
from forward_backward_search.clients.doi2bib import Doi2BibClient
from forward_backward_search.clients.opencitations import OpenCitationsClient
from forward_backward_search.io.readers import read_seed_rows
from forward_backward_search.io.writers import csv_writer, bibtex_appender, write_bib_entries
from forward_backward_search.services.filters import should_skip_row
from forward_backward_search.services.traversal import TraversalService
from forward_backward_search.services.rate_limit import RateLimiter
from forward_backward_search.services.dedup import Deduper
from forward_backward_search.utils.logging import setup_logging


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Forward & backward citation search using OpenCitations and doi2bib-web.")
    # paper review
    # p.add_argument("--input", default=r"D:\LiteratureReviewCVinWC\review_input\review_raw.xlsx", help="Path to input Excel file.")
    # p.add_argument("--out-csv", default=r"D:\LiteratureReviewCVinWC\review_output\review_filtered_output.csv",help="Path to output CSV (semicolon-separated)." )
    # p.add_argument("--out-bib", default=r"D:\LiteratureReviewCVinWC\review_output\review_filtered_output.tex", help="Path to output BibTeX file." )

    # lila review
    p.add_argument("--input", default=r"D:\LiteratureReviewCVinWC\review_input\lila.csv", help="Path to input Excel file.")
    p.add_argument("--out-csv", default=r"D:\LiteratureReviewCVinWC\review_output\lila_search.csv",  help="Path to output CSV (semicolon-separated).")
    p.add_argument("--out-bib", default=r"D:\LiteratureReviewCVinWC\review_output\lila_search.tex",help="Path to output BibTeX file.")

    p.add_argument("--doi2bib-base", default="http://localhost:8080", help="Base URL of doi2bib-web service.")
    p.add_argument("--min-year", type=int, default=2014, help="Minimum publication year to include.")
    p.add_argument("--rate", type=int, default=6, help="Max API calls per second (overall)." )
    p.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds.")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG","INFO","WARNING","ERROR"], help="Logging level.")
    p.add_argument("--proxy", default=None, help="HTTP proxy base (e.g., http://127.0.0.1:8118) to use for both http/https.")
    return p

def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    setup_logging(getattr(logging, ns.log_level))

    proxies = None
    if ns.proxy:
        proxies = {"http": ns.proxy, "https": ns.proxy}

    cfg = Config(
        input_excel_path=Path(ns.input),
        output_csv_path=Path(ns.out_csv),
        output_bibtex_path=Path(ns.out_bib),
        doi2bib_base_url=ns.doi2bib_base,
        min_year=int(ns.min_year),
        rate_limit_per_sec=int(ns.rate),
        timeout_seconds=float(ns.timeout),
        proxies=proxies,
    )

    session = requests.Session()
    if proxies:
        session.proxies = proxies

    doi2bib = Doi2BibClient(cfg.doi2bib_base_url, session=session, timeout=cfg.timeout_seconds)
    oc = OpenCitationsClient(cfg.opencitations_base_url, session=session, timeout=cfg.timeout_seconds)
    limiter = RateLimiter(cfg.rate_limit_per_sec)
    deduper = Deduper()
    traversal = TraversalService(doi2bib, oc, limiter, deduper, cfg.min_year)

    # Prepare outputs
    with csv_writer(cfg.output_csv_path) as csvw, bibtex_appender(cfg.output_bibtex_path) as bibw:
        # CSV header
        csvw.writerow(("doi", "relation", "year"))
        for idx, row in read_seed_rows(cfg.input_excel_path):
            doi_addr = row.get("doi")
            if not isinstance(doi_addr, str):
                logging.warning("Row %s has invalid DOI value: %r", idx, doi_addr)
                continue

            if should_skip_row(row):
                logging.info("Skipping row %s due to filters", idx)
                continue

            logging.info("Processing row %s: %s", idx, doi_addr)

            for doi, rel, bib_db, year in traversal.traverse(doi_addr):
                write_bib_entries(bibw, bib_db)
                csvw.writerow((doi, rel, year))

    max_stats = traversal.max_citation_stats()
    if max_stats:
        logging.info("Max citations: %s has %d citing articles", *max_stats)

    logging.info("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
