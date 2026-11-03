"""Build the blank 300-line parser gold sheet and its dev/test split (M2, plan D4).

Lines come from the official Wikibooks snapshot (CC BY-SA 4.0), never from RecipeNLG.
Three strata of 100 lines each:

- ``random``: uniform over all distinct lines. Drawn first, so it stays a fair sample.
- ``hard``: a line with a Unicode fraction, "or", brackets, "and", a digit range, or a line that the
  M1 resolver reads as unread or as several lines.
- ``rare``: a line whose resolved ingredient appears in the fewest recipes.

The hard and rare strata use the M1 resolver to PICK lines. They do not copy its output into the
sheet. Report results per stratum and pool only ``random`` for a headline number.

Each stratum is cut 50/50 into dev and test by sorted sha256, so sizes are exact (50 and 50).

Run from the repo root:  uv run python scripts/make_parser_gold_sheet.py
Writes data/eval/parser_gold/sheet.v1.json and data/interim/parser_gold_labelling.csv
(the CSV is a work file; git ignores it).
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from pantrychef.ingredients.resolve import resolve_lines
from pantrychef.ingredients.table import IngredientTable
from pantrychef.sources.wikibooks import parse_page

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data/raw/wikibooks/snapshot.2026-11-03.jsonl.gz"
TABLE = ROOT / "data/ingredients/ingredients.csv"
OUT_SHEET = ROOT / "data/eval/parser_gold/sheet.v1.json"
OUT_CSV = ROOT / "data/interim/parser_gold_labelling.csv"
SEED = 42
PER_STRATUM = 100
RETRIEVED_ON = "2026-11-03"

_HARD = re.compile(r"[¼-¾⅐-⅞]|\bor\b|\(|\band\b|\d\s*(?:-|to)\s*\d", re.I)


def sort_key(seed: int, stratum: str, line_id: str) -> str:
    return hashlib.sha256(f"{seed}:{stratum}:{line_id}".encode()).hexdigest()


def collect_lines(snapshot: Path = SNAPSHOT) -> list[dict]:
    """Return one record per distinct (case-folded) line text, in snapshot order."""
    seen: set[str] = set()
    out: list[dict] = []
    with gzip.open(snapshot, "rt", encoding="utf8") as fh:
        for raw in fh:
            r = parse_page(json.loads(raw), RETRIEVED_ON)
            if r is None:
                continue
            for n, text in enumerate(r.ingredient_lines):
                key = text.casefold().strip()
                if len(key) < 3 or key.endswith(":") or key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "id": f"{r.recipe_id}#{n}",
                        "text": text,
                        "page": r.page,
                        "revision_id": r.revision_id,
                        "revision_url": r.revision_url,
                    }
                )
    return out


def pick(pool: list[dict], taken: set[str], stratum: str, n: int, seed: int = SEED) -> list[dict]:
    ordered = sorted(
        (rec for rec in pool if rec["id"] not in taken),
        key=lambda rec: sort_key(seed, stratum, rec["id"]),
    )
    chosen = ordered[:n]
    if len(chosen) < n:
        raise SystemExit(f"stratum {stratum}: only {len(chosen)} lines available")
    taken.update(rec["id"] for rec in chosen)
    return chosen


def build(lines: list[dict], table: IngredientTable, seed: int = SEED) -> list[dict]:
    resolved = {rec["id"]: resolve_lines(rec["text"], table) for rec in lines}
    df: Counter[str] = Counter()
    for res in resolved.values():
        for i in {i for rl in res for i in rl.options}:
            df[i] += 1

    def hard(rec: dict) -> bool:
        res = resolved[rec["id"]]
        return bool(_HARD.search(rec["text"])) or len(res) != 1 or not res[0].read

    def rare_score(rec: dict) -> int | None:
        ids = {i for rl in resolved[rec["id"]] for i in rl.options}
        return min((df[i] for i in ids), default=None)

    taken: set[str] = set()
    rows: list[dict] = []
    random_rows = pick(lines, taken, "random", PER_STRATUM, seed)
    hard_rows = pick([r for r in lines if hard(r)], taken, "hard", PER_STRATUM, seed)
    scored = sorted(
        (r for r in lines if r["id"] not in taken and rare_score(r) is not None),
        key=lambda r: (rare_score(r), sort_key(seed, "rare", r["id"])),
    )
    rare_rows = scored[:PER_STRATUM]
    if len(rare_rows) < PER_STRATUM:
        raise SystemExit("not enough rare lines")
    taken.update(r["id"] for r in rare_rows)

    for stratum, chosen in (("random", random_rows), ("hard", hard_rows), ("rare", rare_rows)):
        ordered = sorted(chosen, key=lambda r: sort_key(seed, "split:" + stratum, r["id"]))
        half = len(ordered) // 2
        for k, rec in enumerate(ordered):
            rows.append({**rec, "stratum": stratum, "split": "dev" if k < half else "test"})
    rows.sort(key=lambda r: sort_key(seed, "order", r["id"]))  # shuffled, so order hides strata
    return rows


def main() -> None:
    table = IngredientTable.from_text(TABLE.read_text(encoding="utf8"))
    lines = collect_lines()
    rows = build(lines, table)
    digest = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    doc = {
        "version": 1,
        "seed": SEED,
        "snapshot": SNAPSHOT.name,
        "snapshot_sha256": digest,
        "licence": "CC BY-SA 4.0",
        "n": len(rows),
        "counts": {
            f"{s}/{p}": sum(1 for r in rows if r["stratum"] == s and r["split"] == p)
            for s in ("random", "hard", "rare")
            for p in ("dev", "test")
        },
        "lines": rows,
    }
    OUT_SHEET.parent.mkdir(parents=True, exist_ok=True)
    OUT_SHEET.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf8", newline="\n"
    )
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "text", "names", "optional", "not_an_ingredient"])
        for r in rows:
            w.writerow([r["id"], r["text"], "", "", ""])
    print(doc["n"], doc["counts"])


if __name__ == "__main__":
    main()
