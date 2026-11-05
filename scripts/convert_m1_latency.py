"""One-off: rewrite results/m1_latency_*.json into results schema 1.

The original file content is kept under ``raw``. Every number is copied, not recomputed.
commit, dirty and seed come from the original file. Safe to run twice (converted files are skipped).
"""

from __future__ import annotations

import json
from pathlib import Path

from pantrychef.eval.results import dump_result

RESULTS = Path(__file__).resolve().parents[1] / "results"
NOTE = (
    "converted from the pre-schema file by scripts/convert_m1_latency.py; environment not recorded"
)
# The run files were dirty only because the old results/m1_latency.json was deleted
# (docs/PROJECT_STATE.md section 10).
RUN_DIRTY_PATHS = ["results/m1_latency.json"]


def convert(orig: dict) -> dict:
    metrics = []
    for size, s in orig["metrics"]["bySize"].items():
        for name, key in (
            ("latency_p50_ms", "p50"),
            ("latency_p95_ms", "p95"),
            ("latency_max_ms", "max"),
        ):
            metrics.append(
                {
                    "name": name,
                    "role": "latency",
                    "depends_on": [],
                    "arm": None,
                    "split": "all",
                    "n": s["n"],
                    "value": s[key],
                    "group": {"pantry_size": int(size)},
                }
            )
    return {
        "schema": 1,
        "label": orig["label"],
        "what": orig["what"],
        "command": orig["command"],
        "commit": orig["commit"],
        "dirty": orig["dirty"],
        "dirty_paths": RUN_DIRTY_PATHS if orig["dirty"] else [],
        "config": orig["config"],
        "seed": orig["seed"],
        "corpus_fingerprint": orig.get("pack", {}).get("corpus_fingerprint")
        or "none recorded (deployed bundle: " + orig.get("url", "unknown") + ")",
        "arms": [],
        "metrics": metrics,
        "comparisons": [],
        "environment": {"note": NOTE},
        "raw": orig,
    }


def main() -> None:
    for path in sorted(RESULTS.glob("m1_latency_*.json")):
        orig = json.loads(path.read_text(encoding="utf-8"))
        if orig.get("schema") == 1:
            print("skip (already converted)", path.name)
            continue
        dump_result(path, convert(orig))
        print("converted", path.name)


if __name__ == "__main__":
    main()
