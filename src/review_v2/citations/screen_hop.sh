#!/usr/bin/env bash
# Title/abstract screening of a citation run with the frozen screening set-up of the first hop.
# Usage: bash src/review_v2/citations/screen_hop.sh hop2      (after citations/fetch_citations.py ... hop2)
# Steps: candidates -> abstracts for records without one (OpenAlex, then Scopus) -> screeners A and B ->
# combine -> adjudicator on unsure -> re-adjudication of the three lossy exclusion groups -> finalize.
# Every step resumes from its cache.
set -euo pipefail
cd "$(dirname "$0")/../../.."
export PYTHONIOENCODING=utf-8
PY=.venv/Scripts/python.exe
run=$1
R=review_output/v2
IN=$R/citations/$run/to_screen.csv
S=$R/screening

$PY src/review_v2/citations/candidates.py "$run"
$PY - "$run" <<'EOF'
import sys
import pandas as pd
run = sys.argv[1]
f = f"review_output/v2/citations/{run}/to_screen.csv"
d = pd.read_csv(f)
miss = d.loc[d["abstract"].isna() & d["doi"].notna(), "doi"]
open(f"review_output/v2/search/cit_{run}_noabs_dois.txt", "w").write("\n".join(miss) + "\n")
print("without abstract, with DOI:", len(miss))
EOF
$PY src/review_v2/search/fetch_by_doi.py "cit_${run}_noabs"
$PY - "$run" <<'EOF'
import sys
import pandas as pd
run = sys.argv[1]
f = f"review_output/v2/citations/{run}/to_screen.csv"
d = pd.read_csv(f)
m = pd.read_json(f"review_output/v2/search/cit_{run}_noabs_meta.jsonl", lines=True)
m = m[m["abstract"].notna()].drop_duplicates("doi").set_index("doi")["abstract"]
fill = d["abstract"].isna() & d["doi"].isin(m.index)
d.loc[fill, "abstract"] = d.loc[fill, "doi"].map(m)
d.to_csv(f, index=False, encoding="utf-8")
print("abstracts filled:", int(fill.sum()), "still without:", int(d["abstract"].isna().sum()))
EOF
$PY src/review_v2/screening/screen.py "$IN" "citations_$run" --screener a > "$S/cit_${run}_a.log" 2>&1 &
$PY src/review_v2/screening/screen.py "$IN" "citations_$run" --screener b > "$S/cit_${run}_b.log" 2>&1 &
wait
$PY src/review_v2/screening/combine.py "$IN" "citations_$run" "$run"
mkdir -p "$S/adjudication_$run" "$S/adjudication_rescue_$run"
$PY src/review_v2/screening/adjudicate.py collect "$S/adjudication_$run/input.csv" "citations_$run"
$PY src/review_v2/screening/adjudicate.py run "$S/adjudication_$run/input.csv" "adjudication_$run"
$PY src/review_v2/screening/adjudicate.py rescue "$S/adjudication_rescue_$run/input.csv" "citations_$run"
$PY src/review_v2/screening/adjudicate.py run "$S/adjudication_rescue_$run/input.csv" "adjudication_rescue_$run"
$PY src/review_v2/screening/finalize.py
