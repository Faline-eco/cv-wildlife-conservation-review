from __future__ import annotations

from pathlib import Path
import pandas as pd
from typing import Iterator, Tuple, Mapping, Any


def read_seed_rows(excel_path: Path) -> Iterator[Tuple[int, Mapping[str, Any]]]:
    if excel_path.suffix == '.xlsx':
        df = pd.read_excel(excel_path)
    elif excel_path.suffix == '.csv':
        df = pd.read_csv(excel_path, sep=";")
    else:
        raise Exception("Unsupported file")
    df.columns = df.columns.str.lower()
    for idx, row in df.iterrows():
        yield idx, dict(row)
