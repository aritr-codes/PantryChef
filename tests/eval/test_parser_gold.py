"""Parser gold set: label checks and hand-computed scores."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pantrychef.eval.parser_gold import (
    Label,
    LabelError,
    parse_names,
    read_labels_csv,
    score,
)
from pantrychef.ingredients.table import IngredientTable

ROOT = Path(__file__).resolve().parents[2]

TABLE = IngredientTable.from_text(
    "id,name,synonyms,staple,provenance\n"
    "egg,egg,eggs,0,hand\n"
    "flour,flour,,0,hand\n"
    "butter,butter,,0,hand\n"
    "salt,salt,,1,hand\n"
)


def test_parse_names() -> None:
    assert parse_names("bulgur|cracked wheat") == (("bulgur", "cracked wheat"),)
    assert parse_names("salt; pepper ") == (("salt",), ("pepper",))
    assert parse_names("") == ()


def _csv(tmp_path: Path, rows: list[tuple[str, str, str, str]]) -> Path:
    p = tmp_path / "labels.csv"
    lines = ["id,text,names,optional,not_an_ingredient"]
    lines += [f"{i},x,{n},{o},{s}" for i, n, o, s in rows]
    p.write_text("\n".join(lines) + "\n", encoding="utf8")
    return p


def test_read_labels_ok(tmp_path: Path) -> None:
    p = _csv(tmp_path, [("a", "egg", "", ""), ("b", "", "", "1"), ("c", "salt;flour", "1", "")])
    got = read_labels_csv(p, ["a", "b", "c"])
    assert got["a"] == Label((("egg",),), False, False)
    assert got["b"].not_an_ingredient
    assert got["c"] == Label((("salt",), ("flour",)), True, False)


@pytest.mark.parametrize(
    "rows,ids",
    [
        ([("a", "", "", "")], ["a"]),  # blank
        ([("a", "egg", "", "1")], ["a"]),  # names and not_an_ingredient
        ([("a", "egg", "2", "")], ["a"]),  # bad optional
        ([("a", "egg", "", "")], ["a", "b"]),  # missing line
        ([("z", "egg", "", "")], ["a"]),  # unknown id
        ([("a", "egg", "", ""), ("a", "egg", "", "")], ["a"]),  # duplicate
    ],
)
def test_read_labels_rejects(tmp_path: Path, rows, ids) -> None:
    with pytest.raises(LabelError):
        read_labels_csv(_csv(tmp_path, rows), ids)


def test_score_hand_computed() -> None:
    lines = [
        {"id": "1", "text": "2 eggs"},  # read: egg. gold egg. pred ok, gold found
        {"id": "2", "text": "1 cup flour or butter"},  # read {flour,butter}. gold same group
        {"id": "3", "text": "3 kumquats"},  # unread. gold kumquat is out of table
        {"id": "4", "text": "flour, butter"},  # two groups. gold flour only. 1 pred wrong
    ]
    labels = {
        "1": Label((("egg",),), False, False),
        "2": Label((("flour", "butter"),), False, False),
        "3": Label((("kumquat",),), False, False),
        "4": Label((("flour",),), False, False),
    }
    got = score(lines, labels, TABLE)
    # predicted groups: line1 1, line2 1, line3 0, line4 2 -> 4
    # correct: egg yes, {flour,butter} subset of gold group yes, flour yes, butter no -> 3
    # gold groups: 1 + 1 + 1 + 1 = 4; found: egg, flour/butter, (kumquat no), flour -> 3
    assert (got["pred_groups"], got["pred_correct"]) == (4, 3)
    assert (got["gold_groups"], got["gold_found"], got["gold_out_of_table"]) == (4, 3, 1)
    assert got["precision"] == pytest.approx(0.75)
    assert got["recall"] == pytest.approx(0.75)
    assert got["f1"] == pytest.approx(0.75)


def test_committed_sheet_is_blank_and_split_exact() -> None:
    doc = json.loads((ROOT / "data/eval/parser_gold/sheet.v1.json").read_text(encoding="utf8"))
    assert doc["n"] == len(doc["lines"]) == 300
    assert set(doc["counts"].values()) == {50}
    texts = {r["text"].casefold() for r in doc["lines"]}
    assert len(texts) == 300
    # no resolver output and no labels in the sheet
    assert set(doc["lines"][0]) == {
        "id", "text", "page", "revision_id", "revision_url", "stratum", "split",
    }  # fmt: skip
