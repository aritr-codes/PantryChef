"""Pure metric functions (M2). Every function has hand-computed unit tests.

``ranked`` is a list of recipe ids in order. ``k <= 0`` gives 0.0.
"""

from __future__ import annotations


def recall_at_k(ranked: list[str], gold: str, k: int) -> float:
    """1.0 if ``gold`` is in the first ``k`` ids, else 0.0."""
    return 1.0 if k > 0 and gold in ranked[:k] else 0.0


def mrr_at_k(ranked: list[str], gold: str, k: int) -> float:
    """1/rank of ``gold`` when rank <= k, else 0.0. A repeated id counts at its first rank."""
    if k <= 0 or gold not in ranked[:k]:
        return 0.0
    return 1.0 / (ranked.index(gold) + 1)


def makeable_at_k(ranked_have_total: list[tuple[int, int]], k: int) -> float:
    """Share of the first ``min(k, len)`` entries with have == total. Empty gives 0.0.

    PRODUCT metric only.
    """
    top = ranked_have_total[: max(k, 0)]
    return sum(h == t for h, t in top) / len(top) if top else 0.0


def hit_rate(ranked_have_total: list[tuple[int, int]]) -> float:
    """1.0 if any entry has have == total, else 0.0. PRODUCT metric only."""
    return 1.0 if any(h == t for h, t in ranked_have_total) else 0.0
