"""M3 Task 5 round 2: the v2 table now has its own rows for product forms.

The phrases below are lines from the snapshot unread list (Wikibooks Cookbook, CC BY-SA) or
invented. Edges and removed synonyms are pinned here.
"""

from __future__ import annotations

import pytest

from pantrychef.ingredients.names import resolve_name
from pantrychef.ingredients.resolve import resolve_lines
from pantrychef.ingredients.table import TABLE_V2_PATH, IngredientTable

# The only synonyms the round removes. The two "garlic" ones were table errors. The chili ones
# were workarounds for the old head-noun rule: the line resolver reads them through "chili",
# "chile" or "chilli" and the pepper rule, and the typed-name resolver reaches them by the
# "contained" step. The other 13 old chili phrases came back (review fix): without them the typed
# resolver only reached chili_pepper by the fuzzy step.
REMOVED = {
    "garlic": {"garlic powder", "garlic salt"},
    "chili_pepper": {
        "hot chili pepper",
        "fresh chili",
        "dry red chilly",
        "dried red chilly",
        "dried red chili pepper",
        "dried chili",
        "dried chile",
        "dried chile pepper",
        "fresh chile pepper",
        "fresh chili pepper",
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
        ("1 cup ginger garlic sauce", "ginger_garlic_paste"),
        ("1 tbsp chili paste", "chili_paste"),
        ("1 tsp green chile paste", "chili_paste"),
        ("1 tsp red chili sauce", "hot_sauce"),
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
        ("1 tsp ground chile pepper (to taste)", "chili_pepper"),  # no "ground chile" key
        ("2 tbsp ground chilli", "chili_pepper"),
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
    assert len(table.rows) == 872
    assert {r.provenance for r in table.rows} <= {"hand", "wikibooks-rule"}


def test_a_bare_food_word_does_not_read_as_an_organ_or_a_note(table):
    # "kidney" alone is a bean here. The organ row needs a full name.
    assert "kidney" not in _ids(table, "2 cans kidney, black, or pinto beans")[0][0]
    assert "kidney" not in {" ".join(k) for k in table.keys}
    assert _ids(table, "4 chicken thighs, giblets removed") == [(("chicken",), True)]


@pytest.mark.parametrize(
    "name",
    [
        "green chili",
        "red chili",
        "green chile",
        "red chile",
        "green chile pepper",
        "medium green chile pepper",
        "fresh red chile pepper",
        "dried chile pepper",
        "fresh chilli",
    ],
)
def test_typed_chili_names_reach_chili_pepper_without_fuzzy_matching(table, name):
    keys = {" ".join(k): i for k, i in table.keys.items()}
    match = resolve_name(name, keys, table.words)
    assert match.ids == ("chili_pepper",)
    assert match.step in ("exact", "contained")


@pytest.mark.parametrize(
    ("text", "ids"),
    [
        ("3 chicken carcasses", "chicken_carcass"),
        ("1 cup cider", "cider"),
        ("1 bunch mustard greens", "mustard_greens"),
        ("1 beef heart", "beef_heart"),
        ("1 beef tongue", "beef_tongue"),
        ("2 tbsp goose fat", "goose_fat"),
        ("2 tbsp duck fat", "duck_fat"),
        ("2 tbsp chicken fat", "chicken_fat"),
        ("1 cup oat bran", "oat_bran"),
        ("1 quince", "quince"),
        ("1 head frisee", "frisee"),
        ("2 sea urchin", "sea_urchin"),
        ("1 cup pork blood", "pork_blood"),
        ("1 tbsp thai chili sauce", "thai_chili_sauce"),
        ("1 tbsp texturized soy protein", "textured_vegetable_protein"),
        ("1 tsp soy lecithin", "soy_lecithin"),
        ("1/4 cup barberries", "barberry"),
        ("1 jar piccalilli", "piccalilli"),
        ("1 cup hazelnut meal", "hazelnut"),
        ("2 screwpine leaves", "pandan_leaf"),
        ("1 tsp ground curcuma", "turmeric"),
        ("1 cup salsa fresca", "salsa"),
    ],
)
def test_review_fix_foods_read(table, text, ids):
    assert _ids(table, text) == [((ids,), True)]


def test_ground_meat_edges(table):
    assert table.by_id["ground_chicken"].form_of == ("chicken",)
    assert table.by_id["ground_chicken"].is_a == ()
    assert table.by_id["ground_beef"].form_of == ("beef",)
