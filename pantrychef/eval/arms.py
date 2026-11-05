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


class CandidateIndex:
    """Fast ``candidates`` for many pantries. Same results as ``candidates``, bit for bit.

    It precomputes the needed lines and weights of every recipe once, and an inverted map from
    an ingredient id to the lines that list it. A pantry then touches only the recipes that
    share an id with it. Scores add the weights in line order, as ``answer()`` does.
    """

    def __init__(self, pack: Pack, staples: set[str]):
        self.pack = pack
        self.staples = set(staples)
        self.ids: list[str] = []
        self.weights: list[list[float]] = []
        self.total: list[int] = []
        self.den: list[float] = []
        self.by_id: dict[str, list[tuple[int, int]]] = {}
        for recipe in pack.recipes:
            needed = _needed(recipe, self.staples)
            if not needed:
                continue
            r = len(self.ids)
            w = [_weight(pack, ln) for ln in needed]
            self.ids.append(recipe.recipe_id)
            self.weights.append(w)
            self.total.append(len(needed))
            self.den.append(sum(w))
            for li, ln in enumerate(needed):
                for o in set(ln.options):
                    self.by_id.setdefault(o, []).append((r, li))

    def candidates(self, pantry: set[str]) -> list[Scored]:
        held = {i for i in pantry if i in self.pack.ingredients} - self.staples
        hit: dict[int, set[int]] = {}
        for i in held:
            for r, li in self.by_id.get(i, ()):
                hit.setdefault(r, set()).add(li)
        out = []
        for r in sorted(hit):  # pack order
            lines = sorted(hit[r])
            num = sum(self.weights[r][li] for li in lines)
            den = self.den[r]
            out.append(
                Scored(
                    self.ids[r], len(lines), self.total[r], num / math.sqrt(den) if den > 0 else 0.0
                )
            )
        return out


def visible_ids(cands: list[Scored], limit: int = 10) -> set[str]:
    """Recipe ids that ``answer()`` shows: at most 2 missing lines, top ``limit`` in each group."""
    shown: set[str] = set()
    for missing in (0, 1, 2):
        group = sorted(
            (c for c in cands if c.total - c.have == missing),
            key=lambda c: (-c.score, c.total, c.recipe_id),
        )
        shown.update(c.recipe_id for c in group[:limit])
    return shown


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
