import logging
import os
import json
from pathlib import Path

import pandas as pd

# Folder containing your JSON files
input_folder = r"D:\LiteratureReviewCVinWC\review_output\manual"

# Fields to process with verified/unverified extraction
fields_with_verified_unverified = [
    "Species (Text)(translated)",
    "Species (Images)(translated)",
    "Country",
    "Imaging Method",
    "Light Spectra (Text)",
    "Light Spectra (Images)",
    "Imaging Method (new)",
    "Imaging Method (Text) (new)",
    "Light Spectra (Text) (new)",
    "Light Spectra (Images) (new)",
    "CV Tasks",
    "CV Algorithms",
]


def extract_values(entry):
    """Extract verified and unverified lists, handling missing keys."""
    verified = entry.get("verified", [])
    unverified = entry.get("unverified", [])
    return verified, unverified


def extract_dataset(entry):
    """Extract only the 'value' from verified/unverified entries."""

    def get_values(items):
        return [i["value"] if isinstance(i, dict) else i for i in items]

    verified = get_values(entry.get("verified", []))
    unverified = get_values(entry.get("unverified", []))
    return verified, unverified


def extract_habitat_values(entry):
    """Extract all 'value' from evidences list."""
    return [ev.get("value") for ev in entry.get("evidences", [])]


data_rows = []

for file_name in os.listdir(input_folder):
    if file_name.endswith(".json") and not file_name.startswith("_config.json"):
        file_path = os.path.join(input_folder, file_name)
        with open(file_path, "r") as f:
            print(file_path)
            try:
                content = json.load(f)
            except Exception as e:
                print(f"Problem with {file_path}")
                continue
        # Apply filter
        if content.get("is_computer_vision_in_wildlife_study") and not content.get(
                "is_computer_vision_in_wildlife_study_review"):
            row = {"file": file_name, "doi": content.get("doi"), "year": content.get("year")}

            # Extract for main fields
            for field in fields_with_verified_unverified:
                verified, unverified = extract_values(content.get(field, {}))
                if " (new)" in field:
                    field = field.replace(" (new)", "")
                if "(translated)" in field:
                    row[f"{field} - verified"] = [y for x in verified for y in x.get("translations")]
                    row[f"{field} - unverified"] = [y for x in unverified for y in x.get("translations")]
                else:
                    row[f"{field} - verified"] = verified
                    row[f"{field} - unverified"] = unverified


            # Dataset special case
            dataset_verified, dataset_unverified = extract_dataset(content.get("Dataset", {}))
            row["Dataset - verified"] = dataset_verified
            row["Dataset - unverified"] = dataset_unverified

            # HabitatVerification evidences
            row["HabitatVerification values"] = extract_habitat_values(content.get("HabitatVerification", {}))

            # ParentHabitat evidences (boolean categories -> extract names that are True)
            if input_folder.endswith("manual"):
                row["ParentHabitat values"] = [k for k, v in content.get("ParentHabitat (fixed)", {}).items() if v is True]
            else:
                row["ParentHabitat values"] = [k for k, v in content.get("ParentHabitat", {}).items() if v is True]
            data_rows.append(row)

# Create DataFrame
df = pd.DataFrame(data_rows)
pd.set_option("display.max_columns", None)
# pd.set_option("display.max_rows", None)
pd.set_option("display.max_colwidth", None)
# Show result
print(df.head())
input_folder_path = Path(input_folder)
folder_name = input_folder_path.name
df.to_parquet(os.path.join(input_folder_path.parent, f"{folder_name}.parquet"), index=False, compression="zstd")
