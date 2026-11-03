"""Adapter tests on real pages (CC BY-SA, see tests/fixtures/wikibooks/NOTICE.md)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pantrychef.sources.wikibooks import clean_markup, parse_page

FIX = Path(__file__).parent / "fixtures" / "wikibooks" / "pages.json"
PAGES = {r["title"]: r for r in json.loads(FIX.read_text(encoding="utf8"))}


def _parse(title):
    return parse_page(PAGES[title], "2026-11-03")


def test_apple_cobbler_fields_and_provenance():
    r = _parse("Cookbook:Apple Cobbler")
    assert r.title == "Apple Cobbler"
    assert r.url == "https://en.wikibooks.org/wiki/Cookbook:Apple_Cobbler"
    assert r.revision_id == 4587240
    assert r.revision_url == "https://en.wikibooks.org/w/index.php?oldid=4587240"
    assert r.licence == "CC BY-SA 4.0" and r.retrieved_on == "2026-11-03"
    assert r.recipe_id == "wb-3283"
    assert r.category == "Recipes for dessert" and r.servings == "8"
    assert r.time == "Prep: 15 minutes; Baking: 20 minutes"
    assert len(r.ingredient_lines) == 10 and len(r.steps) == 8
    assert r.ingredient_lines[0] == "6 cups sliced, peeled, and cored baking apples"
    assert r.ingredient_lines[1] == "⅔ cup white granulated sugar"
    assert r.ingredient_lines[2] == "6 Tbsp water (divided into 4 and 2)"
    assert r.ingredient_lines[6] == "1 ½ tsp baking powder"


def test_spaced_headings_and_ref_tags_removed():
    r = _parse("Cookbook:Caesar Salad")
    assert r.ingredient_lines[0] == "1 head Romaine lettuce, roughly chopped"
    assert "Heavy pinch of sea salt" in r.ingredient_lines
    assert r.servings is None and r.category == "Salad recipes"
    assert len(r.steps) == 6


def test_multiline_summary_with_nested_link_and_image_line_skipped():
    r = _parse("Cookbook:Pesto I")
    assert r.category == "Sauce recipes" and r.time == "45 minutes"
    assert r.ingredient_lines[0] == "4 oz (100 g) fresh basil"
    assert all("Image" not in line and "jpeg" not in line for line in r.ingredient_lines)


def test_or_lines_kept_as_written():
    r = _parse("Cookbook:Atkins-Friendly Chocolate Mousse")
    assert r.ingredient_lines[0] == "1 cup (240 ml) or 1 part half and half"


def test_non_recipe_pages_return_none():
    assert _parse("Cookbook:Atkins Diet Cooking") is None
    assert _parse("Cookbook:Policy/Recipe template") is None


def test_url_is_https_wikibooks_and_encoded_for_accents():
    rec = {
        "title": "Cookbook:Crème Brûlée I",
        "page_id": 5,
        "revision_id": 9,
        "wikitext": "==Ingredients==\n*1 egg\n",
    }
    r = parse_page(rec, "d")
    assert r.url.startswith("https://en.wikibooks.org/wiki/Cookbook:Cr%C3%A8me")
    assert " " not in r.url


def test_redirect_returns_none():
    rec = {
        "title": "Cookbook:X",
        "page_id": 1,
        "revision_id": 2,
        "wikitext": "#REDIRECT [[Cookbook:Y]]\n==Ingredients==\n*1 egg",
    }
    assert parse_page(rec, "d") is None


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("[[Cookbook:Cup|cup]] of [[flour]]", "cup of flour"),
        ("'''bold''' and ''it''", "bold and it"),
        ("a&nbsp;b", "a b"),
        ("x<ref>note</ref> y", "x y"),
        ("{{see also|x}}text", "text"),
        ("[http://example.org site] link", "site link"),
    ],
)
def test_clean_markup(raw, want):
    assert clean_markup(raw) == want
