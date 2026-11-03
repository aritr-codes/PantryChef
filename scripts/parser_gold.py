"""Parser gold set tools (M2). Run from the repo root.

  uv run python scripts/parser_gold.py check            # validate the labelling CSV
  uv run python scripts/parser_gold.py write            # write labels.dev/test.v1.json
  uv run python scripts/parser_gold.py score --split dev   # print dev scores (test is refused)

The labelling CSV is ``data/interim/parser_gold_labelling.csv`` (made by
``make_parser_gold_sheet.py``). Fill ``names``, ``optional`` and ``not_an_ingredient``. See
``pantrychef/eval/parser_gold.py`` for the label format. Do not copy resolver output into it.
Test labels stay unscored until M3 acceptance (plan D4), so ``score`` refuses ``--split test``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pantrychef.eval.parser_gold import read_labels_csv, score
from pantrychef.ingredients.table import IngredientTable

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "data/eval/parser_gold/sheet.v1.json"
CSV = ROOT / "data/interim/parser_gold_labelling.csv"
TABLE = ROOT / "data/ingredients/ingredients.csv"


def _labels() -> tuple[list[dict], dict]:
    lines = json.loads(SHEET.read_text(encoding="utf8"))["lines"]
    return lines, read_labels_csv(CSV, [r["id"] for r in lines])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "write", "score"])
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    args = ap.parse_args()
    lines, labels = _labels()
    if args.cmd == "check":
        print(f"ok: {len(labels)} labels")
    elif args.cmd == "write":
        for split in ("dev", "test"):
            out = {
                r["id"]: {
                    "groups": [list(g) for g in labels[r["id"]].groups],
                    "optional": labels[r["id"]].optional,
                    "not_an_ingredient": labels[r["id"]].not_an_ingredient,
                }
                for r in lines
                if r["split"] == split
            }
            path = ROOT / f"data/eval/parser_gold/labels.{split}.v1.json"
            path.write_text(
                json.dumps({"version": 1, "split": split, "labels": out}, indent=2) + "\n",
                encoding="utf8",
                newline="\n",
            )
            print(path.name, len(out))
    else:
        if args.split == "test":
            raise SystemExit("test labels stay unscored until M3 acceptance")
        table = IngredientTable.load(TABLE)
        sub = [r for r in lines if r["split"] == "dev"]
        print(json.dumps(score(sub, labels, table), indent=2))


if __name__ == "__main__":
    main()
