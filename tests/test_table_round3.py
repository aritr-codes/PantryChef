"""M3 Task 11 table round 3: generic class rows, flours, ferments and a few synonyms.

Lines are invented. The names come from the error analysis of the spent sets (foods only).
"""

from __future__ import annotations

import pytest

from pantrychef.ingredients.resolve import resolve_lines
from pantrychef.ingredients.table import TABLE_V2_PATH, IngredientTable


@pytest.fixture(scope="module")
def table() -> IngredientTable:
    return IngredientTable.load(TABLE_V2_PATH)


def _ids(table, text):
    return [(ln.options, ln.read) for ln in resolve_lines(text, table)]


NEW_ROWS = {
    "herbs", "spices", "seasoning", "sorghum", "sorghum_flour", "millet_flour",
    "orange_blossom_water", "bagel_chips", "bitter_melon", "vegetarian_oyster_sauce",
    "doenjang", "vanilla_sugar", "egg_substitute", "wine_yeast", "yeast_nutrient",
    "drink_mix", "pate", "pork_stomach", "seafood",
}  # fmt: skip


def test_round_3_appends_rows(table):
    assert len(table.rows) == 894
    assert set(table.by_id) >= NEW_ROWS


def test_generic_class_rows_are_not_staples(table):
    for rid in ("herbs", "spices", "seasoning"):
        assert rid not in table.staples
    assert table.by_id["italian_seasoning"].name == "italian seasoning"  # a longer key still wins


@pytest.mark.parametrize(
    ("text", "ids"),
    [
        ("1 handful fresh herbs, chopped", "herbs"),
        ("1 tsp dried spices", "spices"),
        ("seasoning to taste", "seasoning"),
        ("1 cup sorghum flour", "sorghum_flour"),
        ("2 cups millet flour", "millet_flour"),
        ("1 cup sorghum", "sorghum"),
        ("1 tsp orange blossom water", "orange_blossom_water"),
        ("1 cup bagel chips", "bagel_chips"),
        ("1 bitter melon, seeded and sliced", "bitter_melon"),
        ("2 tbsp vegetarian oyster sauce", "vegetarian_oyster_sauce"),
        ("1 tbsp oyster sauce", "oyster_sauce"),
        ("1 tbsp doenjang", "doenjang"),
        ("1 tsp vanilla sugar", "vanilla_sugar"),
        ("1 tbsp sugar", "sugar"),
        ("1 tbsp egg substitute", "egg_substitute"),
        ("2 eggs", "egg"),
        ("1 packet wine yeast", "wine_yeast"),
        ("1 packet dry yeast", "yeast"),
        ("1 tsp yeast nutrient", "yeast_nutrient"),
        ("1 packet powdered drink mix", "drink_mix"),
        ("1 tbsp anchovy sauce", "fish_sauce"),
        ("1 tsp sardine oil", "fish_oil"),
        ("4 dried sardines", "dried_fish"),
        ("1 lb sardines", "sardine"),
        ("1 pork pate, sliced", "pate"),
        ("1 cup mixed seafood", "seafood"),
        ("1 tbsp red pepper paste", "chili_paste"),
        ("300 g pasta spirals", "pasta"),
        ("1 inch ginseng root", "ginseng"),
        ("1 tsp yeast extract spread", "yeast_extract"),
        ("4 hamburger rolls", "bread_roll"),
        ("2 tsp poultry seasoning", "poultry_seasoning"),
        ("1 tsp pumpkin pie spice", "mixed_spice"),
    ],
)
def test_round_3_probes(table, text, ids):
    assert _ids(table, text) == [((ids,), True)]


def test_edges(table):
    by = table.by_id
    assert by["sorghum_flour"].form_of == ("sorghum",)
    assert by["millet_flour"].form_of == ("millet",)
    assert by["bagel_chips"].form_of == ()  # bagel is_a bread: an edge would make a depth-2 chain
    assert by["vanilla_sugar"].is_a == ("sugar",)
    assert by["wine_yeast"].is_a == ("yeast",)
    for rid in NEW_ROWS:
        assert by[rid].provenance == "wikibooks-rule"


def test_bare_roll_is_not_a_key(table):
    # A bare "roll" key would read "egg roll", "spring roll" and "cinnamon roll" as bread rolls
    # (probed in M3 Task 11), so only the named bread rolls are keys.
    assert ("roll",) not in table.keys
    for text in ("1 egg roll", "1 spring roll", "1 cinnamon roll"):
        assert _ids(table, text) == [((), False)]
    assert _ids(table, "16 spring roll wrappers") == [(("wonton_wrapper",), True)]


def test_near_lines_stay_as_they_were(table):
    assert _ids(table, "1 herb de provence jar") == [((), False)]  # an unknown word still unreads
    assert _ids(table, "1 tbsp herb oil") == [((), False)]  # a staple after a food is a product
    assert _ids(table, "1 herb butter") == [(("butter",), True)]


def test_a_known_spice_name_beats_the_generic_row(table):
    assert _ids(table, "1 tsp mitmita spice") == [(("mitmita",), True)]
    assert _ids(table, "1 tsp accent seasoning") == [(("msg",), True)]


@pytest.mark.parametrize(
    ("text", "ids"),
    [
        ("1 cup ground peanuts", "peanut"),
        ("1 cup peanut powder", "peanut_powder"),
        ("1 cup green gram flour", "mung_bean_flour"),
        ("1 cup black gram flour", "urad_flour"),
        ("1 cup gram flour", "chickpea_flour"),
        ("1 tsp maggi seasoning", "maggi_seasoning"),
        ("1 maggi cube", "seasoning_cube"),
        ("1 tsp baharat spice", "baharat"),
    ],
)
def test_fix_round_1_rows_beat_the_generic_readings(table, text, ids):
    assert _ids(table, text) == [((ids,), True)]
