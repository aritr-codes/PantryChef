"""The local judging page: deterministic, blind, escaped, and the CSV header matches the scorer."""

import json
import re
from pathlib import Path

import pytest

from scripts.judging_page import COLUMNS, RUBRIC, build_page
from scripts.judging_sheet import TEMPLATE_COLUMNS

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = ["overlap", "shipped", "idf_flat", "rank_linear", "model", "gold", "pantry_id"]
NASTY = "A <b>&\"' </script><script>alert(1)</script>  "


def _sheet(title: str = NASTY) -> dict:
    item = {
        "item_id": "item01",
        "pantry": ["egg", title],
        "left": [{"title": title, "missing": ["1 cup <i>milk</i>"]}]
        + [{"title": f"L{i}", "missing": []} for i in range(4)],
        "right": [{"title": f"R{i}", "missing": []} for i in range(5)],
        "pantry_id": "secret",  # must be dropped
        "left_arm": "overlap",
    }
    return {"version": 1, "items": [item, {**item, "item_id": "item02"}]}


def _data(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="sheet">(.*?)</script>', html, re.S)
    assert m
    return json.loads(m.group(1))


def test_deterministic():
    assert build_page(_sheet(), 1, "pilot") == build_page(_sheet(), 1, "pilot")


def test_header_equals_template_columns():
    assert COLUMNS == TEMPLATE_COLUMNS
    assert _data(build_page(_sheet(), 1, "pilot"))["columns"] == TEMPLATE_COLUMNS


def test_no_forbidden_strings_and_no_network():
    html = build_page(_sheet("Plain"), 1, "pilot")
    low = html.lower()
    for word in FORBIDDEN:
        assert word not in low, word
    for bad in ("http://", "https://", "src=", "@import", "<link"):
        assert bad not in low, bad
    assert not re.search(r"(?<![a-z])url\(", low)


def test_embedded_sheet_round_trips_and_extra_keys_dropped():
    sheet = _sheet()
    d = _data(build_page(sheet, 3, "pilot"))
    assert d["session"] == 3 and d["name"] == "pilot"
    assert [i["item_id"] for i in d["items"]] == ["item01", "item02"]
    assert d["items"][0]["left"] == sheet["items"][0]["left"]
    assert d["items"][0]["pantry"] == sheet["items"][0]["pantry"]
    assert set(d["items"][0]) == {"item_id", "pantry", "left", "right"}


def test_script_escaped():
    html = build_page(_sheet(), 1, "pilot")
    assert html.count("</script>") == 2  # the data block and the code block only
    assert "<script>alert" not in html
    assert " " not in html


def test_arm_guess_only_for_test_sheet():
    plain = build_page(_sheet("x"), 1, "dev")
    test = build_page(_sheet("x"), 1, "test", arm_guess=True)
    assert _data(plain)["arm_guess"] is False and _data(test)["arm_guess"] is True
    assert _data(test)["columns"] == TEMPLATE_COLUMNS + ["arm_guess"]
    assert _data(plain)["columns"] == TEMPLATE_COLUMNS
    assert "new model" in " ".join(_data(test)["rubric"])
    assert "new model" not in " ".join(_data(plain)["rubric"])


def test_rubric_is_verbatim_from_protocol():
    text = (ROOT / "docs/JUDGING_PROTOCOL.md").read_text(encoding="utf-8")
    m4 = text.split("### Rubric (approved", 1)[1].split("### Answer file", 1)[0]
    quoted = [ln[2:] for ln in m4.splitlines() if ln.startswith("> ")]
    assert quoted == RUBRIC


def test_real_pilot_sheet_is_blind():
    path = ROOT / "data/eval/m4/sheet.pilot.v1.json"
    if not path.exists():
        pytest.skip("no pilot sheet")
    sheet = json.loads(path.read_text(encoding="utf-8"))
    d = _data(build_page(sheet, 1, "pilot"))
    assert len(d["items"]) == len(sheet["items"])
    html = build_page(sheet, 1, "pilot").lower()
    assert not [w for w in FORBIDDEN if w in html]
