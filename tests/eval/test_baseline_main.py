"""Tests for the baseline runner. Needs pantrychef.eval.metrics (lane A)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pantrychef.eval.baseline_main import group_label, main, run

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pack"


def _tiny_pack(tmp_path: Path) -> Path:
    def line(*ids):
        return {"t": "/".join(ids), "o": list(ids), "opt": False, "r": True}

    core = {
        "info": {"version": "t", "commit": "t", "corpus_fingerprint": "tiny-fp"},
        "ingredients": [
            {"id": i, "name": i, "staple": False, "idf": 1.0}
            for i in ("a", "b", "c", "d", "x", "y")
        ],
        "keys": {},
        "recipes": [
            {
                "id": "g1",
                "title": "Gold One",
                "page": "p1",
                "rev": 1,
                "lines": [line("a"), line("b"), line("c"), line("d")],
            },
            {
                "id": "h1",
                "title": "Other Two",
                "page": "p2",
                "rev": 1,
                "lines": [line("a"), line("x"), line("y")],
            },
        ],
    }
    (tmp_path / "core.v2.json").write_text(json.dumps(core), encoding="utf8")
    return tmp_path


def test_hand_case_on_tiny_pack(tmp_path):
    # g1 total 4 (m = 1): pantry = 3 of {a,b,c,d}. h1 total 3 (m = 1): pantry = 2 of {a,x,y}.
    # With d = 0 every pantry has at most 2 recipes as candidates. The gold has the larger
    # have (3 vs <= 1 for g1; 2 vs <= 1 for h1), so overlap ranks it first: MRR 1.0, recall 1.0.
    # Nobody has have == total, so makeable and hit_rate are 0. Two groups: 1 dev, 1 test,
    # 3 draws each, so n = 3.
    out = run(_tiny_pack(tmp_path), d_values=[0], resamples=100)
    got = {(m["split"], m["arm"], m["name"]): m for m in out["metrics"]}
    for split in ("dev", "test"):
        for name, v in (
            ("recall_at_10", 1.0),
            ("mrr_at_10", 1.0),
            ("makeable_at_10", 0.0),
        ):
            m = got[(split, "overlap", name)]
            assert m["value"] == v and m["n"] == 3
            assert m["group"] == {"sampler": "none", "d": 0}
        assert got[(split, None, "hit_rate")]["value"] == 0.0
        assert got[(split, None, "visible_rate")]["value"] == 1.0
    assert out["corpus_fingerprint"] == "tiny-fp"
    assert {c["metric"] for c in out["comparisons"]} == {"mrr_at_10", "recall_at_10"}
    assert all(c["ci"]["n_clusters"] == 1 and c["n"] == 3 for c in out["comparisons"])


def test_run_structure_on_fixture_pack():
    out = run(FIXTURE, d_values=[0, 3], resamples=100)
    groups = {group_label(m["group"]) for m in out["metrics"]}
    # d = 0 appears once (sampler "none"); d = 3 appears for each sampler
    assert groups == {"sampler=none,d=0", "sampler=uniform,d=3", "sampler=popularity,d=3"}
    # 3 groups x 2 splits x (4 arms x 3 metrics + hit_rate + visible_rate)
    assert len(out["metrics"]) == 3 * 2 * 14
    # 3 groups x 2 splits x 4 pairs x 2 metrics
    assert len(out["comparisons"]) == 3 * 2 * 4 * 2
    assert all(m["n"] > 0 and 0.0 <= m["value"] <= 1.0 for m in out["metrics"])
    assert out == run(FIXTURE, d_values=[0, 3], resamples=100)  # deterministic


def test_main_writes_result_when_lane_a_is_merged(tmp_path):
    results = pytest.importorskip("pantrychef.eval.results")
    dest = tmp_path / "r.json"
    try:
        main(["--pack", str(FIXTURE), "--out", str(dest)])
    except NotImplementedError:
        pytest.skip("results.write_result is still a stub")
    assert results.load_result(dest)["corpus_fingerprint"] == "fixture"
