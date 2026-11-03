"""Quantity and unit parsing on real Wikibooks lines (CC BY-SA, see fixtures NOTICE.md)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pantrychef.ingredients.units import parse_quantity, parse_unit

LINES = json.loads(
    (Path(__file__).parent / "fixtures" / "wikibooks" / "lines.json").read_text(encoding="utf8")
)


@pytest.mark.parametrize("case", LINES, ids=[c["line"][:30] for c in LINES])
def test_real_line_quantity_and_unit(case):
    qty, rest = parse_quantity(case["line"])
    unit, _ = parse_unit(rest)
    if case["quantity"] is None:
        assert qty is None
    else:
        assert qty == pytest.approx(case["quantity"], abs=1e-4)
    assert unit == case["unit"]
