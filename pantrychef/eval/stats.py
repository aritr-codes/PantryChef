"""Paired cluster bootstrap (M2). Standard library only, so it runs on Kaggle with --no-deps."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Interval:
    mean: float
    lo: float
    hi: float
    level: float
    n_clusters: int
    method: str = "cluster-bootstrap-percentile"


def paired_cluster_bootstrap(
    a: list[float],
    b: list[float],
    clusters: list[str],
    *,
    resamples: int = 10_000,
    level: float = 0.95,
    seed: int = 42,
) -> Interval:
    """Interval of mean(a_i - b_i), resampling whole clusters (gold recipes) with replacement.

    ``a``, ``b`` and ``clusters`` have the same length. The same seed gives the same interval.
    A constant difference gives lo == hi == mean.
    """
    raise NotImplementedError
