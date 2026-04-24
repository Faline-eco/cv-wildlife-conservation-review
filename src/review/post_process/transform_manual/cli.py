import json
import os
import re
from urllib.parse import urlparse

import pandas as pd

from iucn.generate_iucn_models import to_camel, iucn_habitat_text, to_snake
from iucn.iucn_models import IUCNHabitats
from review.post_process.logger import transform_logger as log

def count_digits(string: str) -> int:
    return sum(c.isdigit() for c in string)

def get_json_structure(dataset, column):
    return {"verified": [x.strip() for x in str(dataset[column]).split(",")], "unverified": []}

def update_key(d, target_key, new_value)->bool:
    if isinstance(d, dict):
        found_any = False
        for key, value in d.items():
            if key == target_key:
                d[key] = new_value
                found_any = True
            elif isinstance(value, (dict, list)):
                found_any = found_any or update_key(value, target_key, new_value)
        return found_any
    elif isinstance(d, list):
        found_any = False
        for item in d:
            found_any = found_any or update_key(item, target_key, new_value)
        return found_any

if __name__ == '__main__':
    source_path = r"D:\LiteratureReviewCVinWC\review_input\review_raw.xlsx"
    target_path = r"D:\LiteratureReviewCVinWC\review_output\manual"

    ###################

    os.makedirs(target_path, exist_ok=True)

    iucn_regex = re.compile(r'^\s*((?:\d+\.)*\d+)\.?\s+(.*\S)\s*$', flags=re.UNICODE)
    sublabel_regex = re.compile(r'^(.*?)\s*[–-]\s*(.*)$', flags=re.UNICODE)
    iucn_habitats = {}
    iucn_sub_habitats = set()
    parent_iucn_habitas = {}
    for line in iucn_habitat_text.splitlines():
        if not line.strip():
            continue  # skip blank lines
        m = iucn_regex.match(line)
        if m:
            code, label = m.groups()
            sublabel_m = sublabel_regex.match(label)
            if sublabel_m:
                main_habitat, sub_habitat = sublabel_m.groups()
                iucn_sub_habitats.add(sub_habitat)
            iucn_habitats[code] = label
            if not "." in code or count_digits(code[code.index("."):]) == 0:
                parent_iucn_habitas[code] = label

    df = pd.read_excel(source_path)
    for idx, raw_row in df.iterrows():
        raw = dict(raw_row)
        raw_doi = raw["DOI"]
        if str(raw_doi).lower() == "nan":
            continue

        log.info(f"Processing {raw_doi}")

        is_aggriculture = raw["IsAggriculture"] > 0

        structure = {
            'doi': raw_doi,
            'year': int(raw["Year"]),
            'is_computer_vision_in_wildlife_study': not is_aggriculture,
            'is_computer_vision_in_wildlife_study_review': False,
        }

        if not is_aggriculture:
            iucns = raw["IUCN"].split(",")
            habitats = {}
            for iucn in iucns:
                m = iucn_regex.match(iucn)
                if m:
                    code, label = m.groups()
                    habitats[code] = label
            parent_habitats = {}
            for iucn in parent_iucn_habitas.values():
                parent_habitats[to_camel(iucn)] = False
            for key in habitats:
                if "." in key and count_digits(key[key.index("."):]) == 0:
                    parent_key = key[:key.index(".")]
                else:
                    parent_key = key
                parent_habitats[to_camel(iucn_habitats[parent_key])] = True

            bool_habitat = IUCNHabitats().model_dump()
            found_all = True
            found_habitas = {}
            verified_habitats = []
            unverified_habitats = []
            for habitat_key, habitat in habitats.items():
                orig = habitat
                if habitat_key in parent_iucn_habitas:
                    found = True
                else:
                    if "–" in habitat:
                        habitat = habitat[habitat.index("–") + 1:]
                    if "-" in habitat:
                        habitat = habitat[habitat.index("-") + 1:]
                    found = update_key(bool_habitat, to_snake(habitat), True)
                    found_habitas[orig] = found
                if found:
                    verified_habitats.append(orig)
                else:
                    unverified_habitats.append(orig)
                found_all = found_all and found
            if not found_all:
                log.error("Could not map all habitats to the boolean model")

            structure.update({
                'Species (Text)': get_json_structure(raw, "Species"),
                'Country': get_json_structure(raw, "Country"),
                'Imaging Method': get_json_structure(raw, "Imaging Method"),
                'Light Spectra (Text)': get_json_structure(raw, "Light Spectra"),
                'CV Tasks': get_json_structure(raw, "CV Tasks"),
                'CV Algorithms': get_json_structure(raw, "CV Algorithms"),
                'Dataset': get_json_structure(raw, "Dataset"),
                'Habitat (Manual)': get_json_structure(raw, "Habitat"),
                # "Habitat": bool_habitat,
                # "HabitatVerification": {
                #     "verified":verified_habitats,
                #     "unverified": unverified_habitats
                # },
                # "ParentHabitat": parent_habitats,
            })
        doi = urlparse(raw_doi)
        if "doi" in doi.hostname:
            target_file = doi.path.replace("/", "")
        else:
            target_file = doi.path[doi.path.rindex("/")+1:]
        with open(os.path.join(target_path, target_file + '.json'), 'w', encoding='utf-8') as f:
            json.dump(structure, f, ensure_ascii=False, indent=4)
            log.info(f"Created {target_file}")
