"""Score the M1 resolver on the DEV halves only (M3 Task 1, step 8). Run from the repo root.

  uv run python scripts/m3_dev_baseline.py --out results/m3_m1_dev_baseline.json

Parser gold dev lines: ``mention_accuracy`` and ``parser_precision``. Realistic inputs, dev half:
``input_accuracy`` with the M1 typed-name rule (one exact key lookup, as ``resolve_names`` does).
Test and extra data are never read. Gold names map to ids through the table keys (dev only; the
blind id map of plan D9 is for acceptance).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pantrychef.eval.parser_gold import read_labels_json, score
from pantrychef.eval.realistic import score_inputs
from pantrychef.eval.results import write_result
from pantrychef.ingredients.table import IngredientTable, tokens

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "data/eval/parser_gold"
EVAL = ROOT / "data/eval"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    table = IngredientTable.load()
    sheet = json.loads((GOLD / "sheet.v1.json").read_text(encoding="utf8"))
    lines = [r for r in sheet["lines"] if r["split"] == "dev"]
    parser = score(lines, read_labels_json(GOLD / "labels.dev.v1.json"), table)

    split = json.loads((EVAL / "realistic_inputs.split.v1.json").read_text(encoding="utf8"))
    dev_inputs = sorted(t for t, s in split["assignment"].items() if s == "dev")
    labels = read_labels_json(EVAL / "realistic_inputs.labels.v1.json")

    def resolve(text: str) -> list[str]:
        hit = table.keys.get(tokens(text))
        return [hit] if hit else []

    inputs = score_inputs(dev_inputs, labels, resolve, table)
    print(json.dumps({"parser": parser, "inputs": inputs}, indent=2))

    def metric(name: str, n: int, value: float) -> dict:
        return {"name": name, "arm": None, "split": "dev", "n": n, "value": float(value)}

    write_result(
        args.out,
        {
            "label": "MEASURED",
            "what": "M1 resolver on the dev halves before any M3 change (baseline for growth)",
            "command": "uv run python scripts/m3_dev_baseline.py --out "
            + args.out.resolve().relative_to(ROOT).as_posix(),
            "config": {
                "split": "dev",
                "resolver": "M1: line resolver for parser lines; one exact key lookup for inputs",
                "labels": "model-labelled; inputs settled by the owner, see NOTICE.md",
                "table_rows": len(table.rows),
                "parser": parser,
                "inputs": inputs,
            },
            "seed": 0,
            "corpus_fingerprint": sheet["snapshot_sha256"],
            "arms": [],
            "metrics": [
                metric("mention_accuracy", int(parser["gold_groups"]), parser["mention_accuracy"]),
                metric("parser_precision", int(parser["pred_groups"]), parser["precision"]),
                metric("input_accuracy", int(inputs["n"]), inputs["input_accuracy"]),
            ],
            "comparisons": [],
            "environment": {},
        },
        ROOT,
    )


if __name__ == "__main__":
    main()
