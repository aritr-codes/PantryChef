"""Bare "pepper" draw and score tool (M3 Task 6). Lines are invented."""

from __future__ import annotations

import csv

import pytest

from pantrychef.eval.parser_gold import line_hash
from pantrychef.eval.results import load_result
from pantrychef.ingredients.table import IngredientTable
from scripts.m3_bare_pepper import decide, draw, has_bare_pepper, read_labels, score, write_sheet

TABLE = IngredientTable.from_text(
    "id,name,synonyms,staple,provenance\n"
    "salt,salt,,1,hand\n"
    "black_pepper,black pepper,,1,hand\n"
    "chili_pepper,chili pepper,chile,0,hand\n"
    "egg,egg,,0,hand\n"
)


@pytest.mark.parametrize(
    ("text", "marked"),
    [
        ("1 tsp pepper", True),
        ("salt and pepper", True),
        ("2 eggs, pepper", True),
        ("1 green chile pepper", False),  # part of the chili pepper name
        ("1 tsp black pepper", False),
        ("2 eggs", False),
    ],
)
def test_has_bare_pepper(text, marked):
    assert has_bare_pepper(text, TABLE) is marked


def _lines(n):
    return [{"id": f"Page {k}#0", "text": f"{k} tsp pepper"} for k in range(n)]


def test_draw_skips_frozen_lines_in_any_case_and_is_deterministic():
    lines = _lines(10) + [{"id": "X#1", "text": "2 eggs"}]
    frozen = frozenset({line_hash("3 TSP PEPPER  ")})
    got = draw(lines, TABLE, frozen, n=5)
    assert got["pool"] == 9 and got["frozen"] == 1
    assert len(got["rows"]) == 5
    assert all(set(r) == {"id", "text"} for r in got["rows"])
    assert "3 tsp pepper" not in {r["text"] for r in got["rows"]}
    assert draw(lines, TABLE, frozen, n=5) == got
    assert [r["id"] for r in draw(lines, TABLE, frozen, n=9)["rows"]][:5] == [
        r["id"] for r in got["rows"]
    ]


def test_draw_takes_all_when_the_pool_is_small():
    got = draw(_lines(3), TABLE, frozenset(), n=80)
    assert got["pool"] == 3 and len(got["rows"]) == 3


def test_sheet_is_blind(tmp_path):
    p = tmp_path / "sheet.csv"
    write_sheet([{"id": "A#1", "text": "1 tsp pepper, ground"}], p)
    with open(p, encoding="utf8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows == [["id", "text", "label"], ["A#1", "1 tsp pepper, ground", ""]]


def _filled(tmp_path, labels):
    p = tmp_path / "filled.csv"
    with open(p, "w", encoding="utf8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "text", "label"])
        for k, lab in enumerate(labels):
            w.writerow([f"L{k}", f"{k} pepper", lab])
    return p


def test_read_labels_rejects_unknown_and_duplicate(tmp_path):
    with pytest.raises(ValueError, match="maybe"):
        read_labels(_filled(tmp_path, ["black", "maybe"]))
    p = tmp_path / "dup.csv"
    p.write_text("id,text,label\nA,x,black\nA,y,other\n", encoding="utf8")
    with pytest.raises(ValueError, match="twice"):
        read_labels(p)


def test_read_labels_accepts_case_and_spaces(tmp_path):
    assert read_labels(_filled(tmp_path, [" Black ", "OTHER", "unclear"])) == {
        "L0": "black",
        "L1": "other",
        "L2": "unclear",
    }


@pytest.mark.parametrize(
    ("black", "rest", "decision"),
    [
        (75, ["other"] * 5, "always"),
        (74, ["other"] * 6, "staple_cue_or_taste"),
        (74, ["unclear"] * 6, "staple_cue_or_taste"),  # unclear is not black
        (80, [], "always"),
    ],
)
def test_decision_rule(black, rest, decision):
    labels = {f"L{k}": lab for k, lab in enumerate(["black"] * black + rest)}
    out = decide(labels)
    assert out["decision"] == decision
    assert out["n"] == 80 and out["counts"]["black"] == black


def test_decision_scales_with_n():
    small = {f"L{k}": "black" for k in range(20)}  # 20 of 20: lower bound about 0.84
    assert decide(small)["decision"] == "staple_cue_or_taste"


def test_score_writes_a_valid_result(tmp_path):
    p = _filled(tmp_path, ["black"] * 76 + ["other"] * 3 + ["unclear"])
    out_path = tmp_path / "res.json"
    out = score(p, out_path)
    doc = load_result(out_path)
    (m,) = doc["metrics"]
    assert m["name"] == "bare_pepper_black_share" and m["n"] == 80
    assert m["value"] == pytest.approx(76 / 80)
    assert m["ci"]["lo"] == pytest.approx(out["ci"]["lo"]) and out["ci"]["lo"] >= 0.85
    assert doc["config"]["decision"] == "always"
    assert doc["config"]["counts"] == {"black": 76, "other": 3, "unclear": 1}
    assert doc["label"] == "MEASURED" and "one model" in doc["what"]
