import json
import sys
from pathlib import Path

# --------- Configuration ---------
# Folder containing your JSON files:
INPUT_DIR = Path(r"D:\LiteratureReviewCVinWC\review_output\20250819_reviews")

# Optional: if your JSON has different keys, edit this map.
SECTION_KEYS = {
    "dataset": "datasets",
    "species": "species",
    "habitat": "habitat",  # likely absent in your current JSONs -> will become ×
    "imaging": "imaging_method",
    "light": "light_spectra",
    "tasks": "computer_vision_task",
    "algorithms": "computer_vision_algorithm",
}

# If your JSON provides a 'bibtex_key', we use it; otherwise we fall back to filename.
BIBTEX_KEY_FIELD = "bibtex_key"

# --------- Helpers ---------
CK = r"\checkmark"
TILDE = r"\(\sim \)"
CROSS = r"$\times$"

def symbol_for(obj: dict, section_key: str) -> str:
    """Return the LaTeX symbol (✓, ~, ×) for a given section."""
    # "~" if there's an explicit partial flag (e.g., datasets_partial: true)
    partial_flag = f"{section_key}_partial"
    if partial_flag in obj and isinstance(obj[partial_flag], bool) and obj[partial_flag]:
        return TILDE

    sec = obj.get(section_key)
    if not sec:
        return CROSS

    # Accept either a list (simple) or a dict with 'evidences'/'verified'
    if isinstance(sec, list):
        return CK if len(sec) > 0 else CROSS
    if isinstance(sec, dict):
        # Treat non-empty 'evidences' or 'verified' as ✓
        evid = sec.get("evidences") or []
        veri = sec.get("verified") or []
        return CK if (len(evid) + len(veri)) > 0 else CROSS

    # Fallback
    return CK

def twodig_year(y: int) -> str:
    return f"’{(y % 100):02d}"

def reviewed_papers_and_years(obj: dict):
    """Return (count, min_year, max_year) derived from the 'papers' section."""
    papers = obj.get("papers", {})
    items = []
    for key in ("evidences", "verified"):
        arr = papers.get(key, [])
        if isinstance(arr, list):
            items.extend(arr)

    # Unique by title/value if present; otherwise by doi; otherwise count all
    seen = set()
    years = []
    for it in items:
        # Handle both dict entries and raw strings gracefully
        if isinstance(it, dict):
            ident = it.get("value") or it.get("doi") or json.dumps(it, sort_keys=True)
            yr = it.get("year")
            # Some JSON might store years as strings or NaN; be defensive
            try:
                if isinstance(yr, str):
                    yr = int(yr)
                elif yr != yr:  # NaN check
                    yr = None
            except Exception:
                yr = None
        else:
            ident = str(it)
            yr = None

        if ident not in seen:
            seen.add(ident)
            if isinstance(yr, int):
                years.append(yr)

    count = len(seen)
    min_y = min(years) if years else None
    max_y = max(years) if years else None
    return count, min_y, max_y

def cite_key_for(path: Path, obj: dict) -> str:
    if BIBTEX_KEY_FIELD in obj and isinstance(obj[BIBTEX_KEY_FIELD], str) and obj[BIBTEX_KEY_FIELD].strip():
        return obj[BIBTEX_KEY_FIELD].strip()
    # Fall back to a sanitized filename stem (remove characters LaTeX may dislike)
    stem = path.stem
    # Replace spaces and risky chars with nothing
    safe = "".join(ch for ch in stem if ch.isalnum() or ch in "-_")
    return safe or stem

def format_row(citekey: str, n: int, y_min, y_max, sym_dataset, sym_species,
               sym_habitat, sym_imaging, sym_light, sym_tasks, sym_algos) -> str:
    if y_min is not None and y_max is not None:
        year_span = f"{twodig_year(y_min)}–{twodig_year(y_max)}"
    elif y_min is not None:
        year_span = f"{twodig_year(y_min)}"
    elif y_max is not None:
        year_span = f"{twodig_year(y_max)}"
    else:
        year_span = "—"

    # return (
    #     rf"\cite{{{citekey}}} & {n} ({year_span}) & {sym_dataset} & {sym_species} & "
    #     rf"{sym_habitat} & {sym_imaging} & {sym_light} & {sym_tasks} & {sym_algos} \\"
    # )
    return (
        rf"\url{{{citekey}}} & {n} ({year_span}) & {sym_dataset} & {sym_species} & "
        rf"{sym_habitat} & {sym_imaging} & {sym_light} & {sym_tasks} & {sym_algos} \\"
    )

# --------- Main ---------
def main():
    valid_files = []
    json_paths = sorted([p for p in INPUT_DIR.glob("*.json") if p.is_file()])
    for p in json_paths:
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            # Skip unreadable/bad JSON
            continue
        obj["file"] = p.name
        # Filter: skip if either flag is False (we only keep if both are True)
        if not obj.get("is_computer_vision_in_wildlife_study", False):
            continue
        if not obj.get("is_review", False):
            continue

        # Compute values
        n, y_min, y_max = reviewed_papers_and_years(obj)
        citekey = obj["doi"].replace("_", "\_")#cite_key_for(p, obj)
        # citekey = ""
        sym_dataset   = symbol_for(obj, SECTION_KEYS["dataset"])
        sym_species   = symbol_for(obj, SECTION_KEYS["species"])
        sym_habitat   = symbol_for(obj, SECTION_KEYS["habitat"])
        sym_imaging   = symbol_for(obj, SECTION_KEYS["imaging"])
        sym_light     = symbol_for(obj, SECTION_KEYS["light"])
        sym_tasks     = symbol_for(obj, SECTION_KEYS["tasks"])
        sym_algos     = symbol_for(obj, SECTION_KEYS["algorithms"])

        row = format_row(
            citekey, n, y_min, y_max,
            sym_dataset, sym_species, sym_habitat,
            sym_imaging, sym_light, sym_tasks, sym_algos
        )
        print(row)
        valid_files.append(obj["file"])
    print(valid_files)

if __name__ == "__main__":
    main()
