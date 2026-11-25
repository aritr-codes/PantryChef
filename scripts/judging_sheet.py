"""Build blind judging sheets. See docs/JUDGING_PROTOCOL.md and plan 2026-11-18, section 8.3.

Old M2 pilot (draws its own pantries; the defaults keep the committed key hash valid):

    uv run python scripts/judging_sheet.py [--pack build/pack] [--seed 42]

M4 sheets (pantries come from the committed pool file; neutral order and gold-out are on):

    uv run python scripts/judging_sheet.py --pantries data/eval/m4/pantries.v1.json \\
        --pool dev --take 100 --arms shipped overlap idf_flat --name dev [--repeats 4]

A sheet shows what the judge sees (no arm names). The private key goes to
``data/interim/judging_key.m4-NAME.v1.json`` (git ignores it) and its hash to
``data/eval/m4/key_sha256.NAME.txt`` (commit it before you answer). Do not open the key before you
answer every item.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path

from pantrychef.engine import Pack, _needed, load_pack
from pantrychef.eval.arms import CandidateIndex, Scored
from pantrychef.eval.m4_lists import (
    TOP,
    Orderers,
    excluded_ids,
    model_orderer,
    select_pantries,
    top_lists,
)
from pantrychef.eval.m4_pools import canonical
from pantrychef.eval.pairwise import FREEZE_REL, PANTRIES_REL, WEIGHTS_REL, freeze_problems
from pantrychef.eval.pantries import _group_key, build_pantries
from pantrychef.eval.results import commits
from pantrychef.rank import load_model

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "data/eval/judging/pilot_sheet.v1.json"
KEY = ROOT / "data/interim/judging_key.pilot.v1.json"
KEY_SHA = ROOT / "data/eval/judging/pilot_key_sha256.txt"
ARM_LEFT_RIGHT = ("shipped", "overlap")
MIN_GAP = 3  # a repeat sits at least this many places from its original
POOLS = ("pilot", "dev", "futility", "reserve", "test")
FREEZE = FREEZE_REL
TEMPLATE_COLUMNS = ["item_id", "choice", "strength", "would_cook_left", "would_cook_right",
                    "seconds", "session"]  # fmt: skip


def _hash(seed: int, gold_id: str) -> str:
    return hashlib.sha256(f"{seed}:judge:{gold_id}".encode()).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _view(
    pack: Pack, by_id: dict, ranked: list, held: set[str], staples: set[str], neutral: bool = False
) -> list[dict]:
    """The lines a judge sees. Neutral order: by case-folded title, then id (the arm picks the
    5 recipes, never their order on the sheet)."""
    if neutral:
        ranked = sorted(ranked, key=lambda c: (by_id[c.recipe_id].title.casefold(), c.recipe_id))
    out = []
    for c in ranked:
        recipe = by_id[c.recipe_id]
        missing = [
            ln.text for ln in _needed(recipe, staples) if not any(o in held for o in ln.options)
        ]
        out.append({"title": recipe.title, "missing": missing})
    return out


def _violations(entries: list[tuple], min_gap: int) -> list[int]:
    """Positions that sit closer than ``min_gap`` to another entry of the same pantry."""
    where: dict[int, list[int]] = {}
    for pos, e in enumerate(entries):
        where.setdefault(e[0], []).append(pos)
    bad: set[int] = set()
    for ps in where.values():
        for a, b in itertools.combinations(ps, 2):
            if abs(a - b) < min_gap:
                bad.update((a, b))
    return sorted(bad)


def _place(
    rng: random.Random, sizes: list[int], n_repeatable: int, repeats: int, min_gap: int
) -> list[tuple]:
    """Entries ``(pantry index, pair index, is_repeat, swap sides)`` in sheet order.

    ``sizes[i]`` is the number of pairs of pantry ``i``. Entries of one pantry sit at least
    ``min_gap`` places apart. The first ``n_repeatable`` units (pantry-major) may repeat.
    """
    units = [(i, j) for i, s in enumerate(sizes) for j in range(s)]
    repeated = rng.sample(range(n_repeatable), repeats)
    entries = [(i, j, False, rng.random() < 0.5) for i, j in units]
    entries += [(*units[u], True, rng.random() < 0.5) for u in sorted(repeated)]
    for _ in range(200):  # a plain shuffle works for a small sheet
        rng.shuffle(entries)
        if not _violations(entries, min_gap):
            return entries
    # ponytail: a big sheet (60 pantries x 3) almost never passes a plain shuffle, so repair it
    # with random swaps. 200_000 swaps is far above what it needs. Raise if it still fails.
    bad = _violations(entries, min_gap)
    for _ in range(200_000):
        if not bad:
            return entries
        a, b = rng.choice(bad), rng.randrange(len(entries))
        entries[a], entries[b] = entries[b], entries[a]
        new = _violations(entries, min_gap)
        if len(new) <= len(bad):
            bad = new
        else:
            entries[a], entries[b] = entries[b], entries[a]
    if not bad:
        return entries
    raise ValueError("could not place items of one pantry apart")


def _assemble(
    pack: Pack,
    base: list[dict],
    entries: list[tuple],
    *,
    neutral: bool,
    extra: bool,
) -> tuple[list[dict], dict]:
    """Render entries into sheet items and key items. ``base[i]`` holds ``pantry`` (ids),
    ``gold_id``, ``pairs`` (arm pairs), ``tops`` (arm to top 5) and, when ``extra``, ids."""
    staples = set(pack.default_staples)
    by_id = {r.recipe_id: r for r in pack.recipes}
    names = {i: ing.name for i, ing in pack.ingredients.items()}
    item_id = {(i, j, rep): f"item{k + 1:02d}" for k, (i, j, rep, _) in enumerate(entries)}
    items, key_items = [], {}
    for i, j, rep, swap in entries:
        b = base[i]
        held = {x for x in b["pantry"] if x in pack.ingredients} - staples
        left_arm, right_arm = b["pairs"][j][::-1] if swap else b["pairs"][j]
        iid = item_id[(i, j, rep)]
        items.append(
            {
                "item_id": iid,
                "pantry": sorted(names[x] for x in b["pantry"]),
                "left": _view(pack, by_id, b["tops"][left_arm], held, staples, neutral),
                "right": _view(pack, by_id, b["tops"][right_arm], held, staples, neutral),
            }
        )
        key_items[iid] = {
            "gold_id": b["gold_id"],
            "left": left_arm,
            "right": right_arm,
            "repeat_of": item_id[(i, j, False)] if rep else None,
        }
        if extra:
            key_items[iid]["pantry_id"] = b["pantry_id"]
            key_items[iid]["probe"] = b["probe"]
    return items, key_items


def build_sheet(
    pack: Pack,
    seed: int = 42,
    n: int = 20,
    repeats: int = 4,
    d: int = 3,
    *,
    arms: Sequence[str] = ARM_LEFT_RIGHT,
    min_gap: int = MIN_GAP,
    neutral_order: bool = False,
    gold_out: bool = False,
    orderers: Orderers | None = None,
) -> tuple[dict, dict]:
    """Return (sheet, key). ``n`` base pantries from the test split, plus ``repeats`` repeats.

    The defaults give the M2 pilot, so its committed key hash still reproduces. Do not add a field
    to that key.
    """
    orderers = orderers or {}
    staples = set(pack.default_staples)
    index = CandidateIndex(pack, staples)
    group_of = {r.recipe_id: _group_key(r) for r in pack.recipes}
    pairs = list(itertools.combinations(arms, 2))
    pool = []
    for p in build_pantries(pack, "popularity", d, seed):
        if p.split != "test" or p.draw != 0:
            continue
        gone = {p.gold_id} | {r for r, g in group_of.items() if g == group_of[p.gold_id]}
        tops = top_lists(index, arms, p.pantry, gone if gold_out else set(), orderers)
        ids = {a: [c.recipe_id for c in t] for a, t in tops.items()}
        # Identical lists cannot be compared, so they carry no information.
        if all(len(v) == TOP for v in ids.values()) and all(ids[a] != ids[b] for a, b in pairs):
            pool.append(
                {"gold_id": p.gold_id, "pantry": list(p.pantry), "tops": tops, "pairs": pairs}
            )
    if len(pool) < n:
        raise ValueError(f"only {len(pool)} usable test pantries, need {n}")
    pool.sort(key=lambda x: _hash(seed, x["gold_id"]))
    base = pool[:n]
    rng = random.Random(f"{seed}:judging")
    entries = _place(rng, [len(pairs)] * n, n * len(pairs), repeats, min_gap)
    items, key_items = _assemble(pack, base, entries, neutral=neutral_order, extra=False)
    return {"version": 1, "items": items}, {"version": 1, "seed": seed, "d": d, "items": key_items}


def build_pool_sheet(
    pack: Pack,
    pool: Sequence[dict],
    arms: Sequence[str],
    *,
    seed: int = 42,
    name: str,
    take: int | None = None,
    repeats: int = 0,
    min_gap: int = MIN_GAP,
    neutral_order: bool = True,
    gold_out: bool = True,
    orderers: Orderers | None = None,
    skip_identical: bool = False,
    probe_pantries: Sequence[dict] = (),
    probes: int = 0,
    probe_arms: Sequence[str] | None = None,
    config: dict | None = None,
) -> tuple[dict, dict]:
    """Build a sheet from committed pool records (plan 8.3). Return (sheet, key).

    Walks ``pool`` in order and keeps ``take`` pantries (all when ``take`` is None). With
    ``skip_identical`` (the test pool) a pantry is skipped when two lists are identical or a list
    is short, and the skip is recorded in the key. ``probes`` re-shows the first dev pantries of
    ``probe_pantries`` with ``probe_arms``. A probe never repeats and the key marks it.
    """
    orderers = orderers or {}
    staples = set(pack.default_staples)
    index = CandidateIndex(pack, staples)
    group_of = {r.recipe_id: _group_key(r) for r in pack.recipes}

    def tops_for(rec: dict, use_arms: Sequence[str]) -> dict[str, list[Scored]]:
        gone = excluded_ids(group_of, rec["gold_id"], rec["title_group"])
        return top_lists(index, use_arms, rec["pantry"], gone if gold_out else set(), orderers)

    base, skipped, skipped_pairs = select_pantries(
        index, group_of, pool, arms, orderers, take=take, neutral_order=neutral_order,
        gold_out=gold_out, skip_identical=skip_identical,
    )  # fmt: skip
    n_repeatable = sum(len(b["pairs"]) for b in base)
    if probes:
        if probe_arms is None or len(probe_arms) != 2 or len(probe_pantries) < probes:
            raise ValueError("probes need two probe arms and enough dev pantries")
        for rec in probe_pantries[:probes]:
            base.append(
                {**rec, "tops": tops_for(rec, probe_arms), "pairs": [tuple(probe_arms)],
                 "probe": True}
            )  # fmt: skip
    sizes = [len(b["pairs"]) for b in base]
    rng = random.Random(f"{seed}:judging:{name}")
    entries = _place(rng, sizes, n_repeatable, repeats, min_gap)
    items, key_items = _assemble(pack, base, entries, neutral=neutral_order, extra=True)
    key = {
        "version": 1,
        "name": name,
        "seed": seed,
        "arms": list(arms),
        "repeats": repeats,
        "min_gap": min_gap,
        "neutral_order": neutral_order,
        "gold_out": gold_out,
        "skipped": skipped,
        "skipped_pairs": skipped_pairs,
        **(config or {}),
        "items": key_items,
    }
    return {"version": 1, "items": items}, key


# ---------------------------------------------------------------------------- guards


def check_pack_hash(pack_dir: Path, expected: str) -> None:
    """Refuse when ``core.v2.json.gz`` is not the pack that made the committed pools."""
    got = _sha256(Path(pack_dir) / "core.v2.json.gz")
    if got != expected:
        raise SystemExit(f"pack hash {got} differs from the pinned {expected}. Stop.")


def check_freeze(root: Path | None = None, pack_core: Path | None = None) -> None:
    """A test sheet needs a committed freeze, a clean tree and every frozen hash matching.

    The freeze file and its checks are ``pantrychef.eval.pairwise`` (one definition).
    """
    root = Path(root) if root is not None else ROOT
    pack_core = Path(pack_core) if pack_core is not None else root / "build/pack/core.v2.json.gz"
    problems = freeze_problems(root, pack_core=pack_core, freeze_rel=FREEZE)
    try:
        if not commits(root, FREEZE):
            problems.append(f"the freeze {FREEZE} is not committed.")
    except Exception as e:  # not a git repo
        problems.append(f"cannot read git history for the freeze: {e}")
    if problems:
        raise SystemExit("Stop. " + "; ".join(problems))


def check_matches_freeze(root: Path, args: argparse.Namespace, doc: dict) -> None:
    """The test sheet is built from exactly what the freeze pinned (plan 8.3): the weights file,
    the pantries file and its test pool, the two arms, the number of pantries and the seed."""
    freeze = json.loads((Path(root) / FREEZE).read_text(encoding="utf-8"))
    files = freeze["files"]
    problems = []
    if _sha256(Path(args.model)) != files.get(WEIGHTS_REL):
        problems.append("--model is not the frozen weights file")
    if _sha256(Path(args.pantries)) != files.get(PANTRIES_REL):
        problems.append("--pantries is not the frozen pantries file")
    if hashlib.sha256(canonical(doc["pools"]["test"])).hexdigest() != freeze["test_pool_sha256"]:
        problems.append("the test pool in --pantries is not the frozen test pool")
    if sorted(args.arms) != sorted(["rank_linear", freeze["comparator"]]):
        problems.append("--arms must be rank_linear and the frozen comparator")
    if args.take != freeze["n_test"]:
        problems.append(f"--take must be the frozen n_test ({freeze['n_test']})")
    if args.seed != freeze["seed"]:
        problems.append(f"--seed must be the frozen seed ({freeze['seed']})")
    if problems:
        raise SystemExit("Stop. The test sheet differs from the freeze: " + "; ".join(problems))


# ---------------------------------------------------------------------------- outputs


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


def write_template(path: Path, item_ids: list[str], arm_guess: bool) -> None:
    """An empty answers CSV with one row per item. ``arm_guess`` adds that column (test only)."""
    cols = TEMPLATE_COLUMNS + (["arm_guess"] if arm_guess else [])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for iid in item_ids:
            w.writerow([iid] + [""] * (len(cols) - 1))


def _model_orderers(pack: Pack, arms: Sequence[str], model_path: str | None) -> Orderers:
    """Orderer for the arm ``rank_linear`` (the model of plan section 7)."""
    if "rank_linear" not in arms:
        return {}
    if not model_path:
        raise SystemExit("the arm rank_linear needs --model web/src/rank_model.v1.json")
    return {"rank_linear": model_orderer(pack, load_model(model_path))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="build/pack")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--arms", nargs="+", default=list(ARM_LEFT_RIGHT))
    ap.add_argument("--n", type=int, default=20, help="old pilot only: base pantries")
    ap.add_argument("--repeats", type=int, default=None, help="default 4 (old pilot) or 0")
    ap.add_argument("--min-gap", type=int, default=MIN_GAP)
    ap.add_argument("--pantries", help="committed pool file, data/eval/m4/pantries.v1.json")
    ap.add_argument("--pool", choices=POOLS)
    ap.add_argument("--take", type=int)
    ap.add_argument("--name")
    ap.add_argument("--neutral-order", action=argparse.BooleanOptionalAction, default=None)
    ap.add_argument("--gold-out", action=argparse.BooleanOptionalAction, default=None)
    ap.add_argument("--model", help="weights file for the arm rank_linear")
    ap.add_argument("--arm-guess", action="store_true", help="test sheet only")
    ap.add_argument("--probes", type=int, default=0, help="dev items to re-show in a test sheet")
    ap.add_argument("--probe-arms", nargs=2, default=["shipped", "idf_flat"])
    ap.add_argument("--out-dir", help="write the M4 files under this folder, not the repo root")
    args = ap.parse_args(argv)
    if not 2 <= len(args.arms) <= 3:
        ap.error("--arms takes 2 or 3 names")
    m4 = bool(args.pantries or args.name)
    if m4 and not (args.pantries and args.pool and args.name):
        ap.error("--pantries, --pool and --name go together")
    if args.arm_guess and args.pool != "test":
        raise SystemExit("--arm-guess is for the test pool only")
    if args.probes and args.pool != "test":
        raise SystemExit("--probes is for the test pool only")
    if m4 and (args.neutral_order is False or args.gold_out is False):
        raise SystemExit("an M4 sheet always uses neutral order and gold-out: drop the flag")
    neutral = m4 if args.neutral_order is None else args.neutral_order
    gold_out = m4 if args.gold_out is None else args.gold_out
    pack_dir = Path(args.pack)
    out = Path(args.out_dir) if args.out_dir else ROOT

    if not m4:
        pack = load_pack(pack_dir)
        sheet, key = build_sheet(
            pack, seed=args.seed, n=args.n, repeats=4 if args.repeats is None else args.repeats,
            arms=args.arms, min_gap=args.min_gap, neutral_order=neutral, gold_out=gold_out,
            orderers=_model_orderers(pack, args.arms, args.model),
        )  # fmt: skip
        digest = write_outputs(sheet, key, SHEET, KEY, KEY_SHA)
        print(f"{len(sheet['items'])} items. Key sha256 {digest}", file=sys.stderr)
        return 0

    doc = json.loads(Path(args.pantries).read_text(encoding="utf-8"))
    check_pack_hash(pack_dir, doc["pack_core_sha256"])
    if args.pool == "test":
        check_freeze(out, pack_dir / "core.v2.json.gz")
        if not args.model:
            raise SystemExit("the test sheet needs --model")
        check_matches_freeze(out, args, doc)
    pack = load_pack(pack_dir)
    config = {
        "pool": args.pool,
        "pack_core_sha256": doc["pack_core_sha256"],
        "model_sha256": _sha256(Path(args.model)) if args.model else None,
        "arm_guess": args.arm_guess,
    }
    sheet, key = build_pool_sheet(
        pack, doc["pools"][args.pool], args.arms, seed=args.seed, name=args.name, take=args.take,
        repeats=args.repeats or 0, min_gap=args.min_gap, neutral_order=neutral, gold_out=gold_out,
        orderers=_model_orderers(pack, args.arms, args.model),
        skip_identical=args.pool == "test",
        probe_pantries=doc["pools"]["dev"] if args.probes else (), probes=args.probes,
        probe_arms=args.probe_arms, config=config,
    )  # fmt: skip
    digest = write_outputs(
        sheet,
        key,
        out / f"data/eval/m4/sheet.{args.name}.v1.json",
        out / f"data/interim/judging_key.m4-{args.name}.v1.json",
        out / f"data/eval/m4/key_sha256.{args.name}.txt",
    )
    write_template(
        out / f"data/interim/answers_template.m4-{args.name}.csv",
        [it["item_id"] for it in sheet["items"]],
        args.arm_guess,
    )
    print(f"{len(sheet['items'])} items. Key sha256 {digest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
