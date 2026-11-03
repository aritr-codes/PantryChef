"""Ranking arms (M2). Every arm ranks the SAME candidate set: recipes with have >= 1.

Arms differ only in order. ``shipped`` applies the engine order key to the full set.
It does not call ``answer()``, which drops recipes with more than 2 missing lines.
"""

from __future__ import annotations

from dataclasses import dataclass

from pantrychef.engine import Pack


@dataclass(frozen=True)
class Scored:
    recipe_id: str
    have: int
    total: int
    score: float  # engine score (idf-weighted)


def candidates(pack: Pack, pantry: set[str], staples: set[str]) -> list[Scored]:
    """All recipes with total > 0 and have >= 1, in pack order. Same rules as ``answer()``."""
    raise NotImplementedError


def order(arm: str, cands: list[Scored], seed_key: str = "") -> list[Scored]:
    """Order keys: ``random`` (seeded by seed_key), ``overlap`` (-have, total, id),
    ``idf_flat`` (-score, total, id), ``shipped`` (missing, -score, total, id)."""
    raise NotImplementedError
