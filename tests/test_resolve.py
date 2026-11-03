"""Table and line resolver tests. Lines are real Wikibooks Cookbook lines (CC BY-SA)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import pantrychef.ingredients.resolve as resolve_mod
import pantrychef.ingredients.table as table_mod
from pantrychef.ingredients.resolve import resolve_lines
from pantrychef.ingredients.table import IngredientTable


@pytest.fixture(scope="module")
def table() -> IngredientTable:
    return IngredientTable.load()


def _one(table, text):
    lines = resolve_lines(text, table)
    assert len(lines) == 1, lines
    return lines[0]


def test_table_loads_with_expected_staples(table):
    assert table.staples == {"water", "salt", "black_pepper", "vegetable_oil"}
    assert len(table.rows) >= 250
    assert {r.provenance for r in table.rows} <= {"hand", "wikibooks-rule"}


def test_table_rejects_conflicting_keys(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("id,name,synonyms,staple,provenance\na,milk,,0,hand\nb,cream,milk,0,hand\n")
    with pytest.raises(ValueError, match="used by"):
        IngredientTable.load(p)


def test_table_and_resolver_never_touch_recipenlg_vocab():
    for mod in (table_mod, resolve_mod):
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf8"))
        doc = ast.get_docstring(tree, clean=False)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value != doc:
                assert "vocab" not in node.value.lower(), (mod.__name__, node.value)
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = [getattr(node, "module", None) or ""] + [a.name for a in node.names]
                assert not any("vocab" in n for n in names), (mod.__name__, names)


@pytest.mark.parametrize(
    ("text", "ids"),
    [
        ("2 cups all-purpose flour", ("flour",)),
        ("1 cup (240 ml) or 1 part half and half", ("half_and_half",)),
        ("2 tablespoons peanut butter", ("peanut_butter",)),
        ("1 pound (450 g) fettuccine egg noodles", ("egg_noodle",)),
        ("16 wonton wrappers or 24 egg roll wrappers", ("wonton_wrapper",)),
        ("1 head Romaine lettuce, roughly chopped", ("lettuce",)),
        ("Heavy pinch of sea salt", ("salt",)),
        ("350 g (¾ lb) dried red kidney beans, soaked and cooked", ("kidney_bean",)),
        ("1 ea. (½ cup) finely-chopped medium onion", ("onion",)),
        ("Nonstick cooking spray or vegetable oil", ("cooking_spray", "vegetable_oil")),
        ("4 cloves garlic, minced", ("garlic",)),
        ("1 (13-ounce) can evaporated milk", ("evaporated_milk",)),
        ("Butter", ("butter",)),
    ],
)
def test_real_lines_resolve(table, text, ids):
    line = _one(table, text)
    assert line.options == ids and line.read and not line.optional


def test_salt_and_pepper_to_taste_gives_two_optional_staple_lines(table):
    lines = resolve_lines("salt and pepper to taste", table)
    assert [(ln.options, ln.optional) for ln in lines] == [
        (("salt",), True),
        (("black_pepper",), True),
    ]


def test_bare_pepper_is_unread_unless_salt_or_taste(table):
    bare = _one(table, "Pepper")
    assert not bare.read and bare.options == ()
    assert _one(table, "Pepper to taste").options == ("black_pepper",)


def test_optional_and_garnish_flags(table):
    assert _one(table, "2 teaspoons cumin (optional)").optional
    assert _one(table, "Cilantro, for garnishing").optional
    assert not _one(table, "2 teaspoons cumin").optional


def test_to_taste_is_optional_only_for_staples(table):
    assert _one(table, "Salt to taste").optional
    assert not _one(table, "Hot sauce to taste").optional


def test_and_part_unknown_makes_whole_line_unread(table):
    line = _one(table, "2 cups flour and zzzfruit")
    assert not line.read and line.options == ()


def test_unknown_main_ingredient_is_unread_and_keeps_text(table):
    line = _one(table, "3 cups xylophone paste")
    assert not line.read and line.text == "3 cups xylophone paste"


def test_heading_lines_are_not_ingredients(table):
    assert resolve_lines("For the sauce:", table) == []


def test_comma_list_gives_one_line_per_ingredient(table):
    lines = resolve_lines("garlic, ginger and onion", table)
    assert [ln.options for ln in lines] == [("garlic",), ("ginger",), ("onion",)]


def test_optional_overrides_unread(table):
    line = _one(table, "3 cups xylophone paste (optional)")
    assert line.optional and not line.read


def test_comma_list_ending_in_or_is_one_or_line(table):
    line = _one(table, "Chicken, vegetable, or beef broth")
    assert line.options == ("chicken", "mixed_vegetables", "beef_stock") and line.read


def test_boneless_skinless_commas_do_not_hide_the_ingredient(table):
    assert _one(table, "2 boneless, skinless chicken breasts").options == ("chicken",)


def test_lone_clove_unit_means_the_spice(table):
    assert _one(table, "4 cloves").options == ("cloves",)
