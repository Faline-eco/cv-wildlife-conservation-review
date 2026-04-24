import argparse
import json
from pathlib import Path

from review.post_process.logger import animal_translate_logger
from review.post_process.species_translation.services.translation_service import TranslationService
from review.post_process.util import iterate_jsons_from_folder


def main():
    """Translate the `Species` field of every JSON in *folder*."""

    p = argparse.ArgumentParser(description="WildCV literature extractor")
    p.add_argument("--input", default=r"D:\LiteratureReviewCVinWC\review_output\manual", help="Path to the directory containing the reviews")
    p.add_argument(
        "--fields",
        nargs="+",  # one or more values
        help="List of species fields",
        type=str,
        default=["Species (Text)", "Species (Images)"]
    )

    args = p.parse_args()
    svc = TranslationService(cache_path=Path(args.input + "_cache.json"))
    errors = []
    for fp in iterate_jsons_from_folder(Path(args.input)):
        doi = fp.stem
        try:
            with open(fp, "r", encoding="utf-8") as f:
                paper = json.load(f)
        except UnicodeDecodeError:
            with open(fp, "r") as f:
                paper = json.load(f)
        except Exception as e:
            animal_translate_logger.error(e)
            errors.append(fp)
            continue

        for species_field in args.fields:
            species = paper.get(species_field)
            if species is None:
                animal_translate_logger.info(f"No species information for {doi}")
                continue

            paper[species_field + "(translated)"] = {}
            for dataset in ["verified", "unverified"]:
                responses = svc.translate_many(species[dataset], file_id=doi)
                paper[species_field + "(translated)"][dataset] = [response.model_dump() for response in responses]
                animal_translate_logger.info("%s: %s", doi, [f"{r.original} → {r.translations}" for r in responses])

        with open(fp, "w", encoding="utf-8") as f:
            json.dump(paper, f)
    animal_translate_logger.error(f"Problems with: {errors}")

if __name__ == "__main__":
    main()
