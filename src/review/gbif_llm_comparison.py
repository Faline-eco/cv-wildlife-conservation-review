#!/usr/bin/env python3
"""
Compare GBIF API results with LLM-generated taxonomic data.
All string comparisons are case-insensitive.
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict

# Fields to compare (in taxonomic hierarchy order)
TAXONOMIC_FIELDS = ["kingdom", "phylum", "class", "order", "family", "genus", "canonicalName", "scientificName", "rank"]


def normalize(value):
    """Normalize a value for comparison (lowercase, strip whitespace)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.lower().strip()
    return value


def extract_all_species(data: dict) -> dict:
    """Extract all species from hits and misses into a single dict."""
    all_species = {}

    # Handle different structures
    if "hits" in data:
        for name, entry in data.get("hits", {}).items():
            all_species[normalize(name)] = entry
    if "misses" in data:
        for name, entry in data.get("misses", {}).items():
            all_species[normalize(name)] = entry
    if "species" in data:  # Alternative structure
        for name, entry in data.get("species", {}).items():
            all_species[normalize(name)] = entry

    return all_species


def get_match_data(entry: dict) -> dict | None:
    """Extract the match data from an entry, handling different structures."""
    if entry is None:
        return None

    # LLM format: {"cachedAt": ..., "match": {...}}
    if "match" in entry:
        return entry.get("match")

    # GBIF format might have match directly or nested
    if "canonicalName" in entry or "kingdom" in entry:
        return entry

    return None


def compare_entries(name: str, gbif_entry: dict, llm_entry: dict) -> dict:
    """Compare a single species entry between GBIF and LLM."""
    result = {
        "species": name,
        "status": "match",
        "field_comparisons": {},
        "gbif_only_fields": [],
        "llm_only_fields": [],
        "mismatches": []
    }

    gbif_match = get_match_data(gbif_entry)
    llm_match = get_match_data(llm_entry)

    if gbif_match is None and llm_match is None:
        result["status"] = "both_missing"
        return result

    if gbif_match is None:
        result["status"] = "gbif_missing"
        return result

    if llm_match is None:
        result["status"] = "llm_missing"
        return result

    # Compare each field
    all_fields = set(TAXONOMIC_FIELDS)

    for field in all_fields:
        gbif_val = normalize(gbif_match.get(field))
        llm_val = normalize(llm_match.get(field))

        if gbif_val is None and llm_val is None:
            continue
        elif gbif_val is None:
            result["llm_only_fields"].append(field)
            result["field_comparisons"][field] = {"gbif": None, "llm": llm_match.get(field)}
        elif llm_val is None:
            result["gbif_only_fields"].append(field)
            result["field_comparisons"][field] = {"gbif": gbif_match.get(field), "llm": None}
        elif gbif_val == llm_val:
            result["field_comparisons"][field] = {"gbif": gbif_match.get(field), "llm": llm_match.get(field),
                                                  "match": True}
        else:
            result["mismatches"].append(field)
            result["field_comparisons"][field] = {"gbif": gbif_match.get(field), "llm": llm_match.get(field),
                                                  "match": False}

    if result["mismatches"]:
        result["status"] = "mismatch"
    elif result["gbif_only_fields"] or result["llm_only_fields"]:
        result["status"] = "partial_match"

    return result


def compare_files(gbif_path: Path, llm_path: Path) -> dict:
    """Compare two JSON files and return detailed comparison results."""

    with open(gbif_path, 'r', encoding='utf-8') as f:
        gbif_data = json.load(f)

    with open(llm_path, 'r', encoding='utf-8') as f:
        llm_data = json.load(f)

    gbif_species = extract_all_species(gbif_data)
    llm_species = extract_all_species(llm_data)

    all_names = set(gbif_species.keys()) | set(llm_species.keys())

    results = {
        "summary": {
            "total_species": len(all_names),
            "gbif_count": len(gbif_species),
            "llm_count": len(llm_species),
            "exact_matches": 0,
            "partial_matches": 0,
            "mismatches": 0,
            "gbif_only": 0,
            "llm_only": 0,
            "both_missing": 0
        },
        "field_mismatch_counts": defaultdict(int),
        "comparisons": []
    }

    for name in sorted(all_names):
        gbif_entry = gbif_species.get(name)
        llm_entry = llm_species.get(name)

        if gbif_entry is None:
            results["summary"]["llm_only"] += 1
            results["comparisons"].append({
                "species": name,
                "status": "llm_only"
            })
            continue

        if llm_entry is None:
            results["summary"]["gbif_only"] += 1
            results["comparisons"].append({
                "species": name,
                "status": "gbif_only"
            })
            continue

        comparison = compare_entries(name, gbif_entry, llm_entry)
        results["comparisons"].append(comparison)

        if comparison["status"] == "match":
            results["summary"]["exact_matches"] += 1
        elif comparison["status"] == "partial_match":
            results["summary"]["partial_matches"] += 1
        elif comparison["status"] == "mismatch":
            results["summary"]["mismatches"] += 1
            for field in comparison["mismatches"]:
                results["field_mismatch_counts"][field] += 1
        elif comparison["status"] == "both_missing":
            results["summary"]["both_missing"] += 1
        elif comparison["status"] == "gbif_missing":
            results["summary"]["gbif_only"] += 1
        elif comparison["status"] == "llm_missing":
            results["summary"]["llm_only"] += 1

    # Convert defaultdict to regular dict for JSON serialization
    results["field_mismatch_counts"] = dict(results["field_mismatch_counts"])

    return results


def print_summary(results: dict):
    """Print a human-readable summary of the comparison."""
    s = results["summary"]

    print("\n" + "=" * 60)
    print("COMPARISON SUMMARY")
    print("=" * 60)
    print(f"Total species compared: {s['total_species']}")
    print(f"  - In GBIF: {s['gbif_count']}")
    print(f"  - In LLM:  {s['llm_count']}")
    print()
    print(f"Exact matches:    {s['exact_matches']:5d} ({100 * s['exact_matches'] / max(1, s['total_species']):.1f}%)")
    print(
        f"Partial matches:  {s['partial_matches']:5d} ({100 * s['partial_matches'] / max(1, s['total_species']):.1f}%)")
    print(f"Mismatches:       {s['mismatches']:5d} ({100 * s['mismatches'] / max(1, s['total_species']):.1f}%)")
    print(f"GBIF only:        {s['gbif_only']:5d}")
    print(f"LLM only:         {s['llm_only']:5d}")
    print(f"Both missing:     {s['both_missing']:5d}")

    if results["field_mismatch_counts"]:
        print("\n" + "-" * 40)
        print("MISMATCHES BY FIELD:")
        print("-" * 40)
        for field, count in sorted(results["field_mismatch_counts"].items(), key=lambda x: -x[1]):
            print(f"  {field}: {count}")


def print_mismatches(results: dict, limit: int = 20):
    """Print detailed mismatch information."""
    mismatches = [c for c in results["comparisons"] if c.get("status") == "mismatch"]

    if not mismatches:
        print("\nNo mismatches found!")
        return

    print(f"\n" + "=" * 60)
    print(f"MISMATCH DETAILS (showing {min(limit, len(mismatches))} of {len(mismatches)})")
    print("=" * 60)

    for comp in mismatches[:limit]:
        print(f"\n--- {comp['species']} ---")
        for field in comp.get("mismatches", []):
            fc = comp["field_comparisons"].get(field, {})
            print(f"  {field}:")
            print(f"    GBIF: {fc.get('gbif')}")
            print(f"    LLM:  {fc.get('llm')}")


def main():
    parser = argparse.ArgumentParser(description="Compare GBIF and LLM taxonomic results")
    parser.add_argument("-g", "--gbif_file", default=r"D:\LiteratureReviewCVinWC\review_output\gbif_cache.json", type=Path, help="GBIF JSON file")
    parser.add_argument("-l", "--llm_file", default=r"D:\LiteratureReviewCVinWC\review_output\llm.json", type=Path, help="LLM JSON file")
    parser.add_argument("-o", "--output", type=Path, help="Output JSON file for full results")
    parser.add_argument("-m", "--show-mismatches", type=int, default=20,
                        help="Number of mismatches to display (default: 20)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show all comparisons, not just mismatches")

    args = parser.parse_args()

    results = compare_files(args.gbif_file, args.llm_file)

    # Print summary
    print_summary(results)

    # Print mismatches
    print_mismatches(results, args.show_mismatches)

    # Save full results if requested
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nFull results saved to: {args.output}")


if __name__ == "__main__":
    main()