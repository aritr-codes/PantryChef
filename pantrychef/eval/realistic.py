"""Realistic pantry-input scoring (M3).

An input is correct when every gold group has a predicted id in it and every predicted id is in
some gold group. An input with no predicted id (unknown) is wrong.
"""

from __future__ import annotations

from collections.abc import Callable

from pantrychef.eval.parser_gold import Label, to_ids
from pantrychef.ingredients.table import IngredientTable


def score_inputs(
    inputs: list[str],
    labels: dict[str, Label],
    resolve: Callable[[str], list[str]],
    table: IngredientTable,
    id_map: dict[str, str | None] | None = None,
) -> dict[str, float | int]:
    """Return ``{"n", "correct", "input_accuracy"}``. ``labels`` is keyed by input text."""
    correct = 0
    for text in inputs:
        pred = set(resolve(text))
        gold = [to_ids(g, table, id_map)[0] for g in labels[text].groups]
        correct += bool(
            pred
            and gold
            and all(g & pred for g in gold)
            and all(any(i in g for g in gold) for i in pred)
        )
    n = len(inputs)
    return {"n": n, "correct": correct, "input_accuracy": correct / n if n else 0.0}
