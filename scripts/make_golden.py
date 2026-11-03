"""Write the golden parity file: ``answer()`` on about 200 fixed pantries.

The Python engine is the reference. The TypeScript engine must give the same groups, the same
order and scores within 1e-9 (ADR 0004). The input is the synthetic fixture pack, so the file
holds no Wikibooks text. CI regenerates this file and fails if it differs from the commit.

Run:  uv run python scripts/make_golden.py
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict
from pathlib import Path

from pantrychef.engine import AnswerRequest, Pack, answer, load_pack, resolve_names
from pantrychef.ingredients.table import tokens

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "pack"
OUT = ROOT / "tests" / "golden" / "answer_cases.json"
SEED = 20261102

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
    "",
]
NAME_LISTS = [
    ["flour", "Eggs", "milk", "xylophone"],
    ["olive oil", "Olive Oil", "garlic", "GARLIC"],
    ["tomatoes", "onions", "potato"],
    ["", "  ", "salt"],
]


def _edge_cases(pack: Pack) -> list[tuple[str, AnswerRequest]]:
    d = pack.default_staples
    return [
        ("empty pantry", AnswerRequest([], d)),
        ("only staples", AnswerRequest(["salt", "water"], d)),
        ("unknown id", AnswerRequest(["flour", "egg", "nope"], d, unknown_names=["typo"])),
        ("limit zero", AnswerRequest(["flour", "egg", "milk"], d, limit=0)),
        ("no staples", AnswerRequest(["flour", "water"], [])),
        ("flour is a staple", AnswerRequest(["egg", "milk"], [*d, "flour"])),
        ("everything", AnswerRequest(list(pack.ingredients), d, limit=50)),
        ("one item", AnswerRequest(["honey"], d)),
        ("tie on score and total", AnswerRequest(["rice", "butter"], d, limit=50)),
        ("or line", AnswerRequest(["margarine", "flour", "sugar", "egg"], d)),
        ("blocker case", AnswerRequest(["honey"], [], limit=3)),
        ("unread lines", AnswerRequest(["beef", "onion", "carrot"], d)),
    ]


def build() -> dict:
    pack = load_pack(FIXTURE)
    ids = list(pack.ingredients)
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
