"""Measure how many Wikibooks ingredient lines the ingredient table reads.

Reads a snapshot made by ``scripts/fetch_wikibooks.py``. Prints a Markdown report with the
share of lines read, the share of recipes with every required line read, and the most
common unread phrases. Nothing here ships.

Example:
    uv run python scripts/ingredient_coverage.py data/raw/wikibooks/snapshot.2026-11-03.jsonl.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter

from pantrychef.ingredients.resolve import _body, resolve_lines
from pantrychef.ingredients.table import IngredientTable, tokens
from pantrychef.sources.wikibooks import parse_page


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("snapshot")
    ap.add_argument("--table", default=None)
    ap.add_argument("--top", type=int, default=60)
    args = ap.parse_args()

    table = IngredientTable.load(args.table) if args.table else IngredientTable.load()
    with gzip.open(args.snapshot, "rt", encoding="utf8") as fh:
        records = [json.loads(line) for line in fh]
    recipes = [r for rec in records if (r := parse_page(rec, "x"))]

    total = unread = optional = 0
    full = 0
    phrases: Counter[str] = Counter()
    for r in recipes:
        all_read = True
        for text in r.ingredient_lines:
            for line in resolve_lines(text, table):
                if line.optional:
                    optional += 1
                    continue
                total += 1
                if not line.read:
                    unread += 1
                    all_read = False
                    phrases[" ".join(tokens(_body(text)))] += 1
        full += all_read

    n = len(recipes)
    print(f"- Table rows: {len(table.rows)}")
    print(f"- Recipes with an ingredient list: {n}")
    print(f"- Required lines: {total}; optional lines: {optional}")
    print(f"- Required lines read: {total - unread} ({(total - unread) / total:.1%})")
    print(f"- Recipes with every required line read: {full} ({full / n:.1%})")
    print(f"\nTop {args.top} unread phrases (count, phrase):\n")
    for phrase, c in phrases.most_common(args.top):
        print(f"- {c}\t{phrase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
