"""Ranking arms (M2). Every arm ranks the SAME candidate set: recipes with have >= 1.

Arms differ only in order. ``shipped`` applies the engine order key to the full set.
It does not call ``answer()``, which drops recipes with more than 2 missing lines.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from pantrychef.engine import Pack, _needed, _weight

ARMS = ("random", "overlap", "idf_flat", "shipped")


@dataclass(frozen=True)
class Scored:
    recipe_id: str
    have: int
    total: int
    score: float  # engine score (idf-weighted)


def candidates(pack: Pack, pantry: set[str], staples: set[str]) -> list[Scored]:
    """All recipes with total > 0 and have >= 1, in pack order. Same rules as ``answer()``."""
    held = {i for i in pantry if i in pack.ingredients} - staples
    out = []
    for recipe in pack.recipes:
        needed = _needed(recipe, staples)
        if not needed:
            continue
        satisfied = [any(o in held for o in ln.options) for ln in needed]
        have = sum(satisfied)
        if have == 0:
            continue
        den = sum(_weight(pack, ln) for ln in needed)
        num = sum(_weight(pack, ln) for ln, ok in zip(needed, satisfied, strict=True) if ok)
        out.append(
            Scored(recipe.recipe_id, have, len(needed), num / math.sqrt(den) if den > 0 else 0.0)
        )
    return out


def order(arm: str, cands: list[Scored], seed_key: str = "") -> list[Scored]:
    """Order keys: ``random`` (seeded by seed_key), ``overlap`` (-have, total, id),
    ``idf_flat`` (-score, total, id), ``shipped`` (missing, -score, total, id)."""
    if arm == "random":
        out = sorted(cands, key=lambda c: c.recipe_id)  # fixed start, so the seed decides
        random.Random(seed_key).shuffle(out)
        return out
    if arm == "overlap":
        return sorted(cands, key=lambda c: (-c.have, c.total, c.recipe_id))
    if arm == "idf_flat":
        return sorted(cands, key=lambda c: (-c.score, c.total, c.recipe_id))
    if arm == "shipped":
        return sorted(cands, key=lambda c: (c.total - c.have, -c.score, c.total, c.recipe_id))
    raise ValueError(f"unknown arm {arm!r}")
