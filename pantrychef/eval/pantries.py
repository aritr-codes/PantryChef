"""Masked pantries with distractors and dev/test assignment (M2). See plan section 3."""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass

from pantrychef.engine import Line, Pack, Recipe

SAMPLERS = ("uniform", "popularity")


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
    """m = max(1, floor(0.25 * total + 0.5)). Round half up. total 6 gives 2.

    floor(0.25 * t + 0.5) == (t + 2) // 4 in integers, so every language agrees.
    """
    return max(1, (total + 2) // 4)


def _needed(recipe: Recipe, staples: set[str]) -> list[Line]:
    return [
        ln for ln in recipe.lines if not ln.optional and not any(o in staples for o in ln.options)
    ]


def _maskable(recipe: Recipe, staples: set[str]) -> list[Line]:
    return [ln for ln in _needed(recipe, staples) if ln.read and ln.options]


def eligible(recipe: Recipe, staples: set[str]) -> bool:
    """total >= 3 and at least m maskable lines (required, non-staple-covered, read)."""
    total = len(_needed(recipe, staples))
    return total >= 3 and len(_maskable(recipe, staples)) >= mask_count(total)


def _title_key(title: str) -> str:
    t = re.sub(r"\([^)]*\)", " ", title.lower())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def assign_splits(recipes: list[Recipe], seed: int = 42) -> dict[str, str]:
    """recipe_id to "dev" or "test".

    Group by normalised title, sort groups by sha256(f"{seed}:{key}"), cut 50/50.
    The first ``n_groups // 2`` groups are dev. The rest are test.
    """
    groups: dict[str, list[str]] = {}
    for r in recipes:
        groups.setdefault(_title_key(r.title), []).append(r.recipe_id)
    ordered = sorted(groups, key=lambda k: hashlib.sha256(f"{seed}:{k}".encode()).hexdigest())
    cut = len(ordered) // 2
    return {
        rid: ("dev" if i < cut else "test") for i, key in enumerate(ordered) for rid in groups[key]
    }


def document_frequency(pack: Pack) -> dict[str, int]:
    """Number of recipes with at least one line that lists the id."""
    df: dict[str, int] = {}
    for r in pack.recipes:
        for i in {o for ln in r.lines for o in ln.options}:
            df[i] = df.get(i, 0) + 1
    return df


def sample_distractors(
    sampler: str, pack: Pack, exclude: set[str], d: int, rng: random.Random
) -> tuple[str, ...]:
    """``uniform``: even over non-staple ids.

    ``popularity``: probability proportional to document frequency.

    Never returns an id in ``exclude`` (the option ids of the gold recipe). No repeats.
    """
    if sampler not in SAMPLERS:
        raise ValueError(f"unknown sampler {sampler!r}")
    pool = sorted(i for i, ing in pack.ingredients.items() if not ing.staple and i not in exclude)
    if sampler == "popularity":
        df = document_frequency(pack)
        pool = [i for i in pool if df.get(i, 0) > 0]
    if d > len(pool):
        raise ValueError(f"cannot draw {d} distractors from {len(pool)} ids")
    if sampler == "uniform":
        return tuple(rng.sample(pool, d))
    weights = [df[i] for i in pool]
    out: list[str] = []
    for _ in range(d):  # sequential draws without replacement
        k = rng.choices(range(len(pool)), weights=weights)[0]
        out.append(pool.pop(k))
        weights.pop(k)
    return tuple(out)


def build_pantries(
    pack: Pack, sampler: str, d: int, seed: int = 42, draws: int = 3
) -> list[EvalPantry]:
    """One EvalPantry per eligible gold recipe per draw.

    rng = random.Random(f"{seed}:{recipe_id}:{draw}"). The mask is drawn first, so the same
    seed gives the same masks for every ``d`` and every sampler.
    """
    if d < 0:
        raise ValueError("d must be >= 0")
    if d > 0 and sampler not in SAMPLERS:
        raise ValueError(f"sampler must be one of {SAMPLERS} when d > 0, got {sampler!r}")
    recorded = sampler if d > 0 else "none"
    staples = set(pack.default_staples)
    splits = assign_splits(list(pack.recipes), seed)
    out: list[EvalPantry] = []
    for recipe in pack.recipes:
        if not eligible(recipe, staples):
            continue
        maskable = _maskable(recipe, staples)
        m = mask_count(len(_needed(recipe, staples)))
        gold_ids = {o for ln in recipe.lines for o in ln.options}
        for draw in range(draws):
            rng = random.Random(f"{seed}:{recipe.recipe_id}:{draw}")
            masked_idx = set(rng.sample(range(len(maskable)), m))
            masked = tuple(min(maskable[i].options) for i in sorted(masked_idx))
            kept = {min(ln.options) for i, ln in enumerate(maskable) if i not in masked_idx}
            dis = sample_distractors(sampler, pack, gold_ids, d, rng) if d > 0 else ()
            out.append(
                EvalPantry(
                    gold_id=recipe.recipe_id,
                    draw=draw,
                    pantry=tuple(sorted(kept | set(dis))),
                    masked=masked,
                    distractors=dis,
                    sampler=recorded,
                    split=splits[recipe.recipe_id],
                )
            )
    return out
