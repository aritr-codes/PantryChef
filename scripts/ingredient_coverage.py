"""Measure how many Wikibooks ingredient lines the ingredient table reads.

Reads a snapshot made by ``scripts/fetch_wikibooks.py``. Prints a Markdown report with the
share of lines read, the share of recipes with every required line read (the pack rules, see
``pantrychef.pack.build.coverage``) and the most common unread phrases. Lines in the M3 frozen
set (test and extra lines, by hash) never appear in the phrases. Nothing here ships.

With ``--growth-row FILE`` it also scores the dev halves and appends one row to the results file
FILE (M3 table growth). Dev scoring never reads test or extra data. By default a gold name maps to
an id through the table keys (``dev_scoring: "table_keys"``), so a score depends on which keys the
table has. With ``--id-map PATH`` (a frozen map of gold name to id) gold names map through the map
(``dev_scoring: "id_map"``), so the score does not move when the table keys move.

Example:
    uv run python scripts/ingredient_coverage.py data/raw/wikibooks/snapshot.2026-11-03.jsonl.gz \\
        --table data/ingredients/ingredients.v2.csv --growth-row results/m3_table_growth.json
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from collections.abc import Collection
from pathlib import Path

from pantrychef.eval.parser_gold import line_hash, load_frozen, read_labels_json, score
from pantrychef.eval.realistic import score_inputs
from pantrychef.eval.results import git_facts, write_result
from pantrychef.ingredients.names import resolve_name
from pantrychef.ingredients.resolve import _body
from pantrychef.ingredients.table import IngredientTable, tokens
from pantrychef.pack.build import coverage
from pantrychef.sources.wikibooks import parse_page

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "data/eval/parser_gold"
EVAL = ROOT / "data/eval"
RESOLVER = "resolve_name"  # the typed-name resolver that scores input_accuracy_dev


def top_unread(
    unread: list[str], table: IngredientTable, frozen: Collection[str], n: int
) -> list[list]:
    """Top ``n`` ``[phrase, count]`` of unread lines. Lines hashed in ``frozen`` are skipped."""
    phrases = Counter(
        " ".join(tokens(_body(text, table.words)))
        for text in unread
        if line_hash(text) not in frozen
    )
    return [[p, c] for p, c in phrases.most_common(n)]


def read_id_map(path: Path) -> dict[str, str | None]:
    """Read a frozen gold-name-to-id map. ``null`` means the name has no id."""
    return json.loads(Path(path).read_text(encoding="utf8"))


def dev_scores(
    table: IngredientTable, id_map: dict[str, str | None] | None = None
) -> tuple[dict, dict]:
    """Score the dev halves. Return ``(parser, inputs)``.

    Gold names map through the table keys, or through ``id_map`` when given. ``parser`` also holds
    ``random_stratum``: the same scores over the 50 dev lines of the random stratum.
    """
    sheet = json.loads((GOLD / "sheet.v1.json").read_text(encoding="utf8"))
    lines = [r for r in sheet["lines"] if r["split"] == "dev"]
    gold = read_labels_json(GOLD / "labels.dev.v1.json")
    parser = score(lines, gold, table, id_map)
    rnd = score([r for r in lines if r["stratum"] == "random"], gold, table, id_map)
    parser["random_stratum"] = {
        k: rnd[k] for k in ("lines", "gold_groups", "pred_groups", "mention_accuracy", "precision")
    }

    split = json.loads((EVAL / "realistic_inputs.split.v1.json").read_text(encoding="utf8"))
    dev_inputs = sorted(t for t, s in split["assignment"].items() if s == "dev")
    labels = read_labels_json(EVAL / "realistic_inputs.labels.v1.json")
    keys = {" ".join(k): i for k, i in table.keys.items()}

    def resolve(text: str) -> list[str]:
        return list(resolve_name(text, keys, table.words).ids)

    return parser, score_inputs(dev_inputs, labels, resolve, table)


def growth_row(
    commit: str,
    table: IngredientTable,
    cov: dict,
    parser: dict,
    inputs: dict,
    top: list[list],
    id_map_path: str | None = None,
) -> dict:
    return {
        "commit": commit,
        "resolver": RESOLVER,
        "rows": len(table.rows),
        "lines_read": cov["lines_read"],
        "recipes_fully_read": cov["recipes_fully_read"],
        "mention_accuracy_dev": parser["mention_accuracy"],
        "parser_precision_dev": parser["precision"],
        "input_accuracy_dev": inputs["input_accuracy"],
        "top_unread": top,
        "dev_scoring": "id_map" if id_map_path else "table_keys",
        "id_map": id_map_path,
    }


def write_growth(
    path: Path, row: dict, cov: dict, parser: dict, inputs: dict, *, fingerprint: str, command: str
) -> None:
    """Append ``row`` to ``config.rows`` of the results file at ``path`` and rewrite it."""
    path = Path(path)
    rows = json.loads(path.read_text(encoding="utf8"))["config"]["rows"] if path.exists() else []
    for old in rows:  # rows written before the id map existed scored through the table keys
        old.setdefault("dev_scoring", "table_keys")
        old.setdefault("id_map", None)

    def metric(name: str, split: str, n: int, value: float) -> dict:
        return {"name": name, "arm": None, "split": split, "n": n, "value": float(value)}

    write_result(
        path,
        {
            "label": "MEASURED",
            "what": "Ingredient table growth: one row per round (latest row in metrics). "
            "recipes_fully_read is in-sample over the Wikibooks snapshot; the other three are dev.",
            "command": command,
            "config": {"rows": [*rows, row], "split": "dev", "parser": parser, "inputs": inputs},
            "seed": 0,
            "corpus_fingerprint": fingerprint,
            "arms": [],
            "metrics": [
                metric("recipes_fully_read", "all", cov["kept_recipes"], cov["recipes_fully_read"]),
                metric(
                    "mention_accuracy",
                    "dev",
                    int(parser["gold_groups"]),
                    row["mention_accuracy_dev"],
                ),
                metric(
                    "parser_precision",
                    "dev",
                    int(parser["pred_groups"]),
                    row["parser_precision_dev"],
                ),
                metric("input_accuracy", "dev", int(inputs["n"]), row["input_accuracy_dev"]),
            ],
            "comparisons": [],
            "environment": {},
        },
        ROOT,
    )


def _rel(p: str | Path) -> str:
    p = Path(p).resolve()
    return p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else str(p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("snapshot")
    ap.add_argument("--table", default=None)
    ap.add_argument("--top", type=int, default=60)
    ap.add_argument("--growth-row", type=Path, default=None, metavar="FILE")
    ap.add_argument("--id-map", type=Path, default=None, metavar="PATH")
    args = ap.parse_args(argv)

    table = IngredientTable.load(args.table)  # None: the default, the v2 table
    with gzip.open(args.snapshot, "rt", encoding="utf8") as fh:
        records = [json.loads(line) for line in fh]
    recipes = [r for rec in records if (r := parse_page(rec, "x"))]
    cov = coverage(recipes, table)
    top = top_unread(cov["unread"], table, load_frozen(), args.top)

    n, total = len(recipes), cov["required_lines"]
    print(f"- Table rows: {len(table.rows)}")
    print(f"- Recipes with an ingredient list: {n}")
    print(f"- Required lines: {total}; optional lines: {cov['optional_lines']}")
    print(f"- Required lines read: {cov['lines_read']} ({cov['lines_read'] / total:.1%})")
    print(
        f"- Recipes kept by the pack: {cov['kept_recipes']}; with every required line read: "
        f"{cov['fully_read']} ({cov['recipes_fully_read']:.1%})"
    )
    print(f"\nTop {args.top} unread phrases (count, phrase), frozen lines left out:\n")
    for phrase, c in top:
        print(f"- {c}\t{phrase}")

    if args.growth_row:
        id_map = read_id_map(args.id_map) if args.id_map else None
        parser, inputs = dev_scores(table, id_map)
        map_path = _rel(args.id_map) if id_map else None
        row = growth_row(git_facts(ROOT)[0], table, cov, parser, inputs, top, map_path)
        command = (
            f"uv run python scripts/ingredient_coverage.py {_rel(args.snapshot)}"
            + (f" --table {_rel(args.table)}" if args.table else "")
            + f" --growth-row {_rel(args.growth_row)}"
            + (f" --id-map {map_path}" if map_path else "")
            + (f" --top {args.top}" if args.top != 60 else "")
        )
        fingerprint = hashlib.sha256(Path(args.snapshot).read_bytes()).hexdigest()
        write_growth(
            args.growth_row, row, cov, parser, inputs, fingerprint=fingerprint, command=command
        )
        rs = parser["random_stratum"]
        print(
            f"\nDev scoring: {row['dev_scoring']}. Dev mention_accuracy "
            f"{parser['mention_accuracy']:.4f}, precision {parser['precision']:.4f}. "
            f"Random stratum ({rs['lines']} lines): mention_accuracy "
            f"{rs['mention_accuracy']:.4f}, precision {rs['precision']:.4f}."
        )
        print(f"Row {row['rows']} written to {_rel(args.growth_row)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
