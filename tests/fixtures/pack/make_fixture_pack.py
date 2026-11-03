"""Write ``core.v1.json``: a small synthetic pack for engine and parity tests.

The recipes are invented for this repo (MIT). They hold no Wikibooks text and no data from
RecipeNLG or Open Recipes. Each recipe is a list of line specs:

    "flour"            required line, one option
    "butter|margarine" required line with alternatives ("or" line)
    "~parsley"         optional line
    "?mystery thing"   unread line (no ids)
    "salt"             a staple line

Run:  uv run python tests/fixtures/pack/make_fixture_pack.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

STAPLES = {"water", "salt", "black_pepper", "vegetable_oil"}
INGREDIENTS = [
    "water",
    "salt",
    "black_pepper",
    "vegetable_oil",
    "flour",
    "sugar",
    "butter",
    "margarine",
    "egg",
    "milk",
    "onion",
    "garlic",
    "tomato",
    "pasta",
    "cheese",
    "rice",
    "chicken",
    "potato",
    "parsley",
    "basil",
    "lemon",
    "honey",
    "oats",
    "banana",
    "yeast",
    "bread",
    "beef",
    "carrot",
    "celery",
    "olive_oil",
]

RECIPES: dict[str, list[str]] = {
    "Pancakes": ["flour", "egg", "milk", "sugar", "butter", "salt"],
    "Omelette": ["egg", "milk", "salt", "~parsley"],
    "Plain Bread": ["flour", "yeast", "water", "salt"],
    "Butter Cookies": ["flour", "sugar", "butter|margarine", "egg"],
    "Margarine Cake": ["flour", "sugar", "margarine", "egg", "milk"],
    "Tomato Pasta": ["pasta", "tomato", "garlic", "olive_oil", "~basil", "salt"],
    "Garlic Pasta": ["pasta", "garlic", "vegetable_oil|olive_oil", "~parsley"],
    "Cheese Pasta": ["pasta", "cheese", "butter", "black_pepper"],
    "Fried Rice": ["rice", "egg", "onion", "carrot", "vegetable_oil", "salt"],
    "Chicken Rice": ["chicken", "rice", "onion", "garlic", "salt"],
    "Roast Chicken": ["chicken", "lemon", "garlic", "butter", "salt", "black_pepper"],
    "Mashed Potato": ["potato", "butter", "milk", "salt"],
    "Potato Soup": ["potato", "onion", "celery", "milk", "butter"],
    "Potato Omelette": ["potato", "egg", "onion", "olive_oil"],
    "Beef Stew": ["beef", "potato", "carrot", "onion", "celery", "water", "salt"],
    "Beef Rice": ["beef", "rice", "onion"],
    "Banana Pancakes": ["banana", "flour", "egg", "milk"],
    "Banana Oats": ["banana", "oats", "milk", "honey"],
    "Honey Oats": ["oats", "honey", "milk"],
    "Lemon Cake": ["flour", "sugar", "lemon", "egg", "butter"],
    "Lemonade": ["lemon", "sugar", "water"],
    "Garlic Bread": ["bread", "garlic", "butter", "~parsley"],
    "Cheese Toast": ["bread", "cheese"],
    "Egg Toast": ["bread", "egg", "butter"],
    "Tomato Salad": ["tomato", "onion", "olive_oil", "~basil", "salt"],
    "Tomato Soup": ["tomato", "onion", "garlic", "butter|olive_oil", "water", "salt"],
    "Mystery Stew": ["beef", "?secret spice mix", "onion", "carrot"],
    "Mystery Cake": ["flour", "sugar", "?special glaze", "egg"],
    "Carrot Soup": ["carrot", "onion", "water", "salt", "?bouillon of some kind"],
    "Cheese Omelette": ["egg", "cheese", "milk", "butter"],
    "Cheese Sauce": ["cheese", "milk", "butter", "flour"],
    "Rice Pudding": ["rice", "milk", "sugar", "~lemon"],
    "Oat Cookies": ["oats", "flour", "sugar", "butter", "egg"],
    "Honey Bread": ["flour", "yeast", "honey", "water", "salt"],
    "Plain Pasta": ["pasta", "salt", "water"],
    "Flour Paste": ["flour", "water"],
    "Salt Dough": ["flour", "water", "salt", "vegetable_oil"],
    "Basil Chicken": ["chicken", "basil", "garlic", "olive_oil", "~lemon"],
    "Celery Salad": ["celery", "carrot", "lemon|honey", "olive_oil"],
    "Carrot Cake": ["carrot", "flour", "sugar", "egg", "vegetable_oil"],
    "Onion Rings": ["onion", "flour", "egg", "milk", "vegetable_oil"],
    "Chicken Soup": ["chicken", "carrot", "celery", "onion", "water", "salt"],
    "Garlic Potatoes": ["potato", "garlic", "butter|margarine|olive_oil", "~parsley"],
    "Egg Fried Potato": ["potato", "egg", "vegetable_oil", "salt"],
    "Parsley Butter": ["butter", "parsley", "garlic"],
    "Simple Rice": ["rice", "water", "salt"],
    "Buttered Rice": ["rice", "butter"],
}


def build() -> dict:
    known = set(INGREDIENTS)
    recipes = []
    for i, (title, specs) in enumerate(RECIPES.items(), start=1):
        lines = []
        for spec in specs:
            opt = spec.startswith("~")
            unread = spec.startswith("?")
            body = spec.lstrip("~?")
            options = [] if unread else [o for o in body.split("|") if o in known]
            lines.append({"t": body, "o": options, "opt": opt, "r": not unread})
        recipes.append(
            {
                "id": f"fx-{i:03d}",
                "title": title,
                "page": f"Cookbook:{title}",
                "rev": 1000 + i,
                "lines": lines,
            }
        )
    df: dict[str, int] = {}
    for r in recipes:
        for ing in {o for ln in r["lines"] for o in ln["o"]}:
            df[ing] = df.get(ing, 0) + 1
    n = len(recipes)
    return {
        "format": 1,
        "info": {
            "version": "fixture",
            "commit": "fixture",
            "corpus_fingerprint": "fixture",
            "recipes": n,
        },
        "ingredients": [
            {
                "id": i,
                "name": i.replace("_", " "),
                "staple": i in STAPLES,
                "idf": math.log(1 + n / df[i]) if i in df else 0.0,
            }
            for i in INGREDIENTS
        ],
        "keys": {i.replace("_", " "): i for i in INGREDIENTS},
        "recipes": recipes,
    }


def build_text(core: dict) -> dict:
    """Invented steps and placeholder attribution. The links are placeholders for tests only."""
    recipes = {}
    for r in core["recipes"]:
        slug = r["title"].replace(" ", "_")
        recipes[r["id"]] = {
            "steps": [f"Prepare the ingredients for {r['title']}.", "Combine them and cook."],
            "servings": None,
            "time": None,
            "category": "Fixture recipes",
            "url": f"https://en.wikibooks.org/wiki/Cookbook:{slug}",
            "revision_url": f"https://en.wikibooks.org/w/index.php?oldid={r['rev']}",
            "revision_id": r["rev"],
            "licence": "Synthetic test fixture (MIT)",
            "retrieved_on": "2026-11-02",
            "changes": "Invented for tests. Not a Wikibooks page.",
        }
    return {"format": 1, "recipes": recipes}


if __name__ == "__main__":
    here = Path(__file__).parent
    core = build()
    for name, obj in (("core.v1.json", core), ("text.v1.json", build_text(core))):
        with open(here / name, "w", encoding="utf8", newline="\n") as fh:
            fh.write(json.dumps(obj, indent=1) + "\n")
        print(f"wrote {here / name}")
