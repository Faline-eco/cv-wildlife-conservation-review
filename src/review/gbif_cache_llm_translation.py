#!/usr/bin/env python3
"""
Script to process species names from a GBIF JSON file and generate
accurate taxonomic structures using an LLM (Google Gemini).
"""

import asyncio
import json
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel
from typing import Optional

from genai_client import LLMClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class TaxonomicMatch(BaseModel):
    """Pydantic model for the taxonomic match structure."""
    kingdom: Optional[str] = None
    phylum: Optional[str] = None
    class_: Optional[str] = None  # 'class' is reserved in Python
    order: Optional[str] = None
    family: Optional[str] = None
    genus: Optional[str] = None
    species: Optional[str] = None  # For subspecies cases
    canonicalName: str
    scientificName: str
    rank: str  # KINGDOM, PHYLUM, CLASS, ORDER, FAMILY, GENUS, SPECIES, SUBSPECIES


# JSON schema for Gemini's native structured output
TAXONOMIC_SCHEMA = {
    "type": "object",
    "properties": {
        "kingdom": {"type": "string", "nullable": True},
        "phylum": {"type": "string", "nullable": True},
        "class": {"type": "string", "nullable": True},
        "order": {"type": "string", "nullable": True},
        "family": {"type": "string", "nullable": True},
        "genus": {"type": "string", "nullable": True},
        "species": {"type": "string", "nullable": True},
        "canonicalName": {"type": "string"},
        "scientificName": {"type": "string"},
        "rank": {"type": "string",
                 "enum": ["KINGDOM", "PHYLUM", "CLASS", "ORDER", "FAMILY", "GENUS", "SPECIES", "SUBSPECIES"]}
    },
    "required": ["canonicalName", "scientificName", "rank"]
}

SYSTEM_PROMPT = """You are a taxonomic expert. Given a species name (which may be a scientific name, common name, abbreviation, singular/plural form, or a higher taxonomic level), return the accurate GBIF-style taxonomic classification.

IMPORTANT RULES:
1. Return ONLY the taxonomic levels that apply. For example:
   - "Aves" is a CLASS, so only return kingdom, phylum, class (not order, family, genus)
   - "Canidae" is a FAMILY, so return kingdom through family (not genus)
   - "Pan troglodytes" is a SPECIES, so return the full hierarchy

2. The "rank" field must reflect the LOWEST taxonomic level of the queried name:
   - "Aves" → rank: "CLASS"
   - "Mammalia" → rank: "CLASS"  
   - "Canidae" → rank: "FAMILY"
   - "Canis" → rank: "GENUS"
   - "Canis lupus" → rank: "SPECIES"
   - "Canis lupus familiaris" → rank: "SUBSPECIES"

3. canonicalName: The standardized scientific name without author/year
4. scientificName: The full scientific name with author and year if applicable

5. For common names (e.g., "dog", "cat", "eagle"), resolve to the most likely species and provide full taxonomy.

6. Fix typos in species names (e.g., "pan troglydes" → "Pan troglodytes")

7. Use standard taxonomic databases (GBIF, ITIS, NCBI) conventions.

8. If the name is ambiguous or could refer to multiple taxa, choose the most common/well-known interpretation.

9. Leave fields as null if they don't apply to the taxonomic level (e.g., no genus for a family-level query)."""


async def lookup_species(client: LLMClient, species_name: str) -> dict:
    """Look up a single species name using the LLM."""

    prompt = f"""Provide the taxonomic classification for: "{species_name}"

Return a JSON object with the taxonomic hierarchy. Only include taxonomic levels that apply to this name's rank."""

    try:
        response = await client.generate(
            contents=prompt,
            system_instruction=SYSTEM_PROMPT,
            response_model=TAXONOMIC_SCHEMA,
            use_strong_model=True
        )

        match_data = json.loads(response)

        # Rename 'class' field for output (handle Python reserved word)
        result = {
            "cachedAt": datetime.now(timezone.utc).isoformat() + "Z",
            "match": {}
        }

        # Build match dict, filtering out None values and empty strings
        for key in ["kingdom", "phylum", "class", "order", "family", "genus", "species",
                    "canonicalName", "scientificName", "rank"]:
            if key in match_data and match_data[key] is not None and match_data[key] != "":
                result["match"][key] = match_data[key]

        return result

    except Exception as e:
        logging.error(f"Failed to lookup '{species_name}': {e}")
        return {
            "cachedAt": datetime.now(timezone.utc).isoformat() + "Z",
            "error": str(e),
            "match": None
        }


async def process_gbif_file(
        input_path: Path,
        output_path: Path,
        api_keys: list[str],
        model_name: str = "gemini-2.0-flash",
        rpm: int = 10
):
    """Process the GBIF JSON file and generate LLM-based taxonomic lookups."""

    # Load input file
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    hits = data.get("hits", {})
    misses = data.get("misses", {})

    all_species = list(hits.keys()) + list(misses.keys())
    total = len(all_species)

    logging.info(f"Processing {len(hits)} hits and {len(misses)} misses ({total} total)")

    # Initialize client
    client = LLMClient(
        api_keys=api_keys,
        light_model_name=model_name,
        strong_model_name=model_name,
        rpm=rpm,
        use_native_json_schema=True
    )

    # Process all species
    results = {
        "metadata": {
            "processedAt": datetime.now(timezone.utc).isoformat() + "Z",
            "model": model_name,
            "totalProcessed": total
        },
        "species": {}
    }

    for idx, species_name in enumerate(all_species, 1):
        logging.info(f"[{idx}/{total}] Processing: {species_name}")
        result = await lookup_species(client, species_name)
        results["species"][species_name] = result

        # Save intermediate results every 10 species
        if idx % 5 == 0:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            logging.info(f"Saved intermediate results ({idx}/{total})")

    # Save final results
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    logging.info(f"Done! Results saved to {output_path}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Process GBIF species names with LLM")
    parser.add_argument("-i", "--input", type=Path, default=Path(r"D:\LiteratureReviewCVinWC\review_output\gbif_cache.json"), help="Input JSON file with hits/misses")
    parser.add_argument("-o", "--output", type=Path, default=Path(r"/review_output/llm_cache.json"), help="Output JSON file")
    parser.add_argument("-k", "--api-keys", type=str, default="AIzaSyA97_daJ2odbnImSAt66rr6z5mdd73kfE8",
                        help="Comma-separated Google AI API keys")
    parser.add_argument("-m", "--model", type=str, default="gemini-2.5-pro",
                        help="Model name (default: gemini-3-pro-preview)")
    parser.add_argument("-r", "--rpm", type=int, default=150,
                        help="Requests per minute limit (default: 10)")

    args = parser.parse_args()

    if args.output is None:
        args.output = args.input.with_stem(args.input.stem + "_llm_resolved")

    api_keys = [k.strip() for k in args.api_keys.split(",")]

    asyncio.run(process_gbif_file(
        input_path=args.input,
        output_path=args.output,
        api_keys=api_keys,
        model_name=args.model,
        rpm=args.rpm
    ))


if __name__ == "__main__":
    main()