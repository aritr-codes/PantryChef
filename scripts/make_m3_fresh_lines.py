"""Draw the M3 fresh parser lines and freeze their hashes (M3 acceptance round 2).

The first acceptance run failed one target, so its test lines are spent. This script draws a new
held-out set before any table change: 200 fresh lines, uniform over the distinct snapshot lines
that are in neither ``sheet.v1.json`` nor ``extra.v1.json``. The filters are those of
``make_parser_gold_sheet.collect_lines``. Order is by sha256 of ``seed:fresh:id`` with seed 47.
The frozen file holds the hash of every fresh line, so table growth never reads them.
The script prints counts only. Nobody reads ``fresh.v1.json`` until the second acceptance run.

Run from the repo root:  uv run python scripts/make_m3_fresh_lines.py
Writes data/eval/parser_gold/fresh.v1.json and data/eval/m3_frozen_lines.v2.json.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pantrychef.eval.parser_gold import line_hash
from scripts.make_parser_gold_sheet import RETRIEVED_ON, SNAPSHOT, collect_lines, sort_key

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "data/eval/parser_gold/sheet.v1.json"
EXTRA = ROOT / "data/eval/parser_gold/extra.v1.json"
OUT_FRESH = ROOT / "data/eval/parser_gold/fresh.v1.json"
OUT_FROZEN = ROOT / "data/eval/m3_frozen_lines.v2.json"
SEED = 47
N_FRESH = 200


def draw_fresh(lines: list[dict], taken_lines: list[dict], n: int = N_FRESH, seed: int = SEED):
    """Return ``n`` records from ``lines`` whose text is not in ``taken_lines``, in hash order."""
    taken = {r["text"].casefold().strip() for r in taken_lines}
    pool = [r for r in lines if r["text"].casefold().strip() not in taken]
    if len(pool) < n:
        raise SystemExit(f"only {len(pool)} lines available")
    pool.sort(key=lambda r: sort_key(seed, "fresh", r["id"]))
    return [{**r, "stratum": "random", "split": "fresh"} for r in pool[:n]]


def _write(path: Path, doc: dict) -> None:
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf8", newline="\n"
    )


def main() -> None:
    for out in (OUT_FRESH, OUT_FROZEN):
        if out.exists():
            raise SystemExit(f"{out.name} exists; it is frozen")
    taken = json.loads(SHEET.read_text(encoding="utf8"))["lines"]
    taken += json.loads(EXTRA.read_text(encoding="utf8"))["lines"]
    fresh = draw_fresh(collect_lines(), taken)
    digest = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    _write(
        OUT_FRESH,
        {
            "version": 1,
            "seed": SEED,
            "snapshot": SNAPSHOT.name,
            "snapshot_sha256": digest,
            "retrieved_on": RETRIEVED_ON,
            "licence": "CC BY-SA 4.0",
            "n": len(fresh),
            "lines": fresh,
        },
    )
    hashes = sorted({line_hash(r["text"]) for r in fresh})
    _write(
        OUT_FROZEN,
        {
            "version": 1,
            "method": "sha256 of text.casefold().strip(); fresh lines only; v1 holds the rest",
            "n": len(hashes),
            "hashes": hashes,
        },
    )
    print(f"fresh {len(fresh)}, frozen {len(hashes)}")


if __name__ == "__main__":
    main()
