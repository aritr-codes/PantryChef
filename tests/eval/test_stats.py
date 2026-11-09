"""Hand-computed tests for paired_cluster_bootstrap."""

from __future__ import annotations

import pytest

from pantrychef.eval.stats import paired_cluster_bootstrap


def test_constant_difference_has_zero_width():
    iv = paired_cluster_bootstrap([0.75] * 4, [0.5] * 4, ["a", "b", "c", "d"], resamples=200)
    assert iv.mean == iv.lo == iv.hi == 0.25
    assert iv.n_clusters == 4


def test_two_cluster_hand_case():
    # d = [1, 0] in clusters x, y. Pooled mean 0.5.
    # A resample draws 2 clusters: xx (mean 1) p=.25, xy/yx (mean .5) p=.5, yy (mean 0) p=.25.
    # With 10000 resamples the lowest ~2500 are 0 and the highest ~2500 are 1, so the
    # 2.5% and 97.5% order statistics (indices 250 and 9750) are 0.0 and 1.0.
    iv = paired_cluster_bootstrap([1.0, 0.0], [0.0, 0.0], ["x", "y"], resamples=10_000)
    assert iv.mean == 0.5
    assert iv.lo == 0.0
    assert iv.hi == 1.0
    assert iv.level == 0.95


def test_same_seed_same_interval_and_other_seed_may_differ():
    a = [0.9, 0.1, 0.4, 0.8, 0.3, 0.6]
    b = [0.2, 0.3, 0.1, 0.5, 0.9, 0.0]
    c = ["a", "a", "b", "b", "c", "c"]
    assert paired_cluster_bootstrap(a, b, c, resamples=500, seed=7) == paired_cluster_bootstrap(
        a, b, c, resamples=500, seed=7
    )


def test_clusters_resample_as_whole_units():
    # Cluster "big" has 3 pantries with d = 1 each; "s1","s2" have 1 pantry with d = 0.
    # n_clusters is 3 (not 5), the pooled mean is 3/5.
    iv = paired_cluster_bootstrap(
        [1.0, 1.0, 1.0, 0.0, 0.0],
        [0.0] * 5,
        ["big", "big", "big", "s1", "s2"],
        resamples=10,
    )
    assert iv.n_clusters == 3
    assert iv.mean == pytest.approx(0.6)
    # Whole-cluster resampling: a resample of only "s" clusters has mean 0, only "big" has mean 1.
    # Pantry-level resampling could never give exactly these when drawing 3 units from 5 pantries
    # with the big cluster split, so check the extremes are reachable at the cluster level.
    wide = paired_cluster_bootstrap(
        [1.0, 1.0, 1.0, 0.0, 0.0], [0.0] * 5, ["big", "big", "big", "s1", "s2"], resamples=5000
    )
    assert wide.lo == 0.0 and wide.hi == 1.0


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        paired_cluster_bootstrap([1.0], [1.0, 2.0], ["a"])
    with pytest.raises(ValueError):
        paired_cluster_bootstrap([1.0], [1.0], ["a", "b"])


def test_resamples_below_one_raise():
    with pytest.raises(ValueError):
        paired_cluster_bootstrap([1.0], [0.0], ["a"], resamples=0)


def test_wilson_75_of_80():
    from pantrychef.eval.stats import wilson

    lo, hi = wilson(75, 80)
    assert lo == pytest.approx(0.86, abs=0.01)
    assert lo < 75 / 80 < hi <= 1.0
    assert wilson(0, 0) == (0.0, 1.0)


def test_mcnemar_exact_symmetric():
    from pantrychef.eval.stats import mcnemar_exact

    assert mcnemar_exact(3, 9) == mcnemar_exact(9, 3)
    # n = 12, P(X <= 3) = (1 + 12 + 66 + 220) / 4096, two-sided doubles it
    assert mcnemar_exact(3, 9) == pytest.approx(2 * 299 / 4096)
    assert mcnemar_exact(5, 5) == 1.0
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(0, 10) == pytest.approx(2 / 1024)
