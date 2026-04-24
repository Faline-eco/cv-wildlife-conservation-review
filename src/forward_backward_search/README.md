# citation_walker

A small, modular tool to perform forward and backward citation searches using
[OpenCitations COCI](https://opencitations.net/index/coci) and a local [doi2bib-web] service.

It refactors and generalizes an original single-file script into a maintainable package with
clear separation of concerns (clients, services, IO, utils).

## Setup

- Ensure you have a local `doi2bib-web` running, e.g.:
  ```bash
  docker run -p 8080:8080 doi2bib-web
  ```

- Install dependencies:
  ```bash
  pip install requests pandas bibtexparser
  ```

## Usage

```bash
python -m citation_walker.cli   --input path/to/review_raw.xlsx   --out-csv path/to/review_filtered_output.csv   --out-bib path/to/bibliography.tex   --doi2bib-base http://localhost:8080   --min-year 2014   --rate 6   --timeout 15
```

Optional proxy (e.g., torproxy/privoxy) for both HTTP and HTTPS:
```bash
--proxy http://127.0.0.1:8118
```

## Notes

- Output CSV is semicolon-separated and contains: `doi;relation;year`
  where `relation` is one of `seed|backward|forward`.
- BibTeX entries are appended to the specified `.tex` file.
- Basic rate limiting aims to keep total API calls under the `--rate` per-second budget.
- Row-level filters replicate the original logic for `IsAggriculture`, `Habitat`, and `Imaging Method` columns.
