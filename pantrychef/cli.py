"""Command-line entrypoint.

`pantrychef cook --have eggs,flour,milk` shows what you can make now, what is one item
away, and the items that unlock the most recipes. It reads a recipe pack built by
`scripts/build_pack.py`.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from zipfile import BadZipFile

from pantrychef import __version__
from pantrychef.config import get_settings
from pantrychef.engine import AnswerRequest, answer, load_pack, resolve_names

DEFAULT_PACK_DIR = "build/pack"
_TITLES = {"make_now": "MAKE NOW", "one_away": "ONE ITEM AWAY", "two_away": "TWO ITEMS AWAY"}


def cook_command(have: str, k: int, pack_dir: str | None = None, staples: str | None = None) -> int:
    folder = Path(pack_dir or DEFAULT_PACK_DIR)
    try:
        pack = load_pack(folder)
    except FileNotFoundError:
        print(f"Recipe pack not found in {folder}. Run `uv run python scripts/build_pack.py`.")
        return 1
    names = [p.strip() for p in have.split(",") if p.strip()]
    ids, unknown = resolve_names(pack, names)
    if staples is None:
        staple_ids = pack.default_staples
    else:
        staple_ids, _ = resolve_names(pack, [p.strip() for p in staples.split(",") if p.strip()])
    ans = answer(pack, AnswerRequest(ids, staple_ids, limit=max(k, 0), unknown_names=unknown))
    if unknown:
        print(f"Not recognised (not used): {', '.join(unknown)}")
    shown = False
    for key, group in ans.groups.items():
        if key == "two_away" and ans.groups["make_now"].count + ans.groups["one_away"].count >= 5:
            continue
        if not group.count:
            continue
        shown = True
        print(f"{_TITLES[key]} ({group.count})")
        for r in group.items:
            miss = ", ".join(
                "/".join(m.options) if m.options else "check this line" for m in r.missing
            )
            tail = f"  missing: {miss}" if miss else ""
            print(f"  {r.title}  (you have {r.have} of {r.total}){tail}")
    if ans.unlocks:
        print("Top unlocks:")
        for u in ans.unlocks[:5]:
            print(f"  Add {u.name} to move {u.recipes} recipes to make now")
    if not shown:
        print("No matching recipes.")
        for b in ans.blockers[:3]:
            print(f"  Add {b.name} to get {b.recipes} recipes")
    return 0


def substitute_command(
    ingredient: str,
    diet: str | None,
    k: int,
    model_path: str | None = None,
    recipe: str | None = None,
) -> int:
    """Find ingredient substitutes using the persisted substitution bundle."""
    from pantrychef.substitution.bundle import DEFAULT_BUNDLE_NAME
    from pantrychef.substitution.train import Artifacts

    s = get_settings()
    mpath = Path(model_path or (s.models_dir / "substitution" / DEFAULT_BUNDLE_NAME))
    if not mpath.exists():
        print(f"Substitution bundle not found at {mpath}. Run scripts/train_substitution.py first.")
        return 1
    try:
        art = Artifacts.load_bundle(mpath)
    except (BadZipFile, OSError, ValueError) as exc:
        print(f"Failed to load substitution bundle at {mpath}: {exc}")
        return 1

    sub = art.substitutor(cfg=replace(art.cfg, k=k))
    ctx = [c.strip() for c in recipe.split(",") if c.strip()] if recipe else None
    results = sub.substitutes(ingredient, diet=diet, recipe=ctx, k=max(k, 0))
    if not results:
        print(f"No substitutes found for '{ingredient}'" + (f" ({diet})" if diet else "") + ".")
        return 0
    for r in results:
        print(f"[{r.score:6.3f}] {r.ingredient}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pantrychef", description="Pantry-aware recipe finder.")
    parser.add_argument("--version", action="version", version=f"pantrychef {__version__}")
    sub = parser.add_subparsers(dest="command")

    cook = sub.add_parser("cook", help="Find recipes you can make.")
    cook.add_argument("--have", required=True, help="Comma-separated pantry ingredients.")
    cook.add_argument("--k", type=int, default=5, help="How many recipes to show per group.")
    cook.add_argument(
        "--pack", default=None, help="Folder with core.v2.json.gz (default build/pack)."
    )
    cook.add_argument(
        "--staples", default=None, help="Comma-separated staples (default: the pack's)."
    )

    sub_p = sub.add_parser("substitute", help="Find ingredient substitutes.")
    sub_p.add_argument("ingredient", help="Ingredient to replace.")
    sub_p.add_argument(
        "--diet", default=None, choices=["vegan", "vegetarian", "gluten_free", "dairy_free"]
    )
    sub_p.add_argument("--k", type=int, default=5)
    sub_p.add_argument(
        "--in-recipe", dest="recipe", default=None, help="Comma-separated recipe context."
    )
    sub_p.add_argument("--model", default=None, help="Path to substitution bundle.")

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "cook":
        return cook_command(have=args.have, k=args.k, pack_dir=args.pack, staples=args.staples)

    if args.command == "substitute":
        return substitute_command(
            ingredient=args.ingredient,
            diet=args.diet,
            k=args.k,
            model_path=args.model,
            recipe=args.recipe,
        )

    print(f"PantryChef v{__version__}. Try: pantrychef cook --have eggs,flour,milk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
