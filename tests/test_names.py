"""Typed-name resolver tests. Inputs are dev or invented names only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pantrychef.engine import Pack, load_pack, resolve_names
from pantrychef.ingredients.names import NameMatch, resolve_name
from pantrychef.ingredients.table import DEFAULT_WORDS, IngredientTable

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "pack"


@pytest.fixture(scope="module")
def pack() -> Pack:
    return load_pack(FIXTURE, "v1")


def step(pack: Pack, text: str) -> tuple[tuple[str, ...], str]:
    m = resolve_name(text, pack.keys, pack.words)
    return m.ids, m.step


def test_fixture_pack_carries_the_word_lists(pack):
    assert pack.words.units["cups"] == "cup"
    assert "boneless" in pack.words.prep and "can" in pack.words.container


def test_exact_step(pack):
    assert step(pack, "Flour") == (("flour",), "exact")
    assert step(pack, "half and half") == (("half_and_half",), "exact")
    assert step(pack, "Half & Half") == (("half_and_half",), "exact")  # key "half half"
    assert step(pack, "Olive-Oil") == (("olive_oil",), "exact")


def test_contained_step_drops_modifiers_around_a_key(pack):
    assert step(pack, "chicken thighs, boneless") == (("chicken_thigh",), "contained")
    assert step(pack, "lean ground beef") == (("ground_beef",), "contained")
    assert step(pack, "2 large eggs") == (("egg",), "contained")
    assert step(pack, "onion, chopped") == (("onion",), "contained")


def test_longest_key_wins_so_a_modifier_inside_a_key_stays(pack):
    # "ground" is a preparation word, and "ground beef" is a key. The key wins.
    assert step(pack, "ground beef") == (("ground_beef",), "exact")
    assert step(pack, "chopped lean ground beef") == (("ground_beef",), "contained")


def test_contained_needs_every_outside_token_to_be_a_modifier(pack):
    assert step(pack, "flour tortilla wrap")[1] == "none"


def test_quantity_and_unit_are_stripped(pack):
    for text in ("2 cups milk", "½ cup milk", "1⁄2 cup milk", "1 1/2 cups milk", "1/2 cup milk"):
        assert step(pack, text) == (("milk",), "contained"), text
    assert step(pack, "2-3 cloves") == (("clove",), "contained")
    assert step(pack, "2 (8 oz) cans tomatoes") == (("tomato",), "contained")
    assert step(pack, "٣ cups milk") == (("milk",), "contained")


def test_split_step(pack):
    assert step(pack, "s&p") == (("salt", "black_pepper"), "split")
    assert step(pack, "flour and sugar") == (("flour", "sugar"), "split")
    assert step(pack, "flour/sugar") == (("flour", "sugar"), "split")
    assert step(pack, "milk, eggs, butter") == (("milk", "egg", "butter"), "split")
    assert step(pack, "flour, flour") == (("flour",), "split")  # deduped


def test_split_needs_every_part_to_resolve(pack):
    # "pepper" is not a key (D6), so the whole input stays unknown.
    assert step(pack, "pepper") == ((), "none")
    assert step(pack, "salt and pepper") == ((), "none")


def test_a_key_that_holds_a_separator_word_is_not_split(pack):
    assert step(pack, "half and half") == (("half_and_half",), "exact")


def test_fuzzy_step(pack):
    assert step(pack, "cinamon") == (("cinnamon",), "fuzzy")  # one missing letter
    assert step(pack, "gralic") == (("garlic",), "fuzzy")  # two letters swapped
    assert step(pack, "margerine") == (("margarine",), "fuzzy")  # 9 letters, distance 1
    assert step(pack, "ground cinamon") == (("cinnamon",), "fuzzy")  # modifier dropped first
    assert step(pack, "2 cups cinamon") == (("cinnamon",), "fuzzy")  # quantity and unit first


def test_fuzzy_allows_distance_two_from_eight_letters():
    keys = {"cinnamon sugar": "cs"}
    words = DEFAULT_WORDS
    assert resolve_name("cinamon sugr", keys, words) == NameMatch(("cs",), "fuzzy")  # 12 letters
    assert resolve_name("cinamon sgr", keys, words).step == "none"  # distance 3


def test_fuzzy_ties_give_none(pack):
    # "peaz" is one edit from "pea" and from "pear".
    assert step(pack, "peaz") == ((), "none")
    keys = {"lime": "lime", "lake": "lake"}
    assert resolve_name("lame", keys, DEFAULT_WORDS) == NameMatch((), "none")
    assert resolve_name("limp", keys, DEFAULT_WORDS) == NameMatch(("lime",), "fuzzy")


def test_a_real_key_is_never_fuzzy_matched(pack):
    # "pea" and "pear" are both keys and one edit apart.
    assert step(pack, "pea") == (("pea",), "exact")
    assert step(pack, "peas") == (("pea",), "exact")
    assert step(pack, "pear") == (("pear",), "exact")
    assert step(pack, "diced peas") == (("pea",), "contained")


def test_short_names_are_never_fuzzy():
    keys = {"ice": "ice", "rye": "rye"}
    assert resolve_name("ace", keys, DEFAULT_WORDS) == NameMatch((), "none")
    assert resolve_name("2 cups ace", keys, DEFAULT_WORDS) == NameMatch((), "none")
    assert resolve_name("ice", keys, DEFAULT_WORDS) == NameMatch(("ice",), "exact")


def test_nothing_resolves_from_empty_or_unit_only_text(pack):
    for text in ("", "   ", "boneless", "2 cups", "1/0 cup"):
        assert step(pack, text) == ((), "none"), text
    assert step(pack, "constructor") == ((), "none")
    assert step(pack, "__proto__") == ((), "none")


def test_unicode_names(pack):
    assert step(pack, "ＦＬＯＵＲ") == (("flour",), "exact")  # full-width letters
    assert step(pack, "ﬂour") == (("flour",), "exact")  # ligature
    assert step(pack, "ÉGG") == (("egg",), "exact")
    assert step(pack, "flour，sugar") == (("flour", "sugar"), "split")  # full-width comma
    assert step(pack, "flour ＆ sugar") == (("flour", "sugar"), "split")
    assert step(pack, "chicken thighs") == (("chicken_thigh",), "exact")


def test_resolve_names_collects_ids_in_order_and_unknowns(pack):
    ids, unknown = resolve_names(pack, ["s&p", "cinamon", "xylophone", "salt", "pepper"])
    assert ids == ["salt", "black_pepper", "cinnamon"]
    assert unknown == ["xylophone", "pepper"]


def test_real_table_keeps_bare_pepper_unknown():
    table = IngredientTable.load()
    keys = {" ".join(k): i for k, i in table.keys.items()}
    assert resolve_name("pepper", keys, table.words) == NameMatch((), "none")


def test_pack_without_words_still_resolves_exact_names():
    core = json.loads((FIXTURE / "core.v1.json").read_text(encoding="utf8"))
    del core["words"]
    pack = Pack.from_core(core)
    assert resolve_names(pack, ["flour", "Eggs", "2 cups milk"]) == (
        ["flour", "egg"],
        ["2 cups milk"],
    )


def test_a_lone_unit_word_is_never_fuzzy_matched():
    # "pint" is one edit from "mint" and "dash" is one from "dashi". Neither is a food here.
    keys = {"mint": "mint", "dashi": "dashi", "clove": "clove"}
    for text in ("pint", "2 pints", "dash", "2 dashes", "1 dash"):
        assert resolve_name(text, keys, DEFAULT_WORDS) == NameMatch((), "none"), text
    # A lone unit word still reaches the exact and contained steps.
    assert resolve_name("2 cloves", keys, DEFAULT_WORDS) == NameMatch(("clove",), "contained")
    assert resolve_name("2 pints mint", keys, DEFAULT_WORDS) == NameMatch(("mint",), "contained")


def test_blank_characters_of_either_language_are_one_space(pack):
    for blank in ("\ufeff", "\x85", "\x1c", "\x1f", "\u2028", "\u3000"):
        assert step(pack, f"2{blank}cups{blank}milk") == (("milk",), "contained"), repr(blank)
        assert step(pack, f"flour{blank}and{blank}sugar") == (("flour", "sugar"), "split")
        assert step(pack, f"{blank}flour{blank}") == (("flour",), "exact")
