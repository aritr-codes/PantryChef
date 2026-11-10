"""Resolver rules F1 to F7 (M3 Task 11). Invented table and invented lines only.

Each rule has a line that fails without it and a guard line that stays as it was.
"""

from __future__ import annotations

import pytest

from pantrychef.ingredients.resolve import resolve_lines
from pantrychef.ingredients.table import IngredientTable

ROWS = (
    "id,name,synonyms,staple,provenance\n"
    "salt,salt,,1,hand\n"
    "water,water,,1,hand\n"
    "black_pepper,black pepper,,1,hand\n"
    "garlic,garlic,,0,hand\n"
    "onion,onion,,0,hand\n"
    "carrot,carrot,,0,hand\n"
    "vinegar,vinegar,,0,hand\n"
    "egg,egg,,0,hand\n"
    "lemon,lemon,,0,hand\n"
    "ginger,ginger,,0,hand\n"
    "milk,milk,,0,hand\n"
    "parsley,parsley,,0,hand\n"
    "flour,flour,,0,hand\n"
    "wine,wine,,0,hand\n"
    "dry_marsala,dry marsala,,0,hand\n"
    "marsala_wine,marsala wine,,0,hand\n"
    "dry_sherry,dry sherry,,0,hand\n"
    "mango_powder,mango powder,amchur,0,hand\n"
    "pomegranate,pomegranate,,0,hand\n"
    "mustard,mustard,,0,hand\n"
    "mustard_powder,mustard powder,,0,hand\n"
    "chili_pepper,chili pepper,chile|chili|chile pepper,0,hand\n"
    "chili_powder,chili powder,chile pepper powder,0,hand\n"
    "ground_beef,ground beef,,0,hand\n"
    "powdered_sugar,powdered sugar,,0,hand\n"
    "sugar,sugar,,0,hand\n"
    "cinnamon,cinnamon,,0,hand\n"
)


@pytest.fixture(scope="module")
def t() -> IngredientTable:
    return IngredientTable.from_text(ROWS)


def _ids(t, text):
    return [(ln.options, ln.read) for ln in resolve_lines(text, t)]


# --- F1: an unknown "and" part in a later comma chunk is skipped ---


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("2 carrots, peeled and cut into pieces", [(("carrot",), True)]),
        ("1 onion, white and green parts", [(("onion",), True)]),
        (
            "salt, garlic and zzzherbs",
            [(("salt",), True), (("garlic",), True)],
        ),
        (
            "salt, black pepper and vinegar, and zzzherbs",
            [(("salt",), True), (("black_pepper",), True), (("vinegar",), True)],
        ),
    ],
)
def test_f1_later_chunk_unknown_and_part_is_skipped(t, text, want):
    assert _ids(t, text) == want


@pytest.mark.parametrize(
    "text",
    [
        "salt and zzzherbs",  # first chunk stays strict
        "2 cups flour and zzzfruit",
        "zzzfruit, garlic and onion peeled",  # the first part is unknown
        "garlic and zzzherbs, carrot",  # the first chunk holds the unknown "and" part
    ],
)
def test_f1_first_chunk_unknown_and_part_still_unread(t, text):
    assert _ids(t, text) == [((), False)]


def test_f1_skipped_part_does_not_hide_a_known_one(t):
    assert _ids(t, "2 eggs, garlic and onion") == [
        (("egg",), True),
        (("garlic",), True),
        (("onion",), True),
    ]


# --- F2: inside one "or" part, matches after "with" are dropped when one comes before ---


def test_f2_match_after_with_is_dropped(t):
    assert _ids(t, "egg with ginger or lemon") == [(("egg", "lemon"), True)]
    assert _ids(t, "1 egg with ginger") == [(("egg",), True)]


def test_f2_guards(t):
    assert _ids(t, "with ginger") == [(("ginger",), True)]  # nothing before "with"
    assert _ids(t, "egg in ginger") == [(("ginger",), True)]  # only "with" starts a note
    assert _ids(t, "cinnamon or ginger") == [(("cinnamon", "ginger"), True)]


# --- F3: two adjacent spans overlap a longer key ---


def test_f3_merged_key_wins(t):
    assert _ids(t, "1/2 cup dry marsala wine") == [(("marsala_wine",), True)]


def test_f3_guards(t):
    assert _ids(t, "1/2 cup dry marsala") == [(("dry_marsala",), True)]
    # no "sherry wine" key, so the head noun stays "wine"
    assert _ids(t, "1/2 cup dry sherry wine") == [(("wine",), True)]
    assert _ids(t, "dry marsala and wine") == [(("dry_marsala",), True), (("wine",), True)]


# --- F4: a trailing word that is in the row name is explained ---


def test_f4_repeated_row_word_is_explained(t):
    assert _ids(t, "1 tsp amchur powder") == [(("mango_powder",), True)]


def test_f4_guards(t):
    assert _ids(t, "1 tsp amchur paste") == [((), False)]
    assert _ids(t, "1 tsp pomegranate powder") == [((), False)]


# --- F5: a line that reads nothing is tried once with the parentheses opened ---


def test_f5_unread_line_retried_with_parentheses_opened(t):
    assert _ids(t, "1 cup (mixed with ginger)") == [(("ginger",), True)]
    assert _ids(t, "(lemon)") == [(("lemon",), True)]


def test_f5_guards(t):
    assert _ids(t, "2 eggs (or lemon)") == [(("egg",), True)]  # already read: unchanged
    assert _ids(t, "3 cups zzzfruit (see note)") == [((), False)]
    assert _ids(t, "(optional)") == [((), False)]


# --- F6: "powdered" or "ground" before a food reads "<food> powder" when that key exists ---


@pytest.mark.parametrize(
    "text", ["1 tsp powdered mustard", "1 tsp ground mustard", "1 tsp ground chile pepper"]
)
def test_f6_form_word_reads_the_powder_row(t, text):
    want = "chili_powder" if "chile" in text else "mustard_powder"
    assert _ids(t, text) == [((want,), True)]


def test_f6_guards(t):
    assert _ids(t, "1 tsp ground ginger") == [(("ginger",), True)]  # no "ginger powder" key
    assert _ids(t, "1 lb ground beef") == [(("ground_beef",), True)]  # a key starts at "ground"
    assert _ids(t, "1 cup powdered sugar") == [(("powdered_sugar",), True)]
    assert _ids(t, "1 tsp mustard") == [(("mustard",), True)]


# --- F7: in a later comma chunk, matches after a clause word are dropped ---


def test_f7_note_chunk_after_clause_word_is_dropped(t):
    assert _ids(t, "2 cups garlic, made with onion") == [(("garlic",), True)]
    assert _ids(t, "2 cups garlic, cut into carrot sticks") == [(("garlic",), True)]
    assert _ids(t, "2 cups garlic, made with onion and parsley") == [(("garlic",), True)]


def test_f7_guards(t):
    # a match before the clause word stays
    assert _ids(t, "garlic, onion for frying") == [(("garlic",), True), (("onion",), True)]
    # the first chunk is not a note
    assert _ids(t, "garlic in onion") == [(("onion",), True)]
    # a chunk without a clause word is an ingredient
    assert _ids(t, "garlic, onion") == [(("garlic",), True), (("onion",), True)]
    # a clause word inside a matched key is not a clause word
    assert _ids(t, "garlic, black pepper") == [(("garlic",), True), (("black_pepper",), True)]
