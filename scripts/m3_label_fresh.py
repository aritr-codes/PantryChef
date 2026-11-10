"""Label the M3 fresh lines: blind sheet, compare, owner sheet and merge (M3 acceptance round 2).

  uv run python scripts/m3_label_fresh.py make-sheet
  uv run python scripts/m3_label_fresh.py compare A B
  uv run python scripts/m3_label_fresh.py owner-sheet
  uv run python scripts/m3_label_fresh.py merge [OWNER_CSV]

The flow is that of ``scripts/m3_label_sets.py``, with one set (``fresh200``): two blind labellers,
the owner settles each disagreement, and the owner checks a sample of agreed lines. Work files go
to ``data/interim/fresh/`` (git ignores it). Every command prints counts only. It never prints a
line or a label.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from pantrychef.eval.parser_gold import Label, LabelError, label_from_fields
from scripts.m3_label_sets import (
    MAX_AGREED_ERRORS,
    N_AGREED,
    _by_id,
    _dis,
    _dump,
    _load_pair,
    _record,
    compare,
    make_sheets,
    owner_sheet,
)

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data/interim/fresh"
GOLD = ROOT / "data/eval/parser_gold"
FRESH = GOLD / "fresh.v1.json"
NAME = "fresh200"
Sets = dict[str, list[tuple[str, str]]]


def load_fresh(path: Path = FRESH) -> Sets:
    lines = json.loads(path.read_text(encoding="utf8"))["lines"]
    return {NAME: [(r["id"], r["text"]) for r in lines]}


def merge_fresh(
    sets: Sets,
    owner_csv: Path,
    work: Path,
    targets: dict[str, Path],
    max_agreed_errors: int = MAX_AGREED_ERRORS,
    n_agreed: int = N_AGREED,
) -> None:
    """Write the fresh label files from a filled owner sheet. Never overwrite a file.

    The sheet must hold exactly ``n_agreed`` agreed rows, no duplicate row, and no label text on
    an agreed row unless its ``error`` is 1.
    """
    for p in targets.values():
        if p.exists():
            raise SystemExit(f"{p.name} exists; label files are never overwritten")
    owner: dict[str, dict] = {}
    with owner_csv.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["set"] != NAME:
                raise LabelError(f"{r['id']}: set must be {NAME}")
            if r["id"] in owner:
                raise LabelError(f"{r['id']}: duplicate row in the owner sheet")
            if r["kind"] not in ("disagree", "agreed"):
                raise LabelError(f"{r['id']}: kind must be disagree or agreed")
            owner[r["id"]] = r
    if sum(r["kind"] == "agreed" for r in owner.values()) != n_agreed:
        raise LabelError(f"the owner sheet must hold exactly {n_agreed} agreed rows")
    items = sets[NAME]
    ids = [i for i, _ in items]
    text = dict(items)
    d = _dis(work, NAME)
    la, lb = _load_pair(d, ids)
    final: dict[str, Label] = dict(la)  # agreed lines keep labeller A
    records = []
    if {i for i, r in owner.items() if r["kind"] == "disagree"} != set(d["ids"]):
        raise LabelError("the disagree rows of the owner sheet do not match the comparison")
    for i in d["ids"]:
        r = owner[i]
        final[i] = label_from_fields(i, r["names"], r["optional"], r["not_an_ingredient"])
        records.append(_record(i, text[i], la[i], lb[i], final[i]))
    checked: list[str] = []
    errors: list[str] = []
    for i, r in owner.items():
        if r["kind"] != "agreed":
            continue
        if i not in ids or i in d["ids"]:
            raise LabelError(f"{i}: not an agreed line of {NAME}")
        checked.append(i)
        flag = r["error"].strip()
        if flag not in ("", "0", "1"):
            raise LabelError(f"{i}: error must be 0, 1 or blank")
        filled = r["names"].strip() or r["optional"].strip() or r["not_an_ingredient"].strip()
        if flag != "1" and filled:
            raise LabelError(f"{i}: label filled on an agreed row, but error is not 1")
        if flag == "1":
            errors.append(i)
            final[i] = label_from_fields(i, r["names"], r["optional"], r["not_an_ingredient"])
    if len(errors) > max_agreed_errors:
        raise SystemExit(f"{len(errors)} of {len(checked)} agreed lines are wrong; stop and report")
    _dump(targets["labels"], {"version": 1, "split": "fresh", "labels": _by_id(final)})
    _dump(
        targets["adjudication"],
        {
            "version": 1,
            "resolved_by": "owner",
            "agreed_check": {
                "n": len(checked),
                "errors": len(errors),
                "agreed_error_rate": len(errors) / len(checked) if checked else 0.0,
                "error_ids": errors,
            },
            "set": {
                "lines": len(ids),
                "exact_agreement": d["exact_agreement"],
                "a": Path(d["a"]["path"]).name,
                "b": Path(d["b"]["path"]).name,
                "disagreements": records,
            },
        },
    )
    print(f"wrote {len(targets)} files; agreed-line errors {len(errors)} of {len(checked)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("make-sheet")
    c = sub.add_parser("compare")
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    sub.add_parser("owner-sheet")
    m = sub.add_parser("merge")
    m.add_argument("owner_csv", type=Path, nargs="?", default=WORK / "m3_owner_sheet.csv")
    args = ap.parse_args()
    sets = load_fresh()
    WORK.mkdir(parents=True, exist_ok=True)
    if args.cmd == "make-sheet":
        make_sheets(sets, WORK)
    elif args.cmd == "compare":
        n, agree, _ids = compare(NAME, sets, args.a, args.b, WORK)
        print(f"{NAME}: n={n}, exact agreements={agree}, disagreements={n - agree}")
    elif args.cmd == "owner-sheet":
        owner_sheet(sets, WORK)
    else:
        merge_fresh(
            sets,
            args.owner_csv,
            WORK,
            {
                "labels": GOLD / "labels.fresh.v1.json",
                "adjudication": GOLD / "adjudication.fresh.v1.json",
            },
        )


if __name__ == "__main__":
    main()
