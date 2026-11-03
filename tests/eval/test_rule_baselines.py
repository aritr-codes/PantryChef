"""Rule baselines on RecipeNLG: tests use ONLY invented recipes (no RecipeNLG text, ADR 0003)."""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from pantrychef.eval import rule_baselines_main as rb
from pantrychef.eval.metrics import mrr_at_k, recall_at_k
from pantrychef.eval.results import load_result

ROOT = Path(__file__).resolve().parents[2]


def _hand() -> rb.Index:
    return rb.Index(
        [
            {"recipe_id": "r0", "canonical": ["a", "b", "c"]},
            {"recipe_id": "r1", "canonical": ["a", "b"]},
            {"recipe_id": "r2", "canonical": ["a", "d", "e", "f"]},
            {"recipe_id": "r3", "canonical": ["b", "c", "d"]},
        ]
    )


def _ids(index: rb.Index, names: list[str]) -> list[int]:
    # vocab ids follow first appearance: a0 b1 c2 d3 e4 f5
    return [ord(n) - ord("a") for n in names]


def test_hand_overlap_order():
    ix = _hand()
    # pantry {a,b}: have r0=2/3, r1=2/2, r2=1/4, r3=1/3. Order (-have, total, id).
    assert ix.order(_ids(ix, ["a", "b"]), "overlap") == [1, 0, 3, 2]


def test_hand_idf_flat_order_and_scores():
    ix = _hand()
    # N=4, df a=3 b=3 c=2 d=2 e=1 f=1; idf = ln(1+4/df)
    ia, ic, ie = math.log(7 / 3), math.log(3), math.log(5)
    assert ix.idf[0] == pytest.approx(ia)
    # pantry {c,e}: r0 has c, r3 has c, r2 has e. All have=1.
    # overlap: totals 3,3,4 -> r0, r3, r2.  idf_flat scores:
    s0 = ic / math.sqrt(ia + ia + ic)  # r0 = a,b,c   -> 1.0986/1.6713 = 0.6573
    s3 = ic / math.sqrt(ia + ic + ic)  # r3 = b,c,d   -> 1.0986/1.7449 = 0.6296
    s2 = ie / math.sqrt(ia + ic + ie + ie)  # r2 = a,d,e,f -> 1.6094/2.2726 = 0.7082
    assert s2 > s0 > s3
    p = _ids(ix, ["c", "e"])
    assert ix.order(p, "overlap") == [0, 3, 2]
    assert ix.order(p, "idf_flat") == [2, 0, 3]
    assert ix.ranks(p, 2)[:2] == (3, 1)
    assert ix.ranks(p, 3)[:2] == (2, 3)


def test_ranks_match_brute_force():
    ix = _hand()
    for pantry in ([0, 1], [2, 4], [0, 5], [3]):
        for arm, pos in (("overlap", 0), ("idf_flat", 1)):
            order = ix.order(pantry, arm)
            for gold in order:
                assert ix.ranks(pantry, gold)[pos] == order.index(gold) + 1
                assert ix.ranks(pantry, gold)[2] == len(order)


def _corpus(n: int = 40) -> list[dict]:
    """Invented recipes over 25 invented ingredient words, 2 to 7 ingredients each."""
    rng = random.Random(7)
    words = [f"zorb{i:02d}" for i in range(25)]
    out = []
    for i in range(n):
        out.append({"recipe_id": f"r{i}", "canonical": rng.sample(words, 2 + i % 6)})
    return out


def test_golds_distractors_candidates():
    corpus = _corpus()
    ix = rb.Index(corpus)
    qs = rb.select_queries(ix, 100, 42)
    assert all(ix.total[g] >= 3 for g in qs)
    assert len(qs) == int(sum(ix.total >= 3))
    dist = rb.Distractors(ix)
    for g in qs:
        gold_set = set(ix.ingredients(g))
        for draw in range(3):
            kept, masked, rng = rb.mask_pantry(ix, g, 42, draw)
            assert len(masked) == (len(gold_set) + 2) // 4 and not set(kept) & set(masked)
            for sampler in rb.SAMPLERS:
                for d in (3, 6):
                    extra = dist.draw(sampler, random.Random(f"{g}{draw}{d}"), gold_set, d)
                    assert len(set(extra)) == d and not set(extra) & gold_set
                    ov, idf, c = ix.ranks(kept + extra, g)  # raises if gold not a candidate
                    assert 1 <= ov <= c and 1 <= idf <= c
    with pytest.raises(ValueError):
        dist.draw("uniform", random.Random(1), set(range(ix.v - 2)), 3)


def test_query_set_is_hash_ordered_and_capped():
    ix = rb.Index(_corpus())
    a = rb.select_queries(ix, 10, 42)
    assert len(a) == 10 and a == rb.select_queries(ix, 10, 42)
    assert a != rb.select_queries(ix, 10, 43)


def test_run_metrics_agree_with_metrics_module():
    ix = rb.Index(_corpus())
    g = rb.select_queries(ix, 5, 42)[0]
    kept, _, _ = rb.mask_pantry(ix, g, 42, 0)
    ov, _, _ = ix.ranks(kept, g)
    ranked = [str(x) for x in ix.order(kept, "overlap")]
    assert recall_at_k(ranked, str(g), 10) == (1.0 if ov <= 10 else 0.0)
    assert mrr_at_k(ranked, str(g), 10) == (1 / ov if ov <= 10 else 0.0)


def _write_corpus(path: Path) -> None:
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in _corpus()), encoding="utf-8", newline="\n"
    )


def test_output_validates_and_is_deterministic(tmp_path):
    corpus = tmp_path / "c.jsonl"
    _write_corpus(corpus)
    outs = []
    for k, hashseed in enumerate(("0", "12345")):
        out = tmp_path / f"r{k}.json"
        env = {**os.environ, "PYTHONHASHSEED": hashseed}
        subprocess.run(
            [sys.executable, "-m", "pantrychef.eval.rule_baselines_main", "--corpus", str(corpus),
             "--out", str(out), "--n-queries", "30", "--resamples", "200",
             "--csv-sha256", "synthetic", "--quiet"],
            cwd=ROOT, env=env, check=True, capture_output=True,
        )  # fmt: skip
        doc = load_result(out)  # validates schema, registry roles and arms
        doc["raw"].pop("seconds")
        for k2 in ("command", "dirty", "dirty_paths", "commit"):
            doc.pop(k2)
        outs.append(doc)
    assert outs[0] == outs[1]
    doc = outs[0]
    assert doc["corpus_fingerprint"] == "synthetic"
    assert {m["split"] for m in doc["metrics"]} == {"test"}
    assert {(m["arm"], m["name"]) for m in doc["metrics"]} == {
        (a, n) for a in rb.ARM_NAMES for n in rb.METRIC_NAMES
    }
    assert len(doc["comparisons"]) == 5 * 2 * 2  # configs x pairs x metrics
    assert len(doc["raw"]["query_ids_sha256"]) == 64
