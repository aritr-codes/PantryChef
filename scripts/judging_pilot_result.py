"""Write results/m2_judging_pilot.json from the judge answer files. Run from the repo root.

    uv run python scripts/judging_pilot_result.py --judge sonnet=PATH.csv --judge opus=PATH.csv

The judges in the M2 pilot were models, not people. The file says so. It is a test of the protocol,
not a selection result.
"""

from __future__ import annotations

import argparse
import csv
import json
from itertools import combinations
from pathlib import Path

from judging_score import score

from pantrychef.eval.results import write_result

ROOT = Path(__file__).resolve().parent.parent
KEY = ROOT / "data/interim/judging_key.pilot.v1.json"
SHEET_HASH = ROOT / "data/eval/judging/pilot_key_sha256.txt"


def _outcomes(key: dict, rows: list[dict]) -> dict[str, str]:
    items = key.get("items", key)
    pick = {"A": "left", "B": "right"}
    return {
        r["item_id"]: items[r["item_id"]][pick[r["choice"]]] if r["choice"] in pick else "tie"
        for r in rows
        if not items[r["item_id"]]["repeat_of"]
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="append", required=True, help="NAME=ANSWERS.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "results/m2_judging_pilot.json")
    args = ap.parse_args(argv)
    key = json.loads(KEY.read_text(encoding="utf-8"))
    scores, outcomes, metrics = {}, {}, []
    for spec in args.judge:
        name, path = spec.split("=", 1)
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        scores[name] = score(key, rows)
        outcomes[name] = _outcomes(key, rows)
        s = scores[name]
        decided = s["shipped_wins"] + s["overlap_wins"]
        if decided:
            metrics.append(
                {
                    "name": "pilot_pairwise_win_rate",
                    "arm": "shipped",
                    "split": "all",
                    "n": decided,
                    "value": s["win_rate_ties_excluded"],
                    "group": {"judge": name, "kind": "model"},
                }
            )
    agree = {
        f"{a}_{b}": sum(outcomes[a][i] == outcomes[b][i] for i in outcomes[a]) / len(outcomes[a])
        for a, b in combinations(outcomes, 2)
    }
    write_result(
        args.out,
        {
            "label": "MEASURED",
            "what": (
                "Pilot of the judging protocol (20 pantries, 4 repeats): shipped vs overlap lists. "
                "The judges were models, not people. This tests the protocol. It is not a result "
                "to select a model by"
            ),
            "command": "uv run python scripts/judging_pilot_result.py "
            + " ".join(f"--judge {s}" for s in args.judge),
            "config": {
                "judges": "model, each judge in two separate sessions, blind to arms and key",
                "key_sha256": SHEET_HASH.read_text(encoding="utf-8").strip(),
                "scores": scores,
                "outcome_agreement_between_judges": agree,
            },
            "seed": 42,
            "corpus_fingerprint": "data/eval/judging/pilot_sheet.v1.json (Wikibooks pack)",
            "arms": [],
            "metrics": metrics,
            "comparisons": [],
            "environment": {},
        },
        ROOT,
    )
    print(json.dumps({"agreement": agree}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
