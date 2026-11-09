"""Table v2 columns, word file, singulariser and modifier tests. Inputs are invented."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import pytest

import pantrychef.ingredients.resolve as resolve_mod
from pantrychef.ingredients.resolve import resolve_lines
from pantrychef.ingredients.table import (
    DEFAULT_TABLE_PATH,
    DEFAULT_WORDS_PATH,
    TABLE_V1_PATH,
    TABLE_V2_PATH,
    IngredientTable,
    Words,
    is_modifier,
    tokens,
)
from pantrychef.ingredients.units import parse_unit
from tests.test_table_round2 import REMOVED as ROUND2_REMOVED

HEADER = "id,name,synonyms,staple,provenance,is_a,form_of\n"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("asparagus", ("asparagus",)),
        ("couscous", ("couscous",)),
        ("hummus", ("hummus",)),
        ("citrus", ("citrus",)),
        ("octopus", ("octopus",)),
        ("molasses", ("molasses",)),
        ("swiss", ("swiss",)),
        ("glass", ("glass",)),
        ("bay leaves", ("bay", "leaf")),
        ("chilies", ("chili",)),
        ("knives", ("knife",)),
        ("cheeses", ("cheese",)),
        ("tomatoes", ("tomato",)),
        ("potatoes", ("potato",)),
        ("berries", ("berry",)),
        ("boxes", ("box",)),
        ("halves", ("half",)),
        ("loaves", ("loaf",)),
        ("eggs", ("egg",)),
        ("chilis", ("chili",)),
        ("chillis", ("chilli",)),
        ("zucchinis", ("zucchini",)),
        ("tennis", ("tennis",)),
    ],
)
def test_tokens_singulariser(text, expected):
    assert tokens(text) == expected


def test_canonicalize_is_unchanged_for_research_code():
    from pantrychef.ingredients.normalize import canonicalize

    assert canonicalize("asparagus") == "asparagu"  # research artifacts depend on this


def _rows(*lines: str) -> str:
    """CSV text with the given rows plus the two rows the default word file names."""
    staples = ("salt,salt,,1,hand,,", "black_pepper,black pepper,,1,hand,,")
    return HEADER + "".join(ln + "\n" for ln in (*lines, *staples))


def test_edge_to_unknown_id_fails_and_names_the_id():
    with pytest.raises(ValueError, match="nope"):
        IngredientTable.from_text(_rows("a,apple,,0,hand,nope,"))
    with pytest.raises(ValueError, match="ghost"):
        IngredientTable.from_text(_rows("a,apple,,0,hand,,ghost"))


def test_self_edge_fails():
    with pytest.raises(ValueError, match="itself"):
        IngredientTable.from_text(_rows("a,apple,,0,hand,a,"))


def test_cycle_fails():
    with pytest.raises(ValueError, match="cycle"):
        IngredientTable.from_text(
            _rows("a,apple,,0,hand,b,", "b,berry,,0,hand,c,", "c,cherry,,0,hand,a,")
        )


def test_valid_edges_load_as_tuples():
    t = IngredientTable.from_text(
        _rows(
            "fruit,fruit,,0,hand,,",
            "dried_fig,dried fig,,0,hand,fruit,fig",
            "fig,fig,,0,hand,fruit,",
        )
    )
    assert t.by_id["dried_fig"].is_a == ("fruit",)
    assert t.by_id["dried_fig"].form_of == ("fig",)
    assert t.by_id["fruit"].is_a == () and t.by_id["fruit"].form_of == ()


def test_pipe_separated_edges():
    t = IngredientTable.from_text(
        _rows("a,apple,,0,hand,,", "b,berry,,0,hand,,", "c,cherry,,0,hand,a|b,")
    )
    assert t.by_id["c"].is_a == ("a", "b")


def test_v1_file_without_edge_columns_still_loads():
    t = IngredientTable.load(TABLE_V1_PATH)
    assert all(r.is_a == () and r.form_of == () for r in t.rows)


def test_v2_keeps_every_v1_row():
    def read(p):
        with open(p, encoding="utf8", newline="") as fh:
            return {r["id"]: r for r in csv.DictReader(fh)}

    v1, v2 = read(TABLE_V1_PATH), read(TABLE_V2_PATH)
    for rid, r in v1.items():
        assert rid in v2, rid
        for col in ("name", "staple", "provenance"):
            assert v2[rid][col] == r[col], (rid, col)
        old = {s for s in r["synonyms"].split("|") if s}
        # Task 5 round 2 removed these (see tests/test_table_round2.py): table errors and
        # workarounds for the old head-noun rule.
        old -= ROUND2_REMOVED.get(rid, set())
        assert old <= {s for s in v2[rid]["synonyms"].split("|") if s}, rid


def test_v2_loads_without_duplicate_ids():
    t = IngredientTable.load(TABLE_V2_PATH)
    assert len(t.by_id) == len(t.rows)
    assert len(t.rows) >= len(IngredientTable.load(TABLE_V1_PATH).rows)


def test_default_table_is_v2_and_v1_keeps_its_name():
    assert DEFAULT_TABLE_PATH == TABLE_V2_PATH
    assert TABLE_V1_PATH.name == "ingredients.csv"
    assert TABLE_V2_PATH.name == "ingredients.v2.csv"
    assert len(IngredientTable.load().rows) == len(IngredientTable.load(TABLE_V2_PATH).rows)


def test_words_file_has_every_list():
    w = IngredientTable.from_text(_rows("a,apple,,0,hand,,")).words
    assert isinstance(w, Words)
    assert w.units["tbsp"] == "tbsp" and w.units["cups"] == "cup"
    assert {"small", "large"} <= w.size
    assert "chopped" in w.prep and "large" not in w.prep
    assert w.staple_cue == frozenset({"salt"})
    assert w.bare_pepper == {"target": "black_pepper", "when": "staple_cue_or_taste"}


def test_load_reads_a_given_words_file(tmp_path):
    raw = json.loads(DEFAULT_WORDS_PATH.read_text(encoding="utf8"))
    raw["staple_cue"] = ["water"]
    p = tmp_path / "words.json"
    p.write_text(json.dumps(raw), encoding="utf8")
    t = IngredientTable.load(TABLE_V2_PATH, words=p)
    assert t.words.staple_cue == frozenset({"water"})


def test_parse_unit_reads_units_from_the_words_object():
    assert parse_unit("cups flour") == ("cup", "flour")
    assert parse_unit("scoops flour", {"scoops": "scoop"}) == ("scoop", "flour")
    assert parse_unit("cups flour", {"scoops": "scoop"}) == (None, "cups flour")


def test_is_modifier():
    w = IngredientTable.from_text(_rows("a,apple,,0,hand,,")).words
    assert is_modifier("large", w)  # size
    assert is_modifier("chopped", w)  # prep list
    assert is_modifier("minced", w)  # prep list and an -ed word
    assert is_modifier("grilled", w)  # any -ed word of length > 4
    assert not is_modifier("flaxseed", w)
    assert not is_modifier("apple", w)
    assert not is_modifier("red", w)  # too short for the -ed rule


def test_is_modifier_uses_container_words():
    w = Words(
        units={},
        size=frozenset(),
        container=frozenset({"jar"}),
        prep=frozenset(),
        staple_cue=frozenset(),
        bare_pepper={},
    )
    assert is_modifier("jar", w) and not is_modifier("tin", w)


MEAT = _rows(
    "beef,beef,,0,hand,,",
    "ground_beef,ground beef,,0,hand,beef,",
    "pear,pear,,0,hand,,",
)


def test_lean_ground_beef_reads_ground_beef_not_beef():
    t = IngredientTable.from_text(MEAT)
    (line,) = resolve_lines("1 lb lean ground beef", t)
    assert line.options == ("ground_beef",)


def test_peeled_and_diced_pears_read_pear():
    t = IngredientTable.from_text(MEAT)
    (line,) = resolve_lines("3 large ripe pears, peeled and diced", t)
    assert line.options == ("pear",) and line.read


def test_bare_pepper_target_and_salt_cue_come_from_the_words():
    t = IngredientTable.from_text(MEAT)
    assert resolve_lines("pepper", t)[0].read is False
    assert resolve_lines("pepper to taste", t)[0].options == ("black_pepper",)
    swapped = IngredientTable.from_text(
        MEAT,
        json.dumps(
            {
                "units": {},
                "size": [],
                "container": [],
                "prep": [],
                "staple_cue": ["beef"],
                "bare_pepper": {"target": "pear", "when": "staple_cue_or_taste"},
            }
        ),
    )
    lines = resolve_lines("beef, pepper", swapped)
    assert [ln.options for ln in lines] == [("beef",), ("pear",)]


def _words_json(**over) -> str:
    raw = json.loads(DEFAULT_WORDS_PATH.read_text(encoding="utf8"))
    raw.update(over)
    return json.dumps({k: v for k, v in raw.items() if v is not None})


def test_bare_pepper_target_must_be_a_table_id():
    words = _words_json(bare_pepper={"target": "ghost_pepper", "when": "staple_cue_or_taste"})
    with pytest.raises(ValueError, match=r"bare_pepper.*ghost_pepper"):
        IngredientTable.from_text(MEAT, words)


def test_staple_cue_ids_must_be_table_ids():
    with pytest.raises(ValueError, match=r"staple_cue.*brine"):
        IngredientTable.from_text(MEAT, _words_json(staple_cue=["salt", "brine"]))


def test_bare_pepper_when_must_be_known():
    words = _words_json(bare_pepper={"target": "black_pepper", "when": "sometimes"})
    with pytest.raises(ValueError, match=r"bare_pepper.*sometimes"):
        IngredientTable.from_text(MEAT, words)


@pytest.mark.parametrize("key", ["units", "size", "container", "prep", "staple_cue", "bare_pepper"])
def test_missing_words_key_names_the_key(key):
    with pytest.raises(ValueError, match=f"words file has no {key!r}"):
        IngredientTable.from_text(MEAT, _words_json(**{key: None}))


def test_trailing_ok_is_optional_and_loads():
    t = IngredientTable.from_text(MEAT, _words_json(trailing_ok=None))
    assert t.words.trailing_ok == frozenset()
    assert {"clove", "leaf"} <= IngredientTable.from_text(MEAT).words.trailing_ok


@pytest.mark.parametrize("path", [TABLE_V1_PATH, TABLE_V2_PATH])
def test_resolve_has_no_string_literal_equal_to_a_table_id(path):
    ids = set(IngredientTable.load(path).by_id)
    tree = ast.parse(Path(resolve_mod.__file__).read_text(encoding="utf8"))
    doc = ast.get_docstring(tree, clean=False)
    literals = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value != doc
    }
    assert not literals & ids, literals & ids
