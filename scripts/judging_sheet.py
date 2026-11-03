"""Build the blind 20-pantry judging pilot. See docs/JUDGING_PROTOCOL.md.

    uv run python scripts/judging_sheet.py [--pack build/pack] [--seed 42]

Writes data/eval/judging/pilot_sheet.v1.json (what the judge sees, no arm names), the private key
data/interim/judging_key.pilot.v1.json (git ignores it) and data/eval/judging/pilot_key_sha256.txt
(committed, so the key cannot change later). Do not open the key before you answer every item.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

from pantrychef.engine import Pack, _needed, load_pack
from pantrychef.eval.arms import CandidateIndex, order
from pantrychef.eval.pantries import build_pantries

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "data/eval/judging/pilot_sheet.v1.json"
KEY = ROOT / "data/interim/judging_key.pilot.v1.json"
KEY_SHA = ROOT / "data/eval/judging/pilot_key_sha256.txt"
ARM_LEFT_RIGHT = ("shipped", "overlap")
TOP = 5
MIN_GAP = 3  # a repeat sits at least this many places from its original


def _hash(seed: int, gold_id: str) -> str:
    return hashlib.sha256(f"{seed}:judge:{gold_id}".encode()).hexdigest()


def _view(pack: Pack, by_id: dict, ranked: list, held: set[str], staples: set[str]) -> list[dict]:
    out = []
    for c in ranked:
        recipe = by_id[c.recipe_id]
        missing = [
            ln.text for ln in _needed(recipe, staples) if not any(o in held for o in ln.options)
        ]
        out.append({"title": recipe.title, "missing": missing})
    return out


def build_sheet(
    pack: Pack, seed: int = 42, n: int = 20, repeats: int = 4, d: int = 3
) -> tuple[dict, dict]:
    """Return (sheet, key). ``n`` base pantries from the test split, plus ``repeats`` repeats."""
    staples = set(pack.default_staples)
    index = CandidateIndex(pack, staples)
    by_id = {r.recipe_id: r for r in pack.recipes}
    pool = []
    for p in build_pantries(pack, "popularity", d, seed):
        if p.split != "test" or p.draw != 0:
            continue
        cands = index.candidates(set(p.pantry))
        tops = {a: order(a, cands)[:TOP] for a in ARM_LEFT_RIGHT}
        ids = {a: [c.recipe_id for c in t] for a, t in tops.items()}
        # Identical lists cannot be compared, so they carry no information.
        if all(len(v) == TOP for v in ids.values()) and ids["shipped"] != ids["overlap"]:
            pool.append((p, tops))
    if len(pool) < n:
        raise ValueError(f"only {len(pool)} usable test pantries, need {n}")
    pool.sort(key=lambda x: _hash(seed, x[0].gold_id))
    base = pool[:n]

    rng = random.Random(f"{seed}:judging")
    repeated = set(rng.sample(range(n), repeats))
    # entry: (base index, is_repeat, swap sides)
    entries = [(i, False, rng.random() < 0.5) for i in range(n)]
    entries += [(i, True, rng.random() < 0.5) for i in sorted(repeated)]
    for _ in range(10_000):
        rng.shuffle(entries)
        pos = {(i, rep): k for k, (i, rep, _) in enumerate(entries)}
        if all(abs(pos[(i, True)] - pos[(i, False)]) >= MIN_GAP for i in repeated):
            break
    else:
        raise ValueError("could not place repeats apart")

    names = {i: ing.name for i, ing in pack.ingredients.items()}
    item_id = {(i, rep): f"item{k + 1:02d}" for k, (i, rep, _) in enumerate(entries)}
    items, key_items = [], {}
    for (i, rep, swap), iid in zip(entries, (item_id[(e[0], e[1])] for e in entries), strict=True):
        p, tops = base[i]
        held = {x for x in p.pantry if x in pack.ingredients} - staples
        left_arm, right_arm = ARM_LEFT_RIGHT[::-1] if swap else ARM_LEFT_RIGHT
        items.append(
            {
                "item_id": iid,
                "pantry": sorted(names[x] for x in p.pantry),
                "left": _view(pack, by_id, tops[left_arm], held, staples),
                "right": _view(pack, by_id, tops[right_arm], held, staples),
            }
        )
        key_items[iid] = {
            "gold_id": p.gold_id,
            "left": left_arm,
            "right": right_arm,
            "repeat_of": item_id[(i, False)] if rep else None,
        }
    sheet = {"version": 1, "items": items}
    return sheet, {"version": 1, "seed": seed, "d": d, "items": key_items}


def write_outputs(sheet: dict, key: dict, sheet_path: Path, key_path: Path, sha_path: Path) -> str:
    """Write the three files. Refuse to change a key that already has a committed hash."""
    key_bytes = (json.dumps(key, indent=2, sort_keys=True) + "\n").encode("utf-8")
    digest = hashlib.sha256(key_bytes).hexdigest()
    if sha_path.exists() and sha_path.read_text().strip() != digest:
        raise SystemExit(f"key hash differs from {sha_path}. The key must not change. Stop.")
    for p in (sheet_path, key_path, sha_path):
        p.parent.mkdir(parents=True, exist_ok=True)
    sheet_path.write_bytes((json.dumps(sheet, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    key_path.write_bytes(key_bytes)
    sha_path.write_text(digest + "\n")
    return digest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="build/pack")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)
    sheet, key = build_sheet(load_pack(args.pack), seed=args.seed)
    digest = write_outputs(sheet, key, SHEET, KEY, KEY_SHA)
    print(f"{len(sheet['items'])} items. Key sha256 {digest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
