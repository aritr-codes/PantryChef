"""Score a judging answers CSV against the private key. See docs/JUDGING_PROTOCOL.md.

    uv run python scripts/judging_score.py --answers FILE.csv [--key KEY.json]

CSV columns: item_id, choice (A = left list, B = right list, or tie),
would_cook_left (yes|no), would_cook_right (yes|no), seconds.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path

Z = 1.96  # two-sided 95% normal quantile
HALF_WIDTH = 0.1  # an interval of width 0.2


def power_estimate(p: float, tie_rate: float) -> dict:
    """ESTIMATE of the pantries needed for a 95% interval of width 0.2 on the win rate.

    Normal approximation. Non-tie pantries n = Z^2 * p * (1 - p) / HALF_WIDTH^2.
    Pantries = n / (1 - tie_rate). The worst case uses p = 0.5, because p from a small pilot
    is noisy.
    """

    def need(q: float) -> int:
        return math.ceil(Z * Z * q * (1 - q) / HALF_WIDTH**2)

    def total(n: int) -> int | None:
        return None if tie_rate >= 1 else math.ceil(n / (1 - tie_rate))

    n, w = need(p), need(0.5)
    return {
        "non_tie_needed": n,
        "pantries_needed": total(n),
        "worst_non_tie_needed": w,
        "worst_pantries_needed": total(w),
    }


def _yes(v: str) -> bool:
    v = v.strip().lower()
    if v not in ("yes", "no"):
        raise ValueError(f"expected yes or no, got {v!r}")
    return v == "yes"


def score(key: dict, rows: list[dict]) -> dict:
    """Win rate of shipped over overlap, self-consistency on repeats, tie rate, median time.

    Win rate, tie rate and would-cook use the base items (not the repeats), so a pantry
    counts once. ``key`` maps item_id to ``{left, right, repeat_of}``.
    """
    items = key.get("items", key)
    outcome: dict[str, str] = {}  # item_id -> "shipped" | "overlap" | "tie"
    cook = {"shipped": [], "overlap": []}
    seconds = []
    for r in rows:
        iid = r["item_id"]
        if iid not in items:
            raise ValueError(f"unknown item_id {iid!r}")
        k = items[iid]
        choice = r["choice"].strip()
        if choice not in ("A", "B", "tie"):
            raise ValueError(f"choice must be A, B or tie, got {choice!r}")
        outcome[iid] = {"A": k["left"], "B": k["right"], "tie": "tie"}[choice]
        if r["seconds"].strip():  # a model judge cannot time itself, so blank is allowed
            seconds.append(float(r["seconds"]))
        if not k["repeat_of"]:
            cook[k["left"]].append(_yes(r["would_cook_left"]))
            cook[k["right"]].append(_yes(r["would_cook_right"]))
    if 0 < len(seconds) < len(rows):
        raise ValueError("seconds is blank for some items and set for others")
    missing = sorted(set(items) - set(outcome))
    if missing:
        raise ValueError(f"no answer for {missing}")
    base = [i for i, k in items.items() if not k["repeat_of"]]
    sw = sum(outcome[i] == "shipped" for i in base)
    ow = sum(outcome[i] == "overlap" for i in base)
    ties = len(base) - sw - ow
    reps = [(i, k["repeat_of"]) for i, k in items.items() if k["repeat_of"]]
    tie_rate = ties / len(base)
    rate = sw / (sw + ow) if sw + ow else None
    return {
        "n_base": len(base),
        "shipped_wins": sw,
        "overlap_wins": ow,
        "ties": ties,
        "win_rate_ties_excluded": rate,
        "win_rate_ties_as_half": (sw + 0.5 * ties) / len(base),
        "tie_rate": tie_rate,
        "repeats_same": sum(outcome[a] == outcome[b] for a, b in reps),
        "repeats_total": len(reps),
        "median_seconds": statistics.median(seconds) if seconds else None,
        "would_cook_shipped": sum(cook["shipped"]) / len(cook["shipped"]),
        "would_cook_overlap": sum(cook["overlap"]) / len(cook["overlap"]),
        "power": power_estimate(rate, tie_rate) if rate is not None else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", required=True)
    ap.add_argument("--key", default="data/interim/judging_key.pilot.v1.json")
    args = ap.parse_args(argv)
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    with open(args.answers, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(json.dumps(score(key, rows), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
