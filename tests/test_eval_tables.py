"""eval_tables: hand-written expected markdown, plus the stale-doc check on the committed files."""

from pathlib import Path

from scripts.eval_tables import BEGIN, END, check, render, replace_block

ROOT = Path(__file__).resolve().parent.parent
G = {"sampler": "popularity", "d": 3}


def _m(name, arm, value, split="test"):
    return {"name": name, "arm": arm, "split": split, "group": G, "n": 10, "value": value}


def _c(metric, diff, lo, hi):
    return {
        "metric": metric,
        "a": "shipped",
        "b": "overlap",
        "split": "test",
        "group": G,
        "n": 10,
        "diff": diff,
        "ci": {"lo": lo, "hi": hi, "level": 0.95, "n_clusters": 4},
    }


DOC = {
    "label": "MEASURED",
    "commit": "0123456789abcdef",
    "dirty": False,
    "command": "python -m x --out results/t.json",
    "arms": [{"name": "overlap"}, {"name": "shipped"}],
    "metrics": [
        _m("recall_at_10", "overlap", 0.5),
        _m("mrr_at_10", "overlap", 0.25),
        _m("recall_at_10", "shipped", 0.75),
        _m("mrr_at_10", "shipped", 0.5),
        _m("recall_at_10", "shipped", 0.1, split="dev"),  # dev rows must not show
        _m("makeable_at_10", "overlap", 0.4),  # only shipped shows
        _m("makeable_at_10", "shipped", 0.9),
        _m("hit_rate", None, 0.8),
        _m("visible_rate", None, 0.6),
    ],
    "comparisons": [
        _c("mrr_at_10", 0.25, 0.1, 0.4),
        _c("recall_at_10", 0.25, -0.05, 0.55),
    ],
}

FOOT = (
    "*Label: MEASURED. Commit: 01234567. Dirty: no. "
    "Results: [t.json](../results/t.json). "
    "Rebuild: `python -m x --out results/t.json`.*"
)

BYCON = (
    "makeable_at_10 is high for `shipped` by construction: "
    "the shipped order lists recipes you can make now first."
)

EXPECTED = f"""### sampler=popularity, d=3

**Table 1. Recovery sanity check (role: sanity, never selects a model). Test split.**

| Arm | recall@10 | MRR@10 | n |
| --- | --- | --- | --- |
| overlap | 0.5000 | 0.2500 | 10 |
| shipped | 0.7500 | 0.5000 | 10 |

{FOOT}

**Table 2. Paired comparisons, a minus b. Test split.**

| a | b | Metric | Diff | 95% interval | Holds |
| --- | --- | --- | --- | --- | --- |
| shipped | overlap | mrr_at_10 | +0.2500 | [0.1000, 0.4000] | HOLDS |
| shipped | overlap | recall_at_10 | +0.2500 | [-0.0500, 0.5500] | no |

HOLDS means the interval excludes 0. Clusters: 4.

{FOOT}

**Table 3. Product metrics. Test split.**

| Metric | Arm | Value | n |
| --- | --- | --- | --- |
| makeable_at_10 | shipped | 0.9000 | 10 |
| hit_rate | all arms | 0.8000 | 10 |
| visible_rate | all arms | 0.6000 | 10 |

{BYCON}

{FOOT}
"""


def test_render_matches_hand_written_markdown():
    assert render(DOC, Path("results/t.json")) == EXPECTED


def test_replace_block_keeps_the_rest():
    text = f"top\n\n{BEGIN}\nold\n{END}\n\ntail\n"
    assert replace_block(text, "new\n") == f"top\n\n{BEGIN}\nnew\n{END}\n\ntail\n"


def test_committed_docs_are_fresh():
    msg = check(ROOT)
    assert msg is None, msg
