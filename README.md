# Computer Vision in Wildlife Conservation: Review Data and Code

This repository holds the code and data of the systematic review *Computer Vision in Wildlife Conservation*. The interactive overview of the corpus is published via GitHub Pages: <https://faline-eco.github.io/cv-wildlife-conservation-review/> (`index.html`).

There are two versions of the pipeline:

- **Revision (v2, October 2026)**, in `src/review_v2/`, `review_output/v2/` and `paper/`. This is the version the revised manuscript reports. It covers 6,360 papers published between 2014 and October 2026.
- **First submission (v1)**, in `src/forward_backward_search/`, `src/review/` and `src/iucn/`. It used a Gemini-based extraction and is described [below](#first-version-v1). It is kept unchanged for reference.

---

## Revision (v2)

### What the pipeline does

| Step | Code | Model / source |
|---|---|---|
| Database search (Scopus, OpenAlex, PubMed) and library searches (IEEE, ScienceDirect, Wiley, ACM) | `search/` | APIs and exports |
| Citation search, two hops backward and forward | `citations/` | OpenAlex, OpenCitations |
| Title/abstract screening by two independent screeners, plus adjudication of disagreements | `screening/` | Claude Sonnet 5.5 (`claude-sonnet-5-5`) screens; Claude Opus 5.5 (`claude-opus-5-5`) adjudicates |
| Full-text retrieval over sanctioned routes (Zotero, open-access copies, publisher APIs, saved by hand) | `fulltext/` | none |
| Full-text extraction with a frozen protocol and JSON schema; every value needs a quote, which is verified against the PDF text | `extraction/extract.py`, `protocol_extract.md`, `schema.py`, `verify.py` | Claude Opus 5.5, protocol hash `a56e43a1f9e7` |
| Supplementary passes: platform where it is not reported, captive or wild setting | `extraction/platform_pass.py`, `captivity.py` | Claude Sonnet 5.5 |
| Taxon names matched to GBIF; algorithm and dataset registries | `taxa/`, `registry/` | GBIF API, Claude Opus 5.5 |
| Corpus tables (eligibility, settings, spectra, habitats, countries, tasks, algorithms, datasets, species) | `corpus/build.py`, `corpus/tables.py` | none |
| Validation: screening accuracy, extraction agreement with the manual coding, adjudication of disagreements, hallucination check, run-to-run stability, citation coverage and composition of the search arms, corrected shares, check of domestic targets, overlap with earlier reviews | `validation/` | Claude Sonnet 5.5; Codex as the second rater in the hallucination check |
| Every number, table and figure of the paper | `figures/make_figures.py` | none |
| Overview page `index.html` | `figures/overview_html.py` | none |

The LLM steps run through the Claude Code CLI in headless mode (`claude -p --model ... --json-schema ...`). Every record stores the model ID, the hash of its prompt and schema, the SHA-256 of the PDF it was made from, and its cost.

### Reproducing the paper's numbers

The data in `review_output/v2/` are enough to regenerate all 1,142 macros of `paper/numbers.tex`, the tables in `paper/tables_v2/` and the figures in `paper/images/results_v2/`. No API key and no PDF is needed for this. We checked that both outputs come out identical to the versions in the manuscript.

```bash
pip install pandas pyarrow numpy matplotlib seaborn scipy rapidfuzz requests plotly pymupdf
export PYTHONIOENCODING=utf-8
python src/review_v2/corpus/tables.py          # corpus tables from the extraction records
python src/review_v2/figures/make_figures.py   # paper/numbers.tex, paper/tables_v2/, paper/images/results_v2/
python src/review_v2/figures/overview_html.py  # index.html
```

Re-running the search, the screening, the extraction or the LLM-based checks needs API keys and the full texts. Put the keys (`SCOPUS_API_KEY`, `OPENALEX_API_KEY`, ...) in a git-ignored `.env.revision` file in the repository root. Set `PDF_STORE` (the PDF folder) and `ZOTERO_DIR` if they differ from the defaults. The order of the steps is in `src/review_v2/update_corpus.sh` and in the docstring of each script.

### Data (`review_output/v2/`)

| Folder | Contents |
|---|---|
| `corpus/papers.csv` | All 9,780 full-text-assessed records: eligibility (`eligible` gives the 6,360 analysed papers), exclusion criterion, setting (wild/captive), paper type |
| `corpus/*.parquet` | Analysis tables, one row per value, with a `verified` flag for the evidence check |
| `extraction/corpus_v2_opus/` | Extraction record per paper (Claude Opus 5.5), with provenance |
| `extraction/platform_v1/`, `captivity_v1/` | Records of the supplementary passes |
| `screening/ta_final.csv` | Title/abstract decisions of both screeners and the adjudicator, with the final decision |
| `search/` | Search results and library exports (bibliographic metadata), retrieval log |
| `citations/hop1/`, `hop2/` | Seeds, works found, citation edges |
| `taxa/` | Taxon names, GBIF matches (`gbif_cache.json`), naming analysis |
| `registry/` | Canonical names and families of algorithms and datasets |
| `validation/` | Inputs and results of every validation check |
| `../gapminder/2026130_*.parquet` | Extraction of the first version (manual and automated arm), the reference for the agreement check |

**Not included, for copyright reasons:** the full texts, the abstracts, and the verbatim quotes from the papers. The extraction records and the validation files keep, for every value, whether its quote was found in the PDF (`evidence.status`, `verified`), the page and the section, but not the quote itself. The removed fields are `quote`, `abstract`, `text` and `examples`. With the PDFs, `src/review_v2/extraction/verify.py` rebuilds the evidence check.

### License, archive and citation

The code and data are released under the MIT license (`LICENSE`). The article is under double-blind review; a snapshot of this repository will be archived on Zenodo with a DOI upon acceptance (uploaded manually; the metadata are prepared in `.zenodo.json`), and the citation will be added here.

---

## First version (v1)


An automated pipeline for conducting systematic literature reviews on **computer vision applications in wildlife conservation**. The toolkit covers two main phases: expanding a seed corpus through citation search, and extracting structured metadata from PDFs using a Gemini-based LLM pipeline.

---

### Repository Layout

```
src/
├── forward_backward_search/   # Phase 1 — citation discovery
├── review/                    # Phase 2 — LLM extraction pipeline
│   ├── post_process/          # Species translation, re-runs, encoding fixes
│   └── visualization/         # Graph, Gapminder, HTML exports
└── iucn/                      # IUCN habitat taxonomy models & utilities
```

---

### Phase 1 — Forward/Backward Citation Search

**Package:** `src/forward_backward_search/`

Starting from a manually curated seed set of papers, this phase discovers additional relevant papers by walking the citation graph in both directions:

- **Backward search** — papers *cited by* a seed paper (its reference list)
- **Forward search** — papers that *cite* a seed paper (citing works)

Both directions are queried through the [OpenCitations COCI API](https://opencitations.net/index/coci), and bibliographic metadata is resolved via a locally running [doi2bib-web](https://github.com/nicowillis/doi2bib) service. Results are deduplicated, filtered by publication year, and written to CSV and BibTeX.

#### Prerequisites

Start the doi2bib-web service before running:

```bash
docker run -p 8080:8080 doi2bib-web
```


#### Installation

```bash
pip install requests pandas bibtexparser
```

#### Usage

```bash
python -m forward_backward_search.cli \
  --input  path/to/seed_papers.csv \
  --out-csv path/to/discovered.csv \
  --out-bib path/to/bibliography.tex \
  --doi2bib-base http://localhost:8080 \
  --min-year 2014 \
  --rate 6 \
  --timeout 15
```

| Argument | Description | Default |
|---|---|---|
| `--input` | Seed CSV (must contain a `doi` column) | — |
| `--out-csv` | Semicolon-separated output (`doi;relation;year`) | — |
| `--out-bib` | BibTeX output file | — |
| `--doi2bib-base` | Base URL of the doi2bib-web service | `http://localhost:8080` |
| `--min-year` | Exclude papers published before this year | `2014` |
| `--rate` | Max API calls per second | `6` |
| `--timeout` | HTTP request timeout in seconds | `15` |
| `--proxy` | Optional HTTP/HTTPS proxy URL | — |

#### Output

The output CSV contains one row per discovered paper:

```
doi;relation;year
10.1234/example;seed;2020
10.5678/other;backward;2018
10.9999/citing;forward;2022
```

`relation` is one of `seed`, `backward`, or `forward`.

#### Row-level Filters

Papers from the input seed CSV are skipped before traversal when:

- `IsAggriculture` column is `True`
- `Habitat` column is exactly `non-natural`
- `Imaging Method` contains only non-optical sensors (microphone, spectrometer, acoustic camera, microscope)

#### Internal Architecture

```
cli.py
└── TraversalService          services/traversal.py
    ├── OpenCitationsClient   clients/opencitations.py  — /citations and /references endpoints
    ├── Doi2BibClient         clients/doi2bib.py         — DOI → BibTeX via doi2bib-web
    ├── RateLimiter           services/rate_limit.py     — token-bucket, per-second budget
    └── Deduper               services/dedup.py          — seen-DOI set, avoids duplicate fetches
```

`TraversalService.traverse(seed_doi)` is a generator that yields
`(doi, relation, bib_database, year)` tuples, so the CLI can stream results
directly to CSV and BibTeX writers without buffering everything in memory.

---

### Phase 2 — LLM-Based Extraction Pipeline

**Package:** `src/review/`

For each paper in the corpus (provided as PDFs stored in a Zotero library), this phase uploads the PDF to the Gemini API and extracts structured metadata through a series of targeted prompts. All responses are validated against Pydantic schemas and verified by fuzzy-matching extracted quotes back against the raw PDF text.

#### Prerequisites

- A [Zotero](https://www.zotero.org/) library with PDFs stored locally (using the DOI as file name)
- A Google Gemini API keys
- A `.env` file containing your settings (see Configuration below)

#### Installation

```bash
pip install google-genai pydantic pydantic-settings pandas pypdf rapidfuzz httpx
```

#### Configuration

Settings are loaded via `pydantic-settings` from environment variables or a `.env` file.
The path to the `.env` file is set in `src/review/settings.py`:

```python
env_file = r"path/to/your/.env"
```

A minimal `.env`:

```env
ZOTERO_STORAGE=C:\Users\you\Zotero\storage
DOIS_FILE_PATH=path\to\reviews.csv
TARGET_BASE_FOLDER=path\to\output
API_KEYS=["AIza...key1","AIza...key2"]
LIGHT_MODEL_NAME=models/gemini-2.5-flash
STRONG_MODEL_NAME=models/gemini-2.5-pro
RPM=148
CONCURRENT_FILES=4
```

| Setting | Description | Default |
|---|---|---|
| `ZOTERO_STORAGE` | Root of Zotero's local storage directory | — |
| `DOIS_FILE_PATH` | CSV with `doi` and `year` columns (semicolon-separated) | — |
| `TARGET_BASE_FOLDER` | Output directory; a dated sub-folder is created per run | — |
| `REVIEW_TO_CONTINUE` | Sub-folder name of a previous run to resume | `null` |
| `API_KEYS` | JSON array of Gemini API key strings | `[]` |
| `LIGHT_MODEL_NAME` | Gemini model used for cheaper extraction steps | `models/gemini-2.5-flash` |
| `STRONG_MODEL_NAME` | Gemini model used for classification and complex extractions | `models/gemini-2.5-pro` |
| `RPM` | Requests per minute across all API keys | `148` |
| `CONCURRENT_FILES` | Max PDFs processed in parallel | `4` |

#### Usage

```bash
python -m review.cli \
  --rpm 148 \
  --concurrency 4 \
  --log-level INFO \
  --export-csv results.csv
```

Pass `--force` to ignore config-drift warnings when resuming a previous run with changed settings.

#### Pipeline Flow

```
cli.py
│
├── Reads DOI list from CSV and maps PDF filenames to DOIs via Zotero storage
│
└── PaperReviewPipeline.run()            pipeline.py
    │  (asyncio, semaphore-limited)
    └── _process_one(pdf_path, doi, year)
        │
        ├── 1. Cache check — skip if {stem}.json already exists
        │
        ├── 2. check_topic()              extractors.py
        │      Uploads PDF, asks Gemini whether this is a CV-in-wildlife paper
        │      Returns: IsCVWildlife { is_computer_vision_in_wildlife_study, is_review, explanation }
        │
        └── 3. (if CV in wildlife AND not a review)
            ├── extract_topics()          — 8 topic extractors (see Topics below)
            ├── get_datasets()            — dataset names + URLs + evidence
            ├── get_habitats()            — IUCN habitat classification (two-pass)
            └── Writes {stem}.json to output folder
```

Each extracted field carries **evidence** — the page number and a verbatim quote from the PDF — which is then verified by `verify.py` using pypdf text extraction and fuzzy string matching (RapidFuzz, threshold 85%). Results are split into `verified` and `unverified` lists in the output JSON.

#### Extracted Topics

For each paper classified as a CV-in-wildlife study, the following topics are extracted:

| Key | Description | Constrained Vocabulary |
|---|---|---|
| `Species (Text)` | Species names from the main text (prefer scientific names) | No |
| `Species (Images)` | Species visible in figures/diagrams only | No |
| `Country` | Countries where the methodology was applied | No |
| `Imaging Method` | Data acquisition method (UAV, camera trap, satellite, etc.) | No |
| `Light Spectra (Text)` | Spectral bands mentioned in text | No |
| `Light Spectra (Images)` | Spectral information inferred from sample images | No |
| `CV Tasks` | Computer vision task category | Classification, Segmentation, Counting, Reconstruction, Pose Estimation, Synthesis, Tracking, Re-Identification, Activity Recognition, Behavior Analysis, Interaction Monitoring, Localization |
| `CV Algorithms` | Specific model or algorithm names (ResNet, YOLO, U-Net, ViT, …) | No |

All prompts are scoped to *this paper's own methodology*, explicitly excluding related work sections.

#### IUCN Habitat Classification

Habitats are classified using the full IUCN habitat taxonomy (14 top-level groups, each with multiple sub-categories). Extraction uses a two-pass approach:

1. **Prediction pass** — ask the model which habitat groups and sub-types are present (boolean fields per group)
2. **Evidence pass** — for each field predicted `True`, request a page number and verbatim quote

The `iucn/` package contains the Pydantic models for the full taxonomy and a utility (`root_presence_map`) that collapses the nested boolean structure into a flat `{habitat_group: bool}` dict.

#### Output Format

Each paper produces a JSON file at `{TARGET_BASE_FOLDER}/{run_date}/{pdf_stem}.json`:

```jsonc
{
  "doi": "10.1234/example",
  "year": 2021,
  "is_computer_vision_in_wildlife_study": true,
  "is_computer_vision_in_wildlife_study_review": false,
  "is_computer_vision_in_wildlife_study_explanation": "...",
  "Species (Text)": {
    "evidences": [{"value": "Panthera leo", "evidence": {"page": 3, "quote": "..."}}],
    "verified": ["Panthera leo"],
    "unverified": []
  },
  "Dataset": { "evidences": [...], "verified": [...], "unverified": [...] },
  "Habitat": { ... },
  "HabitatVerification": { "evidences": [...], "verified": [...], "unverified": [...] },
  "ParentHabitat": {"Forest": true, "Savanna": false, ...}
}
```

#### Config Drift Detection

The `Storage` class records a SHA-256 hash of the run configuration (models, topics, prompts, RPM) alongside the results. On subsequent runs the hash is compared, and if it differs the pipeline refuses to continue without `--force`. This prevents silently mixing results produced under different settings.

---

### Post-Processing

| Module | CLI | Description |
|---|---|---|
| `post_process/species_translation/` | `python -m review.post_process.species_translation.cli` | Translate common species names to scientific names (or vice versa). Backends: LLM (Gemini), GBIF, EcoName, API Ninja, Docker |
| `post_process/manual_habitat_to_iucn/` | `python -m review.post_process.manual_habitat_to_iucn.cli` | Manually map free-text habitat strings to IUCN categories |
| `post_process/fix_encoding/` | `python -m review.post_process.fix_encoding.cli` | Fix encoding issues in output JSON files |
| `post_process/rerun/` | `python -m review.post_process.rerun.cli` | Re-run extraction for a specific field without reprocessing the full paper |

Species translation is configured via its own `Settings` (see `post_process/species_translation/config.py`) and shares the same `.env` file as the main pipeline. To use the API Ninja backend, set `API_NINJA_KEY` in the environment.

---

### Visualization

The `review/visualization/` package converts the JSON output into several formats:

- **DataFrame** (`toDataFrame.py`) — pandas DataFrame with separate columns for verified/unverified values
- **GraphML / interactive HTML** (`graph/`) — co-occurrence graph of species, methods, and habitats across papers
- **Neo4j** (`graph/to_neo4j.py`) — load the graph into a Neo4j database for exploration
- **Gapminder explorer** (`gapminder/`) — animated scatter plot across years

---

### External Services Summary

| Service | Purpose | Where configured |
|---|---|---|
| [OpenCitations COCI](https://opencitations.net/index/coci) | Citation graph queries | `forward_backward_search/config.py` |
| doi2bib-web (local Docker) | DOI → BibTeX resolution | `forward_backward_search/config.py` |
| Google Gemini API | PDF classification & extraction | `review/settings.py` / `.env` |
| GBIF API | Species name lookup | automatic (no key required) |
| API Ninja | Alternative species lookup | `API_NINJA_KEY` in `.env` |
