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
    "black_pepper,black pepper,,1,hand\n"
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


# ---- M3: mention_accuracy, id_map, line_hash ----

BULGUR = IngredientTable.from_text(
    "id,name,synonyms,staple,provenance\n"
    "bulgur,bulgur,,0,hand\n"
    "cracked_wheat,cracked wheat,,0,hand\n"
    "rice,rice,,0,hand\n"
    "egg,egg,eggs,0,hand\n"
    "flour,flour,,0,hand\n"
    "salt,salt,,1,hand\n"
    "black_pepper,black pepper,,1,hand\n"
)


def test_mention_accuracy_counts_subset_reads() -> None:
    labels = {
        "1": Label((("bulgur", "cracked wheat"),), False, False),
        "2": Label((("bulgur", "cracked wheat"),), False, False),
    }
    # line 1 reads {bulgur}: a subset of the gold group, so it counts.
    got = score([{"id": "1", "text": "1 cup bulgur"}], labels, BULGUR)
    assert got["mention_accuracy"] == 1.0
    # line 2 reads {bulgur, rice}: rice is outside the gold group, so it does not count.
    got = score([{"id": "2", "text": "1 cup bulgur or rice"}], labels, BULGUR)
    assert got["mention_accuracy"] == 0.0


def test_mention_accuracy_counts_gold_groups() -> None:
    lines = [{"id": "1", "text": "2 eggs, flour"}, {"id": "2", "text": "3 kumquats"}]
    labels = {
        "1": Label((("egg",), ("flour",)), False, False),
        "2": Label((("kumquat",),), False, False),
    }
    got = score(lines, labels, BULGUR)
    assert got["mention_accuracy"] == pytest.approx(2 / 3)  # egg, flour yes; kumquat no


def test_id_map_overrides_table_keys() -> None:
    lines = [{"id": "1", "text": "2 eggs"}]
    labels = {"1": Label((("egg",),), False, False)}
    assert score(lines, labels, BULGUR)["mention_accuracy"] == 1.0
    # the map wins over the table key: gold "egg" is now flour, so the read of egg is wrong
    assert score(lines, labels, BULGUR, id_map={"egg": "flour"})["mention_accuracy"] == 0.0
    # a gold name the table cannot key still maps through the map
    labels = {"1": Label((("hen fruit",),), False, False)}
    assert score(lines, labels, BULGUR)["mention_accuracy"] == 0.0
    assert score(lines, labels, BULGUR, id_map={"hen fruit": "egg"})["mention_accuracy"] == 1.0
    # a name mapped to None has no id
    got = score(lines, labels, BULGUR, id_map={"hen fruit": None})
    assert got["mention_accuracy"] == 0.0
    assert got["gold_out_of_table"] == 1


def test_line_hash_form() -> None:
    import hashlib

    from pantrychef.eval.parser_gold import line_hash

    assert line_hash("  Salt ") == line_hash("salt")
    assert line_hash("salt") == hashlib.sha256(b"salt").hexdigest()


def test_id_map_missing_name_raises() -> None:
    lines = [{"id": "1", "text": "2 eggs"}]
    labels = {"1": Label((("egg", "hen fruit"),), False, False)}
    with pytest.raises(LabelError, match="hen fruit"):
        score(lines, labels, BULGUR, id_map={"egg": "egg"})
    # a value of None still means "no id", and it is not an error
    got = score(lines, labels, BULGUR, id_map={"egg": "egg", "hen fruit": None})
    assert got["mention_accuracy"] == 1.0


def test_id_map_keys_and_lookups_are_normalised() -> None:
    lines = [{"id": "1", "text": "2 eggs"}]
    labels = {"1": Label((("Egg",),), False, False)}
    # the map key has another case and plural form than the gold name: both normalise alike
    assert score(lines, labels, BULGUR, id_map={"EGGS": "egg"})["mention_accuracy"] == 1.0
