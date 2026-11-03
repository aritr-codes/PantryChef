"""Pure metric functions (M2). Every function has hand-computed unit tests.

``ranked`` is a list of recipe ids in order. ``k <= 0`` gives 0.0.
"""

from __future__ import annotations


def recall_at_k(ranked: list[str], gold: str, k: int) -> float:
    """1.0 if ``gold`` is in the first ``k`` ids, else 0.0."""
    raise NotImplementedError


def mrr_at_k(ranked: list[str], gold: str, k: int) -> float:
    """1/rank of ``gold`` when rank <= k, else 0.0."""
    raise NotImplementedError


def makeable_at_k(ranked_have_total: list[tuple[int, int]], k: int) -> float:
    """Share of the first ``min(k, len)`` entries with have == total. Empty gives 0.0.

    PRODUCT metric only.
    """
    raise NotImplementedError


def hit_rate(ranked_have_total: list[tuple[int, int]]) -> float:
    """1.0 if any entry has have == total, else 0.0. PRODUCT metric only."""
    raise NotImplementedError
