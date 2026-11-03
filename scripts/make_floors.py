"""Regenerate data/eval/floors.v1.json from a fixture-pack run (M2).

Floors guard against code regressions. They are NOT a quality claim. Run this only for a
deliberate, reviewed change of rule or config:  uv run python scripts/make_floors.py
"""

from __future__ import annotations

import json
from pathlib import Path

from pantrychef.eval.baseline_main import group_label, run

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/eval/floors.v1.json"
MARGIN = 0.05
CONFIG = {"d_values": [0, 3], "samplers": ["uniform", "popularity"], "seed": 42, "draws": 3}
PACK = "tests/fixtures/pack"
KEEP = {
    ("overlap", "recall_at_10"),
    ("overlap", "mrr_at_10"),
    ("idf_flat", "recall_at_10"),
    ("idf_flat", "mrr_at_10"),
    ("shipped", "recall_at_10"),
    ("shipped", "mrr_at_10"),
    ("shipped", "makeable_at_10"),
    (None, "visible_rate"),
}


def main() -> None:
    out = run(ROOT / PACK, resamples=100, **CONFIG)
    floors = [
        {
            "group": group_label(m["group"]),
            "split": m["split"],
            "arm": m["arm"],
            "name": m["name"],
            "n": m["n"],
            "observed": round(m["value"], 6),
            "floor": round(max(0.0, m["value"] - MARGIN), 4),
        }
        for m in out["metrics"]
        if (m["arm"], m["name"]) in KEEP
    ]
    doc = {
        "schema": 1,
        "pack": PACK,
        "config": CONFIG,
        "margin": MARGIN,
        "note": (
            "Floors = observed on the first fixture run minus margin. "
            "They guard against code regressions. They are not a quality claim."
        ),
        "floors": floors,
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf8", newline="\n")
    print(len(floors), "floors")


if __name__ == "__main__":
    main()
