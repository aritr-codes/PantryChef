"""Masked pantries with distractors and dev/test assignment (M2). See plan section 3."""

from __future__ import annotations

import random
from dataclasses import dataclass

from pantrychef.engine import Pack, Recipe


@dataclass(frozen=True)
class EvalPantry:
    gold_id: str
    draw: int
    pantry: tuple[str, ...]  # sorted ingredient ids
    masked: tuple[str, ...]  # first option id of each masked line
    distractors: tuple[str, ...]
    sampler: str  # "uniform" | "popularity" | "none"
    split: str  # "dev" | "test"


def mask_count(total: int) -> int:
    """m = max(1, floor(0.25 * total + 0.5)). Round half up. total 6 gives 2."""
    raise NotImplementedError


def eligible(recipe: Recipe, staples: set[str]) -> bool:
    """total >= 3 and at least m maskable lines (required, non-staple-covered, read)."""
    raise NotImplementedError


def assign_splits(recipes: list[Recipe], seed: int = 42) -> dict[str, str]:
    """recipe_id to "dev" or "test".

    Group by normalised title, sort groups by sha256(f"{seed}:{key}"), cut 50/50.
    """
    raise NotImplementedError


def sample_distractors(
    sampler: str, pack: Pack, exclude: set[str], d: int, rng: random.Random
) -> tuple[str, ...]:
    """``uniform``: even over non-staple ids.

    ``popularity``: probability proportional to document frequency.

    Never returns an id in ``exclude`` (the option ids of the gold recipe). No repeats.
    """
    raise NotImplementedError


def build_pantries(
    pack: Pack, sampler: str, d: int, seed: int = 42, draws: int = 3
) -> list[EvalPantry]:
    """One EvalPantry per eligible gold recipe per draw.

    rng = random.Random(f"{seed}:{recipe_id}:{draw}").
    """
    raise NotImplementedError
