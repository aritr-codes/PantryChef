"""Model features and ordering (M4). One definition, used by the eval code and later the engine.

A candidate is a recipe with ``have >= 1`` and at most 2 missing needed lines (same rules as
``engine.answer``). The caller removes the gold recipe and its title group (gold-out) from the
rows before ``model_order``.

Features (plan 7.1), in this order. ``M`` is the summed weight of satisfied needed lines,
``T`` the summed weight of all needed lines, ``total`` the number of needed lines.

1. ``score``          ``M / sqrt(T)``, the shipped score (0 when ``T == 0``)
2. ``missing``        missing needed lines (0, 1 or 2)
3. ``miss_frac``      ``(T - M) / T`` (0 when ``T == 0``)
4. ``unread_missing`` missing lines that the parser could not read
5. ``total_c``        ``min(total, 12)``
6. ``short``          1 when ``total <= 2``, else 0
7. ``optional_c``     ``min(number of optional lines, 3)``
8. ``mean_w``         ``T / total`` (0 when ``T == 0``)

The weight of a line is the largest pack ``idf`` among its options (``engine._weight``).

Float rule for the TypeScript twin: only ``+ - * /`` and ``sqrt`` on stored numbers, all
correctly rounded in IEEE 754. Sums run in needed-line order, starting from ``0.0``: ``M`` adds
satisfied weights in line order, ``T`` adds all weights in line order, and the model score is
``f = ((0.0 + w0*x0) + w1*x1) + ... + w7*x7`` in feature order. The twin repeats these loops
as written, so it gives the same bits.

Ordering key: ``(-f, total, recipe_id)``. The recipe id compares as a Python string.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pantrychef.engine import Pack, _needed, _weight

FEATURES = (
    "score",
    "missing",
    "miss_frac",
    "unread_missing",
    "total_c",
    "short",
    "optional_c",
    "mean_w",
)
TOTAL_CAP = 12
OPTIONAL_CAP = 3
MAX_MISSING = 2


@dataclass(frozen=True)
class Row:
    recipe_id: str
    have: int
    total: int
    x: tuple[float, ...]  # the 8 features, in FEATURES order


def candidate_rows(pack: Pack, pantry: Iterable[str], staples: Iterable[str]) -> list[Row]:
    """Rows of every candidate recipe, in pack order. No gold-out here."""
    staple_set = set(staples)
    held = {i for i in pantry if i in pack.ingredients} - staple_set
    out = []
    for recipe in pack.recipes:
        needed = _needed(recipe, staple_set)
        total = len(needed)
        if total == 0:
            continue
        satisfied = [any(o in held for o in ln.options) for ln in needed]
        have = sum(satisfied)
        missing = total - have
        if have == 0 or missing > MAX_MISSING:
            continue
        m_sum = 0.0
        t_sum = 0.0
        for ln, ok in zip(needed, satisfied, strict=True):
            w = _weight(pack, ln)
            t_sum += w
            if ok:
                m_sum += w
        unread = sum(1 for ln, ok in zip(needed, satisfied, strict=True) if not ok and not ln.read)
        optional = sum(1 for ln in recipe.lines if ln.optional)
        x = (
            m_sum / math.sqrt(t_sum) if t_sum > 0 else 0.0,
            float(missing),
            (t_sum - m_sum) / t_sum if t_sum > 0 else 0.0,
            float(unread),
            float(min(total, TOTAL_CAP)),
            1.0 if total <= 2 else 0.0,
            float(min(optional, OPTIONAL_CAP)),
            t_sum / total if t_sum > 0 else 0.0,
        )
        out.append(Row(recipe.recipe_id, have, total, x))
    return out


def linear_score(x: Sequence[float], weights: Sequence[float]) -> float:
    f = 0.0
    for w, v in zip(weights, x, strict=True):
        f += w * v
    return f


def model_order(rows: Iterable[Row], weights: Sequence[float]) -> list[Row]:
    """Order rows by ``(-f, total, recipe_id)`` with ``f = weights . x``."""
    if len(weights) != len(FEATURES):
        raise ValueError(f"need {len(FEATURES)} weights, got {len(weights)}")
    return sorted(rows, key=lambda r: (-linear_score(r.x, weights), r.total, r.recipe_id))


def load_model(path: str | Path) -> tuple[float, ...]:
    """Raw weights from a weights file (``rank_model.v1.json``). Feature names must match."""
    data = json.loads(Path(path).read_text(encoding="utf8"))
    if tuple(data["features"]) != FEATURES:
        raise ValueError("weights file features differ from pantrychef.rank.FEATURES")
    return tuple(float(w) for w in data["weights"])
