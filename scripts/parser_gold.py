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

from pantrychef.eval.parser_gold import Label, read_labels_csv, score
from pantrychef.ingredients.table import IngredientTable

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "data/eval/parser_gold/sheet.v1.json"
CSV = ROOT / "data/interim/parser_gold_labelling.csv"
TABLE = ROOT / "data/ingredients/ingredients.csv"


def _labels() -> tuple[list[dict], dict]:
    lines = json.loads(SHEET.read_text(encoding="utf8"))["lines"]
    return lines, read_labels_csv(CSV, [r["id"] for r in lines])


def _committed_labels(split: str) -> dict[str, Label]:
    """Labels from the committed JSON, so a fresh checkout can score without the work CSV."""
    path = ROOT / f"data/eval/parser_gold/labels.{split}.v1.json"
    raw = json.loads(path.read_text(encoding="utf8"))["labels"]
    return {
        k: Label(tuple(tuple(g) for g in v["groups"]), v["optional"], v["not_an_ingredient"])
        for k, v in raw.items()
    }


def _write_result(out: Path, scores: dict) -> None:
    from pantrychef.eval.results import write_result

    metrics = [
        {
            "name": f"parser_{k}",
            "arm": None,
            "split": "dev",
            "n": int(scores[d]),
            "value": float(scores[k]),
        }
        for k, d in (("precision", "pred_groups"), ("recall", "gold_groups"), ("f1", "gold_groups"))
    ]
    metrics.append(
        {
            "name": "parser_optional_accuracy",
            "arm": None,
            "split": "dev",
            "n": int(scores["optional_n"]),
            "value": float(scores["optional_accuracy"]),
        }
    )
    write_result(
        out,
        {
            "label": "MEASURED",
            "what": "Ingredient parser vs the parser gold set, dev half, group-level micro scores",
            "command": "uv run python scripts/parser_gold.py score --split dev --out "
            + out.resolve().relative_to(ROOT).as_posix(),
            "config": {
                "split": "dev",
                "labels": "model-labelled, see data/eval/parser_gold/NOTICE.md",
                **scores,
            },
            "seed": 0,
            "corpus_fingerprint": json.loads(SHEET.read_text(encoding="utf8"))["snapshot_sha256"],
            "arms": [],
            "metrics": metrics,
            "comparisons": [],
            "environment": {},
        },
        ROOT,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "write", "score"])
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--out", type=Path, help="write a results file (score only)")
    args = ap.parse_args()
    if args.cmd == "score":
        lines = json.loads(SHEET.read_text(encoding="utf8"))["lines"]
        labels = _committed_labels(args.split)
    else:
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
        scores = score(sub, labels, table)
        print(json.dumps(scores, indent=2))
        if args.out:
            _write_result(args.out, scores)


if __name__ == "__main__":
    main()
