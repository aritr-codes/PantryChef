"""Table and line resolver tests. Lines are real Wikibooks Cookbook lines (CC BY-SA)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import pantrychef.ingredients.resolve as resolve_mod
import pantrychef.ingredients.table as table_mod
from pantrychef.ingredients.resolve import resolve_lines
from pantrychef.ingredients.table import DEFAULT_WORDS_PATH, IngredientTable


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


def test_a_staple_never_hides_a_real_ingredient(table):
    assert _one(table, "Cornstarch mixed with 1/2 cup cold water").options == ("cornstarch",)
    # A staple right after a food is a product form ("chile oil"), not a hidden staple (M3 6a).
    assert not _one(table, "1 tsp chile oil").read
    assert _one(table, "1 tbsp oil").options == ("vegetable_oil",)


def test_seed_words_are_not_preparation_words(table):
    line = _one(table, "2 cups flour and flaxseed")
    assert not line.read  # flaxseed is unknown, and "-seed" words are not "-ed" verbs


def test_compound_names_beat_their_last_word(table):
    assert _one(table, "1 cup pepper jack cheese").options == ("monterey_jack",)
    assert _one(table, "2 tbsp cashew butter").options == ("cashew_butter",)
    assert _one(table, "1 can cream of mushroom soup").options == ("condensed_soup",)


# --- M3 Task 6a: trailing head noun and chili pepper rules. Invented table and lines. ---

FOOD = (
    "id,name,synonyms,staple,provenance\n"
    "garlic,garlic,,0,hand\n"
    "basil,basil,,0,hand\n"
    "pomegranate,pomegranate,,0,hand\n"
    "almond,almond,,0,hand\n"
    "ginger,ginger,,0,hand\n"
    "egg,egg,,0,hand\n"
    "lemon,lemon,,0,hand\n"
    "lemon_juice,lemon juice,,0,hand\n"
    "flaxseed,flaxseed,linseed,0,hand\n"
    "chili_pepper,chili pepper,chile|chili,0,hand\n"
    "cornstarch,cornstarch,,0,hand\n"
    "salt,salt,,1,hand\n"
    "black_pepper,black pepper,,1,hand\n"
    "vegetable_oil,vegetable oil,oil,1,hand\n"
    "water,water,,1,hand\n"
)


def _words(**over) -> str:
    raw = json.loads(DEFAULT_WORDS_PATH.read_text(encoding="utf8"))
    raw.update(over)
    return json.dumps(raw)


@pytest.fixture(scope="module")
def food() -> IngredientTable:
    return IngredientTable.from_text(FOOD)


def _ids(table, text):
    return [(ln.options, ln.read) for ln in resolve_lines(text, table)]


@pytest.mark.parametrize(
    "text",
    [
        "1 cup pomegranate juice",
        "1 tbsp chili garlic sauce",
        "1 tsp ginger garlic paste",
        "1 cup almond flour",
        "2 tbsp linseed oil",  # a staple head after a food is a product form, not the food
        "1 tsp chile oil",
        "2 eggs and pomegranate juice",
    ],
)
def test_unexplained_trailing_head_noun_makes_the_line_unread(food, text):
    assert _ids(food, text) == [((), False)]


def test_a_key_that_covers_the_whole_phrase_still_reads(food):
    assert _ids(food, "2 tbsp lemon juice") == [(("lemon_juice",), True)]


@pytest.mark.parametrize(
    ("text", "ids"),
    [
        ("3 cloves garlic", ("garlic",)),
        ("2 garlic cloves", ("garlic",)),
        ("2 garlic cloves, crushed", ("garlic",)),
        ("1 cup chopped fresh basil leaves", ("basil",)),
        ("2 basil sprigs", ("basil",)),
        ("2 eggs, beaten", ("egg",)),
        ("Cornstarch mixed with 1/2 cup cold water", ("cornstarch",)),
    ],
)
def test_benign_trailing_words_keep_the_food(food, text, ids):
    assert _ids(food, text) == [(ids, True)]


def test_or_alternative_with_unexplained_head_is_dropped_not_misread(food):
    assert _ids(food, "pomegranate juice or lemon juice") == [(("lemon_juice",), True)]


def test_comma_still_stops_a_match_and_a_trailing_check(food):
    # "juice" sits in another comma chunk, so it is not a head noun of "lemon".
    assert _ids(food, "1 lemon, juice only")[0] == (("lemon",), True)


def test_chili_pepper_reads_without_a_bare_pepper_line(food):
    assert _ids(food, "1 green chile pepper, chopped") == [(("chili_pepper",), True)]
    always = IngredientTable.from_text(
        FOOD, _words(bare_pepper={"target": "black_pepper", "when": "always"})
    )
    assert _ids(always, "1 green chile pepper, chopped") == [(("chili_pepper",), True)]


def test_salt_and_pepper_still_reads_salt_and_black_pepper(food):
    assert _ids(food, "salt and pepper") == [(("salt",), True), (("black_pepper",), True)]


def test_pepper_after_salt_is_still_a_bare_pepper(food):
    # A staple is not a name that "pepper" extends, so the marker stays and salt cues it.
    assert _ids(food, "salt pepper") == [(("black_pepper",), True)]


def test_bare_pepper_when_staple_cue_or_taste(food):
    assert _ids(food, "1 tsp pepper") == [((), False)]
    assert _ids(food, "pepper to taste") == [(("black_pepper",), True)]
    assert _ids(food, "garlic, salt, pepper") == [
        (("garlic",), True),
        (("salt",), True),
        (("black_pepper",), True),
    ]


def test_bare_pepper_when_always(food):
    always = IngredientTable.from_text(
        FOOD, _words(bare_pepper={"target": "black_pepper", "when": "always"})
    )
    assert _ids(always, "1 tsp pepper") == [(("black_pepper",), True)]
    assert _ids(always, "1 tsp ground pepper") == [(("black_pepper",), True)]
