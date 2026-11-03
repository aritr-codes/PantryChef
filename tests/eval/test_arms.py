"""Tests for the ranking arms."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pantrychef.engine import (
    GROUPS,
    AnswerRequest,
    Ingredient,
    Line,
    Pack,
    PackInfo,
    Recipe,
    answer,
    load_pack,
)
from pantrychef.eval.arms import CandidateIndex, candidates, order, visible_ids

ROOT = Path(__file__).resolve().parents[2]


def _hand_pack() -> Pack:
    # idf: a=4, b=1, c=4, d=4. No staples.
    ings = {
        i: Ingredient(i, i, False, w) for i, w in (("a", 4.0), ("b", 1.0), ("c", 4.0), ("d", 4.0))
    }

    def rec(rid, *ids):
        return Recipe(rid, rid, rid, 1, tuple(Line(i, (i,), False, True) for i in ids))

    # pantry {a, b}:
    #   x = a,b,c,d  have 2 total 4 missing 2  score 5/sqrt(13)  = 1.38675
    #   y = b        have 1 total 1 missing 0  score 1/sqrt(1)   = 1.0
    #   z = a,c      have 1 total 2 missing 1  score 4/sqrt(8)   = 1.41421
    return Pack(
        PackInfo("t", "t", "fp"),
        ings,
        {},
        (rec("x", "a", "b", "c", "d"), rec("y", "b"), rec("z", "a", "c")),
    )


def test_candidates_hand_values():
    cs = {c.recipe_id: c for c in candidates(_hand_pack(), {"a", "b"}, set())}
    assert (cs["x"].have, cs["x"].total) == (2, 4)
    assert cs["x"].score == pytest.approx(5 / 13**0.5)
    assert (cs["y"].have, cs["y"].total, cs["y"].score) == (1, 1, 1.0)
    assert cs["z"].score == pytest.approx(4 / 8**0.5)
    # pantry {d}: only x has d
    assert [c.recipe_id for c in candidates(_hand_pack(), {"d"}, set())] == ["x"]
    # a staple in the pantry is ignored
    assert candidates(_hand_pack(), {"a"}, {"a"}) == []


def test_arms_differ_on_hand_example():
    cands = candidates(_hand_pack(), {"a", "b"}, set())
    ids = lambda arm: [c.recipe_id for c in order(arm, cands, "k")]  # noqa: E731
    # overlap: -have then total: x (have 2), y (1, total 1), z (1, total 2)
    assert ids("overlap") == ["x", "y", "z"]
    # idf_flat: -score: z 1.414, x 1.387, y 1.0
    assert ids("idf_flat") == ["z", "x", "y"]
    # shipped: missing then -score: y (0), z (1), x (2)
    assert ids("shipped") == ["y", "z", "x"]
    r = ids("random")
    assert sorted(r) == ["x", "y", "z"]
    assert r == ids("random")  # same seed_key is stable
    # some other key gives a different permutation
    assert any([c.recipe_id for c in order("random", cands, str(s))] != r for s in range(20))


def test_unknown_arm_raises():
    with pytest.raises(ValueError):
        order("magic", [])


def test_shipped_order_matches_answer_order_on_golden_cases():
    """For each golden pantry, ``shipped`` restricted to the ids ``answer()`` returned has the
    same relative order as answer()'s flattened groups.

    This proves the order key matches the product. It does NOT prove the candidate sets match:
    ``answer()`` drops recipes with more than 2 missing lines, ``candidates`` keeps them.
    """
    pack = load_pack(ROOT / "tests" / "fixtures" / "pack", "v1")
    cases = json.loads((ROOT / "tests" / "golden" / "answer_cases.json").read_text("utf8"))["cases"]
    assert len(cases) >= 200
    checked = 0
    for case in cases:
        req = dict(case["request"])
        req["limit"] = 10**6
        ans = answer(pack, AnswerRequest(**req))
        expected = [it.recipe_id for g in GROUPS for it in ans.groups[g].items]
        staples = set(req["staples"])
        cands = candidates(pack, set(req["pantry"]), staples)
        ranked = [c.recipe_id for c in order("shipped", cands)]
        keep = set(expected)
        assert [i for i in ranked if i in keep] == expected, case["name"]
        assert keep <= set(ranked)
        checked += len(expected)
    assert checked > 0


def test_candidate_index_equals_reference_and_visible_ids_equals_answer():
    """The index returns the same Scored list as ``candidates`` (same floats), and
    ``visible_ids`` returns the ids that ``answer()`` shows with its default limit."""
    pack = load_pack(ROOT / "tests" / "fixtures" / "pack", "v1")
    cases = json.loads((ROOT / "tests" / "golden" / "answer_cases.json").read_text("utf8"))["cases"]
    indexes: dict[tuple, CandidateIndex] = {}
    for case in cases:
        req = case["request"]
        staples = set(req["staples"])
        idx = indexes.setdefault(tuple(sorted(staples)), CandidateIndex(pack, staples))
        pantry = set(req["pantry"])
        ref = candidates(pack, pantry, staples)
        assert idx.candidates(pantry) == ref, case["name"]
        ans = answer(pack, AnswerRequest(pantry=list(pantry), staples=sorted(staples)))
        shown = {it.recipe_id for g in GROUPS for it in ans.groups[g].items}
        assert visible_ids(ref) == shown, case["name"]
