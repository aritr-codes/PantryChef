"""Realistic-input scoring with invented inputs and a tiny table."""

from __future__ import annotations

from pantrychef.eval.parser_gold import Label
from pantrychef.eval.realistic import score_inputs
from pantrychef.ingredients.table import IngredientTable

TABLE = IngredientTable.from_text(
    "id,name,synonyms,staple,provenance\n"
    "salt,salt,,1,hand\n"
    "black_pepper,black pepper,,0,hand\n"
    "sugar,sugar,,0,hand\n"
)
GOLD = {"salt and pepper": Label((("salt",), ("black pepper",)), False, False)}


def _acc(ids: list[str], id_map=None) -> dict:
    return score_inputs(["salt and pepper"], GOLD, lambda _t: ids, TABLE, id_map)


def test_input_accuracy_needs_all_groups() -> None:
    assert _acc(["salt"])["input_accuracy"] == 0.0  # misses a group
    assert _acc(["salt", "black_pepper"]) == {"n": 1, "correct": 1, "input_accuracy": 1.0}
    assert _acc(["salt", "black_pepper", "sugar"])["input_accuracy"] == 0.0  # extra id
    assert _acc([])["input_accuracy"] == 0.0  # unknown input


def test_input_accuracy_alternatives_and_id_map() -> None:
    gold = {"x": Label((("pepper", "black pepper"),), False, False)}
    got = score_inputs(["x"], gold, lambda _t: ["black_pepper"], TABLE)
    assert got["input_accuracy"] == 1.0
    got = score_inputs(["x"], gold, lambda _t: ["sugar"], TABLE, {"pepper": "sugar"})
    assert got["input_accuracy"] == 1.0  # the map replaces the table lookup
    got = score_inputs([], {}, lambda _t: [], TABLE)
    assert got == {"n": 0, "correct": 0, "input_accuracy": 0.0}
