"""Paired cluster bootstrap (M2). Standard library only, so it runs on Kaggle with --no-deps."""

from __future__ import annotations

import random
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

    Each resample draws ``n_clusters`` clusters with replacement and takes the pooled mean of
    all pantry differences in the drawn clusters (a cluster with 3 pantries counts once as a
    unit and weighs 3 pantries). Percentile interval: sorted resample means at index
    ``int(alpha/2 * B)`` and ``min(B-1, int((1 - alpha/2) * B))``.
    """
    if not (len(a) == len(b) == len(clusters)):
        raise ValueError("a, b and clusters must have the same length")
    if resamples < 1:
        raise ValueError("resamples must be at least 1")
    if not a:
        raise ValueError("empty input")
    if not 0.0 < level < 1.0:
        raise ValueError("level must be in (0, 1)")
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for x, y, c in zip(a, b, clusters, strict=True):
        sums[c] = sums.get(c, 0.0) + (x - y)
        counts[c] = counts.get(c, 0) + 1
    keys = list(sums)  # first-appearance order: deterministic
    s = [sums[k] for k in keys]
    n = [counts[k] for k in keys]
    m = len(keys)
    mean = sum(s) / sum(n)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        picks = rng.choices(range(m), k=m)
        means.append(sum(s[i] for i in picks) / sum(n[i] for i in picks))
    means.sort()
    alpha = 1.0 - level
    lo = means[int(alpha / 2 * resamples)]
    hi = means[min(resamples - 1, int((1 - alpha / 2) * resamples))]
    return Interval(mean=mean, lo=lo, hi=hi, level=level, n_clusters=m)
