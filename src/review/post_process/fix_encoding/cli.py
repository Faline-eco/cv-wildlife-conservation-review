import json
import os
import shutil
from pathlib import Path

from review.post_process.util import iterate_jsons_from_folder

if __name__ == '__main__':
    dataset_folder = r"D:\LiteratureReviewCVinWC\review_output\20250731"

    for fp in iterate_jsons_from_folder(Path(dataset_folder)):
        try:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    paper = json.load(f)
            except UnicodeDecodeError:
                with open(fp, "r") as f:
                    paper = json.load(f)
        except Exception as e:
            corrupt_path = os.path.join(dataset_folder, "corrupt")
            os.makedirs(corrupt_path, exist_ok=True)
            shutil.copy2(str(fp), corrupt_path)
            continue

        new_path = os.path.join(dataset_folder, "utf8")
        os.makedirs(new_path, exist_ok=True)
        with open(os.path.join(new_path, os.path.basename(fp)), "w", encoding="utf-8") as f:
            json.dump(paper, f, ensure_ascii=False, indent=4)