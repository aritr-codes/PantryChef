"""CI floor for the rule baselines on the fixture pack.

Floors guard against code regressions (a broken mask rule, sampler, arm or order key). They are
NOT a quality claim: the fixture has 47 recipes and the masked-recovery task is leaky (ADR 0005).

Floors come from the first fixture run minus a margin of 0.05. Each entry in
``data/eval/floors.v1.json`` stores the observed value, n and the floor. Floors cover the
``overlap``, ``idf_flat`` and ``shipped`` arms (recall_at_10, mrr_at_10), ``shipped``
makeable_at_10 and visible_rate, on both splits, with d in {0, 3} and both samplers.
``hit_rate`` is left out: all arms rank the same candidate set, so it is equal across arms.
Regenerate the file only for a deliberate, reviewed change of rule or config.
"""

from __future__ import annotations

import json
from pathlib import Path

from pantrychef.eval.baseline_main import group_label, run

ROOT = Path(__file__).resolve().parents[2]


def test_fixture_metrics_stay_above_floors():
    doc = json.loads((ROOT / "data" / "eval" / "floors.v1.json").read_text(encoding="utf8"))
    cfg = doc["config"]
    out = run(
        ROOT / doc["pack"],
        samplers=cfg["samplers"],
        d_values=cfg["d_values"],
        seed=cfg["seed"],
        draws=cfg["draws"],
        resamples=100,
    )
    got = {(group_label(m["group"]), m["split"], m["arm"], m["name"]): m for m in out["metrics"]}
    assert doc["floors"]
    for f in doc["floors"]:
        m = got[(f["group"], f["split"], f["arm"], f["name"])]
        assert m["n"] == f["n"], f
        assert m["value"] >= f["floor"], (f, m["value"])
