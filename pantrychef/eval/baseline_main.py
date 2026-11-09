"""M2 rule baselines on a pack: ``python -m pantrychef.eval.baseline_main --pack DIR --out F``.

Every arm ranks the same candidate set (recipes with have >= 1). Sanity metrics (recall, MRR)
are leaky by design (ADR 0005) and never select a model. Product metrics describe what a person
sees. ``n`` is the number of pantries behind each number.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from pantrychef.engine import load_pack
from pantrychef.eval.arms import ARMS, CandidateIndex, order, visible_ids
from pantrychef.eval.metrics import hit_rate, makeable_at_k, mrr_at_k, recall_at_k
from pantrychef.eval.pantries import build_pantries
from pantrychef.eval.stats import paired_cluster_bootstrap

K = 10
PAIRS = (
    ("overlap", "random"),
    ("idf_flat", "overlap"),
    ("shipped", "idf_flat"),
    ("shipped", "overlap"),
)
COMPARED = ("mrr_at_10", "recall_at_10")
FEATURES = {
    "random": [],
    "overlap": ["have", "total"],
    "idf_flat": ["idf", "have", "total"],
    "shipped": ["idf", "have", "total", "group"],
}


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def group_label(group: dict) -> str:
    return f"sampler={group['sampler']},d={group['d']}"


def run(
    pack_dir,
    samplers: list[str] | None = None,
    d_values: list[int] | None = None,
    seed: int = 42,
    draws: int = 3,
    resamples: int = 10_000,
) -> dict:
    """Return ``{"metrics": [...], "comparisons": [...], ...}`` for one pack."""
    samplers = samplers or ["uniform", "popularity"]
    d_values = d_values if d_values is not None else [0, 3, 6]
    pack = load_pack(pack_dir)
    staples = set(pack.default_staples)
    index = CandidateIndex(pack, staples)
    metrics: list[dict] = []
    comparisons: list[dict] = []
    for sampler, d in [(s, d) for d in d_values for s in samplers if d > 0 or s == samplers[0]]:
        group = {"sampler": sampler if d > 0 else "none", "d": d}
        pantries = build_pantries(pack, sampler, d, seed, draws)
        # per[(split, arm, metric)] = list of per-pantry values; clusters[split] = gold ids
        per: dict[tuple[str, str, str], list[float]] = {}
        clusters: dict[str, list[str]] = {}
        visible: dict[str, list[float]] = {}
        for p in pantries:
            cands = index.candidates(set(p.pantry))
            clusters.setdefault(p.split, []).append(p.gold_id)
            visible.setdefault(p.split, []).append(float(p.gold_id in visible_ids(cands)))
            for arm in ARMS:
                scored = order(arm, cands, f"random-arm:{seed}:{p.gold_id}:{p.draw}")
                ranked = [c.recipe_id for c in scored]
                ht = [(c.have, c.total) for c in scored]
                vals = {
                    "recall_at_10": recall_at_k(ranked, p.gold_id, K),
                    "mrr_at_10": mrr_at_k(ranked, p.gold_id, K),
                    "makeable_at_10": makeable_at_k(ht, K),
                    "hit_rate": hit_rate(ht),
                }
                for name, v in vals.items():
                    per.setdefault((p.split, arm, name), []).append(v)
        for split in sorted(clusters):
            n = len(clusters[split])
            for arm in ARMS:
                for name in ("recall_at_10", "mrr_at_10", "makeable_at_10"):
                    metrics.append(
                        {
                            "name": name,
                            "arm": arm,
                            "split": split,
                            "group": group,
                            "n": n,
                            "value": _mean(per[(split, arm, name)]),
                        }
                    )
            # hit_rate does not depend on the order (all arms rank the same set), so report it once.
            metrics.append(
                {
                    "name": "hit_rate",
                    "arm": None,
                    "split": split,
                    "group": group,
                    "n": n,
                    "value": _mean(per[(split, "overlap", "hit_rate")]),
                }
            )
            metrics.append(
                {
                    "name": "visible_rate",
                    "arm": None,
                    "split": split,
                    "group": group,
                    "n": n,
                    "value": _mean(visible[split]),
                }
            )
            for a, b in PAIRS:
                for name in COMPARED:
                    va, vb = per[(split, a, name)], per[(split, b, name)]
                    iv = paired_cluster_bootstrap(
                        va, vb, clusters[split], resamples=resamples, seed=seed
                    )
                    comparisons.append(
                        {
                            "metric": name,
                            "a": a,
                            "b": b,
                            "split": split,
                            "group": group,
                            "n": n,
                            "diff": iv.mean,
                            "ci": {
                                "lo": iv.lo,
                                "hi": iv.hi,
                                "level": iv.level,
                                "method": iv.method,
                                "n_clusters": iv.n_clusters,
                            },
                        }
                    )
    return {
        "metrics": metrics,
        "comparisons": comparisons,
        "arms": [{"name": a, "features_used": FEATURES[a]} for a in ARMS],
        "config": {
            "samplers": samplers,
            "d_values": d_values,
            "draws": draws,
            "k": K,
            "resamples": resamples,
        },
        "seed": seed,
        "corpus_fingerprint": pack.info.corpus_fingerprint,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pantrychef.eval.baseline_main")
    ap.add_argument("--pack", required=True, help="folder holding core.v2.json[.gz]")
    ap.add_argument("--out", required=True, help="results/NAME.json")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)
    out = run(args.pack, seed=args.seed)
    from pantrychef.eval.results import write_result  # lane A

    doc = {
        "label": "MEASURED",
        "what": "M2 rule baselines (random, overlap, idf_flat, shipped), masked pantries",
        "command": "python -m pantrychef.eval.baseline_main " + shlex.join(argv or sys.argv[1:]),
        **out,
    }
    write_result(Path(args.out), doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
