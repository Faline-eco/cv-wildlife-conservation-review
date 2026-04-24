from __future__ import annotations

import abc
from typing import Iterable, List

from review.post_process.species_translation.models import Direction


class AbstractTranslator(abc.ABC):
    """A strategy interface for every translation back-end."""

    slug: str  # short unique identifier, e.g. “GBIF”

    @abc.abstractmethod
    def translate(self, names: Iterable[str], direction: Direction) -> List[str]:
        """Return one *best* translation per input name.

        Implementations may raise a `TranslationError`.
        """
        ...


class TranslationError(RuntimeError):
    """Wrap all remote API errors so the service layer can react uniformly."""
