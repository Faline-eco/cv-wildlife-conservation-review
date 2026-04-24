from __future__ import annotations

from typing import Dict, Any
from .typing_aliases import RowLike
from ..utils.text import parse_list_cell


def should_skip_row(row: RowLike) -> bool:
    """Encapsulates row-level filtering based on the original script's rules:
    - Skip if 'IsAggriculture' (typo preserved) is True
    - Skip if Habitat has exactly one item equal to 'non-natural'
    - Skip if Imaging Method has exactly one of specific items (microphone, spectrometer, acoustic camera, microscope)
    """
    # Keep original misspelled key if present, else attempt a better-spelled alternative.
    is_ag = bool(row.get('IsAggriculture'.lower()) or row.get('IsAgriculture'.lower()) or False)
    if is_ag:
        return True

    habitats = parse_list_cell(row.get('Habitat'.lower()))
    if len(habitats) == 1 and habitats[0].strip().lower() == 'non-natural':
        return True

    imaging_methods = [x.strip().lower() for x in parse_list_cell(row.get('Imaging Method'.lower()))]
    blocked = {"microphone", "spectrometer", "acoustic camera", "microscope"}
    if len(imaging_methods) == 1 and imaging_methods[0] in blocked:
        return True

    return False


def is_recent_enough(year: int | None, min_year: int) -> bool:
    return year is not None and int(year) >= int(min_year)
