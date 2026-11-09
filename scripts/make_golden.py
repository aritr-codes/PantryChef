"""Write the golden parity file: ``answer()`` on about 200 fixed pantries.

The Python engine is the reference. The TypeScript engine must give the same groups, the same
order and scores within 1e-9 (ADR 0004). The input is the synthetic fixture pack, so the file
holds no Wikibooks text. CI regenerates this file and fails if it differs from the commit.

Run:  uv run python scripts/make_golden.py
"""

from __future__ import annotations

import importlib.util
import json
import random
from dataclasses import asdict
from pathlib import Path

from pantrychef.engine import AnswerRequest, Pack, answer, load_pack, resolve_names
from pantrychef.ingredients.names import resolve_name
from pantrychef.ingredients.table import tokens

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "pack"
OUT = ROOT / "tests" / "golden" / "answer_cases.json"
SEED = 20261102


def _fixture_module():
    path = FIXTURE / "make_fixture_pack.py"
    spec = importlib.util.spec_from_file_location("make_fixture_pack", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The fixture pack ends with rows that only the name cases use. The answer cases sample the rest,
# so adding a name row never changes an answer case.
ANSWER_INGREDIENTS = len(_fixture_module().INGREDIENTS)

TOKEN_INPUTS = [
    "Eggs",
    "egg",
    "  BUTTER ",
    "all-purpose flour",
    "jalapeño",
    "crème fraîche",
    "Half & Half",
    "2% milk",
    "tomatoes",
    "molasses",
    "asparagus",
    "bay leaves",
    "berries",
    "boxes",
    "glass",
    "olive oil (extra virgin)",
    "Jalapeño Peppers",
    "1⁄2 cup",
    "ﬂour",
    "ＦＵＬＬ width",
    "wishes",
    "potatoes",
    "couscous",
    "hummus",
    "citrus",
    "octopus",
    "swiss",
    "chilies",
    "knives",
    "cheeses",
    "halves",
    "loaves",
    "chilis",
    "chillis",
    "zucchinis",
    "tennis",
    "",
]
NAME_LISTS = [
    ["flour", "Eggs", "milk", "xylophone"],
    ["olive oil", "Olive Oil", "garlic", "GARLIC"],
    ["tomatoes", "onions", "potato"],
    ["", "  ", "salt"],
]


# Dev or invented typed names only. The Unicode and quantity cases are the ones that Python and
# TypeScript could disagree on.
# fmt: off
NAME_CASES = [
    # exact
    "flour", "Flour", "  EGGS ", "olive oil", "Olive-Oil", "half and half", "Half & Half",
    "black pepper", "chicken thighs", "Ground Beef", "peas", "pear", "pea",
    # contained
    "chicken thighs, boneless", "lean ground beef", "boneless chicken thighs", "2 large eggs",
    "onion, chopped", "chopped fresh parsley", "diced onion", "chopped lean ground beef",
    "ground beef, browned",
    # quantity and unit
    "2 cups milk", "½ cup milk", "1⁄2 cup milk", "1 1/2 cups milk", "1/2 cup milk",
    "1½ cups milk", "2-3 cloves", "2–3 cloves", "2 to 3 cloves", "2 (8 oz) cans tomatoes",
    "1 tbsp olive oil", "1.5 oz butter", "3 eggs", "1/0 cup milk", "٣ cups milk", "１ cup milk",
    "2 cups", "cloves",
    # split
    "s&p", "S & P", "salt and p", "flour and sugar", "flour/sugar", "flour, sugar",
    "milk, eggs, butter", "flour, flour", "egg & milk", "flour, sugar, ", "tomato / onion",
    "flour and xylophone",
    # fuzzy
    "cinamon", "gralic", "chiken", "tomatoe", "buter", "margerine", "ground cinamon",
    "2 cups cinamon", "diced tomatoe", "parsly", "peaz", "cinnamom", "oliv oil",
    # none
    "pepper", "salt and pepper", "xylophone", "ace", "boneless", "", "   ", "constructor",
    "__proto__", "toString", "flour tortilla wrap",
    # Unicode
    "ＦＬＯＵＲ", "ﬂour", "ÉGG", "flour，sugar", "flour ＆ sugar", "chicken\u00a0thighs",
    "crème fraîche", "jalapeño", "Ｃｉｎａｍｏｎ", "cinnamon\ufeff",
    # lone unit words never reach the fuzzy step
    "pint", "2 pints", "dash", "2 dashes", "1 dash", "2 cloves", "2 pints mint",
    # white space that only one language counts
    "2\ufeffcups\ufeffmilk", "2\x85cups\x85milk", "flour\x85and\x85sugar", "\x1cflour\x1f",
    "flour\ufeff,\ufeffsugar", "1\x851/2\x85cups milk",
]
# fmt: on


def _edge_cases(pack: Pack) -> list[tuple[str, AnswerRequest]]:
    d = pack.default_staples
    return [
        ("empty pantry", AnswerRequest([], d)),
        ("only staples", AnswerRequest(["salt", "water"], d)),
        ("unknown id", AnswerRequest(["flour", "egg", "nope"], d, unknown_names=["typo"])),
        ("limit zero", AnswerRequest(["flour", "egg", "milk"], d, limit=0)),
        ("no staples", AnswerRequest(["flour", "water"], [])),
        ("flour is a staple", AnswerRequest(["egg", "milk"], [*d, "flour"])),
        ("everything", AnswerRequest(list(pack.ingredients)[:ANSWER_INGREDIENTS], d, limit=50)),
        ("one item", AnswerRequest(["honey"], d)),
        ("tie on score and total", AnswerRequest(["rice", "butter"], d, limit=50)),
        ("or line", AnswerRequest(["margarine", "flour", "sugar", "egg"], d)),
        ("blocker case", AnswerRequest(["honey"], [], limit=3)),
        ("unread lines", AnswerRequest(["beef", "onion", "carrot"], d)),
    ]


def build() -> dict:
    pack = load_pack(FIXTURE)
    ids = list(pack.ingredients)[:ANSWER_INGREDIENTS]
    rng = random.Random(SEED)
    cases = [(name, req) for name, req in _edge_cases(pack)]
    staple_sets = [pack.default_staples, [], [*pack.default_staples, "flour"]]
    for n in range(190):
        k = rng.randint(0, 8)
        pantry = rng.sample(ids, k)
        cases.append(
            (
                f"random {n:03d}",
                AnswerRequest(pantry, list(rng.choice(staple_sets)), limit=rng.choice([3, 10, 25])),
            )
        )
    return {
        "seed": SEED,
        "pack": "tests/fixtures/pack/core.v1.json",
        "cases": [
            {
                "name": name,
                "request": {
                    "pantry": req.pantry,
                    "staples": req.staples,
                    "diet": None,
                    "limit": req.limit,
                    "unknown_names": req.unknown_names,
                },
                "answer": asdict(answer(pack, req)),
            }
            for name, req in cases
        ],
        "tokens": [{"input": t, "tokens": list(tokens(t))} for t in TOKEN_INPUTS],
        "names": [
            {"names": names, "ids": ids_, "unknown": unk}
            for names in NAME_LISTS
            for ids_, unk in [resolve_names(pack, names)]
        ],
        "resolve": [
            {"text": text, "ids": list(m.ids), "step": m.step}
            for text in NAME_CASES
            for m in [resolve_name(text, pack.keys, pack.words)]
        ],
    }


def render() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf8", newline="\n") as fh:
        fh.write(render())
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
