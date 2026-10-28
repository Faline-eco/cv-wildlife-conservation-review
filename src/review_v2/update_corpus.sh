#!/usr/bin/env bash
# Bring the corpus up to date after new PDFs arrived (Zotero import or free copies), then rebuild figures.
# Usage: bash src/review_v2/update_corpus.sh <round_name>     e.g. round12
# Every step skips work already done (cached records / names), so the script can be re-run after each import.
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONIOENCODING=utf-8
PY=.venv/Scripts/python.exe
R=review_output/v2
round=$1

$PY src/review_v2/fulltext/inventory.py
# papers with a PDF and no record: screened include/fulltext plus the captive-only exclusions (widened scope)
$PY src/review_v2/extraction/next_round.py "${round}_dois.txt"
$PY - "$round" <<'EOF'
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, "src")
from review_v2.fulltext.prepare import paper_id
from review_v2.search.merge import norm_doi
R = Path("review_output/v2")
have = set(pd.read_csv(R / "fulltext/zotero_pdfs.csv")["doi"].map(norm_doi))
done = {p.stem for p in (R / "extraction/corpus_v2_opus").glob("*.json")}
f = R / "fetch" / f"{sys.argv[1]}_dois.txt"
todo = set(f.read_text().split())
todo |= {d for d in map(norm_doi, (R / "fetch/FINAL_4_captive_dois.txt").read_text().split())
         if d in have and paper_id(d) not in done}
f.write_text("\n".join(sorted(todo)) + "\n", encoding="utf-8")
print("to code incl. captive:", len(todo))
EOF
$PY src/review_v2/fulltext/prepare.py "$R/fetch/${round}_dois.txt"
$PY src/review_v2/extraction/extract.py "$R/fetch/${round}_dois.txt" corpus_v2_opus --model claude-opus-5-5 --workers 6
$PY src/review_v2/corpus/build.py
$PY src/review_v2/extraction/captivity.py "$R/fetch/captivity_pending_dois.txt" --workers 6
$PY src/review_v2/corpus/build.py
$PY src/review_v2/extraction/platform_pass.py run --workers 6
$PY src/review_v2/taxa/llm_names.py
$PY src/review_v2/taxa/normalise.py
$PY src/review_v2/registry/normalise.py algorithms
$PY src/review_v2/registry/normalise.py datasets
$PY src/review_v2/corpus/tables.py
$PY src/review_v2/taxa/naming.py
$PY src/review_v2/taxa/naming_pass.py run --workers 6
$PY src/review_v2/figures/make_figures.py
