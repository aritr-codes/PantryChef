"""Features and ordering of ``pantrychef.rank``. Expected values are computed by hand.

Hand pack: idf a=1, b=2, c=0.5, d=1.5; staple s. Pantry {a}.

- R1: lines a, b, c, optional d, staple s.   needed = a, b, c.  total 3, have 1.
      M = 1, T = 3.5, score = 1/sqrt(3.5), missing 2 (b, c), miss_frac = 2.5/3.5,
      unread 0, total_c 3, short 0, optional_c 1, mean_w = 3.5/3.
- R2: lines a and one unread line (no options, weight 0).  total 2, have 1.
      M = 1, T = 1, score = 1, missing 1, miss_frac 0, unread 1, total_c 2, short 1,
      optional_c 0, mean_w = 1/2.
- R5: line a.  total 1, have 1.  M = 1, T = 1, score 1, missing 0, miss_frac 0, unread 0,
      total_c 1, short 1, optional_c 0, mean_w 1.
- R7: same as R5 (a tie on every feature; only the id differs).
- R3: line b only: have 0, not a candidate.
- R4: lines a, b, c, d (all required): missing 3, not a candidate.
- R0: only a staple line: total 0, never appears.
"""

from __future__ import annotations

import json
import math

import pytest

from pantrychef.eval.arms import candidates, order
from pantrychef.rank import FEATURES, candidate_rows, load_model, model_order
from tests.test_engine import L, make_pack

IDF = {"a": 1.0, "b": 2.0, "c": 0.5, "d": 1.5}


def hand_pack():
    return make_pack(
        {
            "R1": [L("a"), L("b"), L("c"), L("d", optional=True), L("s")],
            "R2": [L("a"), L(read=False)],
            "R5": [L("a")],
            "R7": [L("a")],
            "R3": [L("b")],
            "R4": [L("a"), L("b"), L("c"), L("d")],
            "R0": [L("s")],
        },
        IDF,
    )


def rows_by_id(rows):
    return {r.recipe_id: r for r in rows}


def test_feature_names_and_count():
    assert FEATURES == (
        "score",
        "missing",
        "miss_frac",
        "unread_missing",
        "total_c",
        "short",
        "optional_c",
        "mean_w",
    )
    assert len(FEATURES) <= 8


def test_candidate_set_and_hand_features():
    rows = rows_by_id(candidate_rows(hand_pack(), {"a"}, {"s"}))
    assert set(rows) == {"r-R1", "r-R2", "r-R5", "r-R7"}
    assert rows["r-R1"].x == (
        1.0 / math.sqrt(3.5),
        2.0,
        2.5 / 3.5,
        0.0,
        3.0,
        0.0,
        1.0,
        3.5 / 3,
    )
    assert rows["r-R2"].x == (1.0, 1.0, 0.0, 1.0, 2.0, 1.0, 0.0, 0.5)
    assert rows["r-R5"].x == (1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 1.0)
    assert (rows["r-R1"].have, rows["r-R1"].total) == (1, 3)


def test_total_c_caps_at_12_and_optional_c_at_3():
    pack = make_pack(
        {"Big": [L("a"), L("a")] * 7, "Opt": [L("a")] + [L("d", optional=True)] * 5}, IDF
    )
    rows = rows_by_id(candidate_rows(pack, {"a"}, {"s"}))
    assert rows["r-Big"].x[4] == 12.0  # total 14 -> min(14, 12)
    assert rows["r-Opt"].x[6] == 3.0  # 5 optional lines -> min(5, 3)


def test_staple_pantry_item_is_ignored():
    rows = rows_by_id(candidate_rows(hand_pack(), {"a", "s"}, {"s"}))
    assert set(rows) == {"r-R1", "r-R2", "r-R5", "r-R7"}


def test_order_score_only_then_total_then_id():
    rows = candidate_rows(hand_pack(), {"a"}, {"s"})
    w = [1.0] + [0.0] * 7
    # score: R2 = R5 = R7 = 1.0 > R1 = 0.5345. Ties: total 1 (R5, R7 by id) before total 2 (R2).
    assert [r.recipe_id for r in model_order(rows, w)] == ["r-R5", "r-R7", "r-R2", "r-R1"]


def test_all_zero_weights_fall_to_total_then_id():
    rows = candidate_rows(hand_pack(), {"a"}, {"s"})
    assert [r.recipe_id for r in model_order(rows, [0.0] * 8)] == [
        "r-R5",
        "r-R7",
        "r-R2",
        "r-R1",
    ]


def test_total_c_weight_reverses_the_length_tie_break():
    rows = candidate_rows(hand_pack(), {"a"}, {"s"})
    w = [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    # f = total_c: R1 = 3, R2 = 2, R5 = R7 = 1; R5 before R7 by id.
    assert [r.recipe_id for r in model_order(rows, w)] == ["r-R1", "r-R2", "r-R5", "r-R7"]


def test_order_is_independent_of_input_order():
    rows = candidate_rows(hand_pack(), {"a"}, {"s"})
    w = [0.3, -0.2, 0.1, -0.5, 0.05, 0.4, 0.1, -0.3]
    assert model_order(rows, w) == model_order(list(reversed(rows)), w)


def test_wrong_weight_length_fails():
    with pytest.raises(ValueError):
        model_order(candidate_rows(hand_pack(), {"a"}, {"s"}), [1.0])


def test_score_only_weights_reproduce_idf_flat_on_the_fixture_pack():
    from pathlib import Path

    from pantrychef.engine import load_pack

    pack = load_pack(Path(__file__).resolve().parents[1] / "fixtures" / "pack")
    staples = set(pack.default_staples)
    ids = sorted(pack.ingredients)
    pantries = [set(ids[i : i + 6]) for i in range(0, len(ids) - 5, 3)]
    assert pantries
    checked = 0
    for pantry in pantries:
        flat = [c.recipe_id for c in order("idf_flat", candidates(pack, pantry, staples))]
        cands = {c.recipe_id: c for c in candidates(pack, pantry, staples)}
        expected = [i for i in flat if cands[i].total - cands[i].have <= 2]
        got = [
            r.recipe_id
            for r in model_order(candidate_rows(pack, pantry, staples), [1.0] + [0.0] * 7)
        ]
        assert got == expected
        checked += bool(got)
    assert checked > 0


def test_score_only_weights_reproduce_idf_flat_on_hand_pack():
    pack = hand_pack()
    cands = candidates(pack, {"a"}, {"s"})
    expected = [c.recipe_id for c in order("idf_flat", cands) if c.total - c.have <= 2]
    got = [r.recipe_id for r in model_order(candidate_rows(pack, {"a"}, {"s"}), [1.0] + [0.0] * 7)]
    assert got == expected


def test_load_model_checks_feature_names(tmp_path):
    good = {"version": 1, "features": list(FEATURES), "weights": [0.5] * 8}
    p = tmp_path / "m.json"
    p.write_text(json.dumps(good), encoding="utf8")
    assert load_model(p) == (0.5,) * 8
    p.write_text(json.dumps({**good, "features": ["score"]}), encoding="utf8")
    with pytest.raises(ValueError):
        load_model(p)
