"""Paired cluster bootstrap (M2). Uses numpy, which pandas already requires and Kaggle provides."""

from __future__ import annotations

from dataclasses import dataclass
from math import comb, sqrt

import numpy as np


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
    rng = np.random.default_rng(seed)
    s_arr, n_arr = np.array(s, dtype=float), np.array(n, dtype=float)
    means = np.empty(resamples)
    chunk = max(1, 1_000_000 // m)  # keeps the index matrix small
    for start in range(0, resamples, chunk):
        stop = min(resamples, start + chunk)
        idx = rng.integers(0, m, size=(stop - start, m))
        means[start:stop] = s_arr[idx].sum(axis=1) / n_arr[idx].sum(axis=1)
    means.sort()
    alpha = 1.0 - level
    lo = float(means[int(alpha / 2 * resamples)])
    hi = float(means[min(resamples - 1, int((1 - alpha / 2) * resamples))])
    return Interval(mean=mean, lo=lo, hi=hi, level=level, n_clusters=m)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for ``k`` successes in ``n`` trials (95% by default)."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    centre = p + z * z / (2 * n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    denom = 1 + z * z / n
    return max(0.0, (centre - half) / denom), min(1.0, (centre + half) / denom)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts ``b`` and ``c``."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)
