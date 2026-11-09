"""M3 Task 5 round 2: the v2 table now has its own rows for product forms.

The phrases below are lines from the snapshot unread list (Wikibooks Cookbook, CC BY-SA) or
invented. Edges and removed synonyms are pinned here.
"""

from __future__ import annotations

import pytest

from pantrychef.ingredients.resolve import resolve_lines
from pantrychef.ingredients.table import TABLE_V2_PATH, IngredientTable

# The only synonyms the round removes. The two "garlic" ones were table errors. The chili ones
# were workarounds for the old head-noun rule: the line resolver reads them through "chili",
# "chile" or "chilli" and the pepper rule, and the typed-name resolver still finds them.
REMOVED = {
    "garlic": {"garlic powder", "garlic salt"},
    "chili_pepper": {
        "green chili",
        "red chili",
        "green chile",
        "red chile",
        "hot chili pepper",
        "fresh chili",
        "dry red chilly",
        "dried red chilly",
        "green chile pepper",
        "red chile pepper",
        "green chilli pepper",
        "red chilli pepper",
        "dried red chile pepper",
        "dried red chili pepper",
        "dried chili",
        "dried chile",
        "dried chile pepper",
        "fresh chile pepper",
        "fresh chili pepper",
        "fresh red chile pepper",
        "fresh green chile pepper",
        "medium green chile pepper",
        "small dried red chile pepper",
        "fresh chilli",
        "dried chilli",
    },
}


@pytest.fixture(scope="module")
def table() -> IngredientTable:
    return IngredientTable.load(TABLE_V2_PATH)


def _ids(table, text):
    return [(ln.options, ln.read) for ln in resolve_lines(text, table)]


@pytest.mark.parametrize(
    ("text", "ids"),
    [
        ("1 tsp garlic powder", "garlic_powder"),
        ("1 tsp garlic salt", "garlic_salt"),
        ("1 tsp onion salt", "onion_salt"),
        ("1 tsp seasoning salt", "seasoned_salt"),
        ("2 tsp red chili powder", "chili_powder"),
        ("2 tsp red chile powder", "chili_powder"),
        ("1 tbsp ginger paste", "ginger_paste"),
        ("1 tbsp garlic paste", "garlic_paste"),
        ("1 tbsp ginger garlic paste", "ginger_garlic_paste"),
        ("1 tbsp chili paste", "chili_paste"),
        ("1 tsp instant espresso powder", "coffee_powder"),
        ("1 tsp mango powder", "mango_powder"),
        ("1 tsp amchur", "mango_powder"),
        ("1 cup coconut yogurt", "coconut_yogurt"),
        ("1 cup soy yogurt", "soy_yogurt"),
        ("1 cup frozen yogurt", "frozen_yogurt"),
        ("2 tbsp orange oil", "orange_oil"),
        ("1 tbsp mustard seed oil", "mustard_oil"),
        ("1 cup pomegranate juice", "pomegranate_juice"),
        ("1 cup peach nectar", "peach_nectar"),
        ("2 tbsp montreal steak seasoning", "steak_seasoning"),
        ("2 tbsp red pepper flakes", "red_pepper_flakes"),
        ("1 tbsp nutritional yeast", "nutritional_yeast"),
        ("1 cup white chocolate chips", "white_chocolate_chips"),
        ("1 banana leaf", "banana_leaf"),
        ("2 grape leaves", "grape_leaf"),
        ("2 cassava leaves", "cassava_leaf"),
        ("1 cinnamon leaf", "cinnamon_leaf"),
        ("1 tsp chipotle sauce", "chipotle"),
        ("1 cup custard sauce", "custard"),
        ("1 tsp cardamom powder", "cardamom"),
        ("1 tbsp tamarind concentrate", "tamarind"),
    ],
)
def test_product_forms_read_their_own_row(table, text, ids):
    assert _ids(table, text) == [((ids,), True)]


@pytest.mark.parametrize(
    ("text", "ids"),
    [
        ("2 green chile peppers, chopped", "chili_pepper"),
        ("1 fresh red chile pepper", "chili_pepper"),
        ("3 dried red chilies", "chili_pepper"),
        ("1 green chili", "chili_pepper"),
        ("4 dried chiles", "chili_pepper"),
        ("1 hot chili pepper", "chili_pepper"),
    ],
)
def test_removed_chili_workarounds_still_read(table, text, ids):
    assert _ids(table, text) == [((ids,), True)]


def test_removed_synonyms_are_gone_and_nothing_else_is_lost(table):
    for rid, gone in REMOVED.items():
        have = {" ".join(k) for k, i in table.keys.items() if i == rid}
        assert not (gone & have), (rid, gone & have)
    assert "garlic powder" not in table.by_id["garlic"].synonyms


def test_edges_point_the_right_way(table):
    by = table.by_id
    assert by["garlic_powder"].form_of == ("garlic",)
    assert by["ginger_garlic_paste"].form_of == ("ginger", "garlic")
    assert by["chili_paste"].form_of == ("chili_pepper",)
    assert by["coconut_yogurt"].is_a == ("yogurt",)
    assert by["soy_yogurt"].is_a == ("yogurt",)
    assert by["frozen_yogurt"].is_a == ("yogurt",)
    assert by["garlic_salt"].is_a == ("seasoned_salt",)
    assert by["mulato_chile"].is_a == ("chili_pepper",)


def test_no_new_row_hides_a_bare_product_word(table):
    bare = {
        "powder",
        "paste",
        "sauce",
        "oil",
        "juice",
        "flake",
        "chip",
        "extract",
        "syrup",
        "seasoning",
        "nectar",
        "leaf",
        "mix",
        "spice",
        "blend",
        "puree",
        "concentrate",
    }
    # "oil" is an old synonym of vegetable_oil (a staple). Round 2 adds no other bare word.
    assert {" ".join(k) for k in table.keys} & bare == {"oil"}


def test_round_2_row_count_and_provenance(table):
    assert len(table.rows) == 858
    assert {r.provenance for r in table.rows} <= {"hand", "wikibooks-rule"}
