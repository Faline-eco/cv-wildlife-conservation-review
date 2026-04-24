
from pathlib import Path
from typing import Iterator


def iterate_jsons_from_folder(folder: Path) -> Iterator[Path]:
    """Yield JSON file paths in `folder` (non-recursive) that contain a Species field."""
    if not folder.exists():
        return
    for fp in sorted(folder.glob("*.json")):
        yield fp
