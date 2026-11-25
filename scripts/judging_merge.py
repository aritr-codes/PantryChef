"""Merge per-session answer CSVs into one file, in sheet order. Prints counts, never answers.

    uv run python scripts/judging_merge.py --sheet data/eval/m4/sheet.NAME.v1.json \\
        --out data/eval/m4/answers.NAME.v1.csv answers.NAME.session1.csv answers.NAME.session2.csv

Add ``--arm-guess`` for a test sheet. A row with every answer field blank counts as unanswered.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

# Same list as scripts.judging_sheet.TEMPLATE_COLUMNS (a test checks it).
COLUMNS = ["item_id", "choice", "strength", "would_cook_left", "would_cook_right",
           "seconds", "session"]  # fmt: skip
ANSWER = ["choice", "strength", "would_cook_left", "would_cook_right", "arm_guess", "seconds"]


class MergeError(SystemExit):
    pass


def row_problem(row: dict, arm_guess: bool) -> str | None:
    """Name the first bad column of a row, or None. Never include a value."""
    c = row.get("choice", "")
    s = row.get("strength", "")
    if c not in ("A", "B", "tie"):
        return "choice"
    if s not in ("", "1", "2") or (s == "") != (c == "tie"):
        return "strength"
    for col in ("would_cook_left", "would_cook_right"):
        if row.get(col, "") not in ("yes", "no"):
            return col
    if arm_guess and row.get("arm_guess", "") not in ("left", "right", "unsure"):
        return "arm_guess"
    if row.get("seconds", "") != "" and not row["seconds"].isdigit():
        return "seconds"
    return None


def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def answered_ids(paths: list[Path], arm_guess: bool) -> set[str]:
    """Ids with a complete answer in any of the files."""
    return {
        r["item_id"] for p in paths for r in _read(Path(p)) if row_problem(r, arm_guess) is None
    }


def merge(sheet: Path, sessions: list[Path], out: Path, arm_guess: bool = False) -> int:
    """Write ``out``. Return the number of sheet items still unanswered."""
    doc = json.loads(Path(sheet).read_text(encoding="utf-8"))
    ids = [it["item_id"] for it in doc["items"]]
    arm_guess = arm_guess or bool(doc.get("arm_guess"))
    got: dict[str, dict] = {}
    for p in sessions:
        for r in _read(Path(p)):
            iid = r.get("item_id", "")
            if iid not in ids:
                raise MergeError(f"unknown item id {iid!r} in {Path(p).name}")
            if not any(r.get(c) for c in ANSWER):
                continue  # an unanswered row
            bad = row_problem(r, arm_guess)
            if bad:
                raise MergeError(f"{iid} in {Path(p).name}: bad or missing {bad}")
            if iid in got:
                raise MergeError(f"{iid} is answered twice ({Path(p).name})")
            got[iid] = r
    cols = COLUMNS + (["arm_guess"] if arm_guess else [])
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for iid in ids:
            if iid in got:
                w.writerow([got[iid].get(c, "") for c in cols])
    return len(ids) - len(got)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--arm-guess", action="store_true")
    ap.add_argument("sessions", nargs="+")
    a = ap.parse_args(argv)
    left = merge(Path(a.sheet), [Path(s) for s in a.sessions], Path(a.out), a.arm_guess)
    print(f"merged into {a.out}; {left} items still unanswered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
