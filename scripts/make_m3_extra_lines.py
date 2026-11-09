"""Draw the M3 extra parser lines and freeze the test and extra line hashes (M3 Task 1).

100 fresh lines, uniform over the distinct snapshot lines that are not in ``sheet.v1.json``.
The filters are those of ``make_parser_gold_sheet.collect_lines``. Order is by sha256 of
``seed:extra:id`` with seed 43. The frozen file holds the hash of every test and extra line.
The script prints counts only.

Run from the repo root:  uv run python scripts/make_m3_extra_lines.py
Writes data/eval/parser_gold/extra.v1.json and data/eval/m3_frozen_lines.v1.json.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pantrychef.eval.parser_gold import line_hash
from scripts.make_parser_gold_sheet import RETRIEVED_ON, SNAPSHOT, collect_lines, sort_key

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "data/eval/parser_gold/sheet.v1.json"
OUT_EXTRA = ROOT / "data/eval/parser_gold/extra.v1.json"
OUT_FROZEN = ROOT / "data/eval/m3_frozen_lines.v1.json"
SEED = 43
N_EXTRA = 100


def draw_extra(lines: list[dict], sheet_lines: list[dict], n: int = N_EXTRA, seed: int = SEED):
    """Return ``n`` records from ``lines`` whose text is not in the sheet, in hash order."""
    taken = {r["text"].casefold().strip() for r in sheet_lines}
    pool = [r for r in lines if r["text"].casefold().strip() not in taken]
    if len(pool) < n:
        raise SystemExit(f"only {len(pool)} lines available")
    pool.sort(key=lambda r: sort_key(seed, "extra", r["id"]))
    return [{**r, "stratum": "random", "split": "extra"} for r in pool[:n]]


def _write(path: Path, doc: dict) -> None:
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf8", newline="\n"
    )


def main() -> None:
    for out in (OUT_EXTRA, OUT_FROZEN):
        if out.exists():
            raise SystemExit(f"{out.name} exists; it is frozen")
    sheet = json.loads(SHEET.read_text(encoding="utf8"))["lines"]
    extra = draw_extra(collect_lines(), sheet)
    digest = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    _write(
        OUT_EXTRA,
        {
            "version": 1,
            "seed": SEED,
            "snapshot": SNAPSHOT.name,
            "snapshot_sha256": digest,
            "retrieved_on": RETRIEVED_ON,
            "licence": "CC BY-SA 4.0",
            "n": len(extra),
            "lines": extra,
        },
    )
    hashes = sorted(
        {line_hash(r["text"]) for r in sheet if r["split"] == "test"}
        | {line_hash(r["text"]) for r in extra}
    )
    _write(
        OUT_FROZEN,
        {
            "version": 1,
            "method": "sha256 of text.casefold().strip(); 150 sheet test lines plus extra lines",
            "n": len(hashes),
            "hashes": hashes,
        },
    )
    print(f"extra {len(extra)}, frozen {len(hashes)}")


if __name__ == "__main__":
    main()
