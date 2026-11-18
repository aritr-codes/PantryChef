"""How an M4 list is built: one definition for the sheets and the training items (plan 5.2, 8.1).

A list is the top 5 of one arm over one shared candidate set: recipes with ``have >= 1`` and at
most 2 missing lines, with the gold recipe and its title group removed (gold-out). An arm is a
name known to ``arms.order`` or an *orderer*: ``fn(cands, pantry) -> cands in order``.
The model arm ``rank_linear`` is an orderer over ``pantrychef.rank`` rows.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence

from pantrychef.engine import Pack
from pantrychef.eval.arms import CandidateIndex, Scored, order
from pantrychef.rank import candidate_rows, model_order

TOP = 5
MAX_MISSING = 2  # the product shows at most two missing lines, so every list uses that set

Orderers = dict[str, Callable[[list[Scored], Sequence[str]], list[Scored]]]


def excluded_ids(group_of: dict[str, str], gold_id: str, title_group: str) -> set[str]:
    """The gold recipe and every recipe of its title group."""
    return {gold_id} | {r for r, g in group_of.items() if g == title_group}


def top_lists(
    index: CandidateIndex,
    arms: Sequence[str],
    pantry: Sequence[str],
    exclude: set[str],
    orderers: Orderers,
) -> dict[str, list[Scored]]:
    """Top 5 of each arm over one shared candidate set (at most 2 missing, ``exclude`` removed)."""
    cands = [
        c
        for c in index.candidates(set(pantry))
        if c.total - c.have <= MAX_MISSING and c.recipe_id not in exclude
    ]  # same set for every arm: only the order differs
    return {
        a: (orderers[a](cands, pantry) if a in orderers else order(a, cands))[:TOP] for a in arms
    }


def model_orderer(pack: Pack, weights: Sequence[float]):
    """Orderer for ``rank_linear``: ``pantrychef.rank.model_order`` over the given candidates."""
    staples = set(pack.default_staples)

    def orderer(cands: list[Scored], pantry: Sequence[str]) -> list[Scored]:
        keep = {c.recipe_id: c for c in cands}
        rows = [r for r in candidate_rows(pack, pantry, staples) if r.recipe_id in keep]
        if len(rows) != len(keep):  # the two candidate builders must agree
            raise ValueError("candidate_rows and the candidate index disagree")
        return [keep[r.recipe_id] for r in model_order(rows, weights)]

    return orderer


def feature_map(pack: Pack, pantry: Sequence[str]) -> dict[str, tuple[float, ...]]:
    """Recipe id to its 8-feature vector, for every candidate of one pantry."""
    return {r.recipe_id: r.x for r in candidate_rows(pack, pantry, set(pack.default_staples))}


def _same(ids: dict[str, list[str]], a: str, b: str, neutral_order: bool) -> bool:
    return set(ids[a]) == set(ids[b]) if neutral_order else ids[a] == ids[b]


def select_pantries(
    index: CandidateIndex,
    group_of: dict[str, str],
    pool: Sequence[dict],
    arms: Sequence[str],
    orderers: Orderers,
    *,
    take: int | None = None,
    neutral_order: bool = True,
    gold_out: bool = True,
    skip_identical: bool = False,
) -> tuple[list[dict], list[str], list[dict]]:
    """Walk ``pool`` in order and keep ``take`` pantries (all when ``take`` is None).

    Return ``(base, skipped, skipped_pairs)``. A base record is the pool record plus ``tops`` (arm
    to top 5) and ``pairs`` (the arm pairs to show). With neutral order the sheet hides the order
    of a list, so two lists with the same 5 recipes look identical and the pair is not shown.
    With ``skip_identical`` (the test pool) such a pantry, or a pantry with a short list, is
    skipped whole and listed in ``skipped``. Otherwise the pair goes into ``skipped_pairs`` and
    a short list is an error. ``scripts/m4_rank.py score`` calls this to check the test key.
    """
    pairs = list(itertools.combinations(arms, 2))
    target = len(pool) if take is None else take
    base: list[dict] = []
    skipped: list[str] = []
    skipped_pairs: list[dict] = []
    for rec in pool:
        if len(base) == target:
            break
        gone = excluded_ids(group_of, rec["gold_id"], rec["title_group"]) if gold_out else set()
        tops = top_lists(index, arms, rec["pantry"], gone, orderers)
        short = any(len(t) < TOP for t in tops.values())
        ids = {a: [c.recipe_id for c in t] for a, t in tops.items()}

        twins = [(a, b) for a, b in pairs if _same(ids, a, b, neutral_order)]
        if skip_identical and (short or twins):
            skipped.append(rec["pantry_id"])
            continue
        if short:
            raise ValueError(f"{rec['pantry_id']}: fewer than {TOP} recipes in a list")
        skipped_pairs += [{"pantry_id": rec["pantry_id"], "pair": [a, b]} for a, b in twins]
        base.append(
            {**rec, "tops": tops, "pairs": [p for p in pairs if p not in twins], "probe": False}
        )
    if len(base) < target:
        raise ValueError(f"only {len(base)} usable pantries, need {target}")
    return base, skipped, skipped_pairs
