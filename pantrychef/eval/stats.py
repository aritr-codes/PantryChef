"""Paired cluster bootstrap (M2). Uses numpy, which pandas already requires and Kaggle provides."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from math import ceil, comb, erfc, sqrt

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
    if n <= 0 or not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n and n > 0, got k={k}, n={n}")
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


# ---- Exact binomial tools (M4, plan section 6). Pure Python: math.comb and bisection. ----


def _tail_ge(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(max(k, 0), n + 1))


def _bisect(f, lo: float, hi: float) -> float:
    """Root of an increasing ``f`` on [lo, hi] with f(lo) < 0 < f(hi) (60 halvings)."""
    for _ in range(60):
        mid = (lo + hi) / 2
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def clopper_pearson(k: int, n: int, level: float = 0.95) -> tuple[float, float]:
    """Exact two-sided Clopper-Pearson interval for ``k`` successes in ``n`` trials.

    Lower bound: the p where P(X >= k) = alpha/2. Upper bound: the p where P(X <= k) = alpha/2.
    ``k = 0`` gives a lower bound of 0. ``k = n`` gives an upper bound of 1.
    """
    if n <= 0 or not 0 <= k <= n or not 0.0 < level < 1.0:
        raise ValueError(f"need 0 <= k <= n, n > 0 and 0 < level < 1, got k={k}, n={n}")
    a = (1.0 - level) / 2
    lo = 0.0 if k == 0 else _bisect(lambda p: _tail_ge(k, n, p) - a, 0.0, 1.0)
    hi = 1.0 if k == n else _bisect(lambda p: a - (1 - _tail_ge(k + 1, n, p)), 0.0, 1.0)
    return lo, hi


def sign_test(k: int, n: int) -> float:
    """Two-sided exact sign-test p-value for ``k`` wins in ``n`` decided items (p = 0.5)."""
    if n < 0 or not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n, got k={k}, n={n}")
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(k, n - k) + 1)) / 2**n)


@cache
def wins_needed(decided: int, alpha: float = 0.025) -> int | None:
    """Fewest wins among ``decided`` items with one-sided exact p <= ``alpha`` at p = 0.5.

    This equals "the 95% CP lower bound is above 0.5". ``None`` when no win count reaches it.
    """
    for k in range(decided + 1):
        if _tail_ge(k, decided, 0.5) <= alpha:
            return k
    return None


def power_at(n: int, tie_rate: float, p_true: float) -> float:
    """Power of the one-sided exact test at true win rate ``p_true`` (ESTIMATE).

    The number of decided items is random: Binomial(``n``, 1 - ``tie_rate``).
    """
    total = 0.0
    for d in range(1, n + 1):
        w = wins_needed(d)
        if w is None:
            continue
        pd = comb(n, d) * (1 - tie_rate) ** d * tie_rate ** (n - d)
        total += pd * _tail_ge(w, d, p_true)
    return total


def min_detectable_rate(n: int, tie_rate: float, power: float = 0.8) -> float | None:
    """Smallest true win rate with ``power``, rounded up to the next 0.005. ``None`` if > 1."""
    if power_at(n, tie_rate, 1.0) < power:
        return None
    p = _bisect(lambda q: power_at(n, tie_rate, q) - power, 0.5, 1.0)
    return min(1.0, ceil(p * 200 - 1e-9) / 200)


def wilcoxon_signed_rank(scores: list[float]) -> float:
    """Two-sided Wilcoxon signed-rank p-value (normal approximation, ESTIMATE).

    Zeros drop out. Tied ranks are averaged and the variance has the tie correction.
    A continuity correction of 0.5 applies. Returns 1.0 when no non-zero score is left.
    """
    d = [x for x in scores if x != 0]
    n = len(d)
    if n == 0:
        return 1.0
    ordered = sorted(range(n), key=lambda i: abs(d[i]))
    rank = [0.0] * n
    tie_term, i = 0.0, 0
    while i < n:
        j = i
        while j + 1 < n and abs(d[ordered[j + 1]]) == abs(d[ordered[i]]):
            j += 1
        for k in range(i, j + 1):
            rank[ordered[k]] = (i + j) / 2 + 1
        t = j - i + 1
        tie_term += t**3 - t
        i = j + 1
    w_plus = sum(r for r, x in zip(rank, d, strict=True) if x > 0)
    mean = n * (n + 1) / 4
    var = n * (n + 1) * (2 * n + 1) / 24 - tie_term / 48
    if var <= 0:
        return 1.0
    z = max(0.0, abs(w_plus - mean) - 0.5) / sqrt(var)
    return erfc(z / sqrt(2))
