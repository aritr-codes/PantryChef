"""M4 pools, exclusions, gold-out and the split-leak check (plan sections 5 and 4.2)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from pantrychef.engine import load_pack
from pantrychef.eval.arms import order
from pantrychef.eval.m4_pools import (
    POOL_SIZES,
    VARIANTS,
    VariantScorer,
    build_pools,
    canonical,
    check_no_leak,
    content_sha256,
    pack_core_sha256,
    pilot_exclusions,
    top5_agreement,
    usable_pantries,
)
from pantrychef.eval.pantries import _group_key

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/pack"
SIZES = (("pilot", 2), ("dev", 4), ("futility", 3), ("reserve", 2))
M4 = ROOT / "data/eval/m4"
PANTRIES = M4 / "pantries.v1.json"
TRAIN = M4 / "train_table.v1.json"
WEIGHTS = ROOT / "web/src/rank_model.v1.json"


@pytest.fixture(scope="module")
def pack():
    return load_pack(FIXTURE)


def write_spike(tmp_path, golds):
    p = tmp_path / "spike.json"
    pantries = [
        {"id": f"pilot{i}", "source_recipe_id": g, "names": []} for i, g in enumerate(golds)
    ]
    pantries.append({"id": "new01", "source": "spike_writer", "names": ["x"]})  # no gold
    p.write_text(json.dumps({"pantries": pantries}), encoding="utf-8")
    return p


@pytest.fixture(scope="module")
def built(pack, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("spike")
    base = usable_pantries(pack, "test", set(), set())
    golds = [base[0]["pantry"].gold_id, base[1]["pantry"].gold_id]
    spike = write_spike(tmp, golds)
    doc, stats = build_pools(pack, pack_core_sha256(FIXTURE), spike, SIZES)
    return doc, stats, golds, spike


def test_shape_and_pool_sizes(built):
    doc, _, _, _ = built
    assert set(doc) >= {"version", "pack_core_sha256", "salt", "pools"}
    assert doc["salt"] == "m4"
    assert {k: len(v) for k, v in doc["pools"].items() if k != "test"} == dict(SIZES)
    p = doc["pools"]["dev"][0]
    assert set(p) == {"pantry_id", "gold_id", "title_group", "pantry", "content_sha256"}
    assert p["pantry_id"] == f"m4-dev-{p['gold_id']}"
    assert doc["pools"]["test"][0]["pantry_id"].startswith("m4-test-")
    assert p["content_sha256"] == content_sha256(p["pantry"])


def test_pilot_golds_and_their_title_groups_are_excluded(pack, built):
    doc, stats, golds, spike = built
    ex_golds, ex_groups = pilot_exclusions(spike, pack)  # the `new01` entry adds nothing
    assert ex_golds == set(golds)
    assert ex_groups == {_group_key(r) for r in pack.recipes if r.recipe_id in golds}
    rows = [r for v in doc["pools"].values() for r in v]
    assert not ex_golds & {r["gold_id"] for r in rows}
    assert not ex_groups & {r["title_group"] for r in rows}
    assert stats["excluded_golds"] == 2


def test_gold_out_removes_gold_and_its_title_group(pack):
    for split in ("dev", "test"):
        for it in usable_pantries(pack, split, set(), set()):
            ids = {c.recipe_id for c in it["cands"]}
            group = {r.recipe_id: _group_key(r) for r in pack.recipes}
            assert it["pantry"].gold_id not in ids
            assert all(group[i] != it["title_group"] for i in ids)
            assert len(ids) >= 5


def test_usable_needs_enough_candidates(pack):
    all_n = len(usable_pantries(pack, "dev", set(), set(), 1))
    assert len(usable_pantries(pack, "dev", set(), set(), 10_000)) == 0
    assert len(usable_pantries(pack, "dev", set(), set(), 5)) <= all_n


def test_dev_and_test_title_groups_are_disjoint(built):
    doc, _, _, _ = built
    pools = doc["pools"]
    dev = {r["title_group"] for k in ("pilot", "dev", "futility", "reserve") for r in pools[k]}
    assert not dev & {r["title_group"] for r in pools["test"]}


def test_pool_order_follows_the_order_key(built):
    doc, _, _, _ = built
    rows = doc["pools"]["pilot"] + doc["pools"]["dev"] + doc["pools"]["futility"]
    keys = [hashlib.sha256(f"42:m4:{r['gold_id']}".encode()).hexdigest() for r in rows]
    assert keys == sorted(keys)
    tkeys = [
        hashlib.sha256(f"42:m4:{r['gold_id']}".encode()).hexdigest() for r in doc["pools"]["test"]
    ]
    assert tkeys == sorted(tkeys)


def test_deterministic_and_no_duplicates(pack, built):
    doc, stats, _, spike = built
    again, _ = build_pools(pack, pack_core_sha256(FIXTURE), spike, SIZES)
    assert canonical(doc) == canonical(again)
    assert b"\r" not in canonical(doc) and b"\x00" not in canonical(doc)
    assert stats["duplicates"] == []


def test_pack_hash_is_pinned(built):
    doc, _, _, _ = built
    assert (
        doc["pack_core_sha256"]
        == hashlib.sha256((FIXTURE / "core.v2.json").read_bytes()).hexdigest()
    )


def test_pool_sizes_are_one_named_constant_set():
    """The owner chose 100 dev pantries on 2026-11-19 (the timing pilot gave 30 s per item)."""
    assert POOL_SIZES == (("pilot", 10), ("dev", 100), ("futility", 20), ("reserve", 10))


def test_the_pilot_pool_does_not_depend_on_the_later_pool_sizes(pack, built):
    """The pilot items are the first of the fixed order, so a bigger dev pool leaves them as is."""
    _, _, _, spike = built
    small, _ = build_pools(pack, pack_core_sha256(FIXTURE), spike, (("pilot", 2), ("dev", 1)))
    big, _ = build_pools(pack, pack_core_sha256(FIXTURE), spike, (("pilot", 2), ("dev", 9)))
    assert canonical(small["pools"]["pilot"]) == canonical(big["pools"]["pilot"])
    assert small["pools"]["dev"] == big["pools"]["dev"][:1]  # dev starts at the same place
    assert canonical(small["pools"]["test"]) == canonical(big["pools"]["test"])


# What the committed draw must keep when the dev pool grows (2026-11-19). The pilot sheet, its
# key hash and its answers are committed and bound to these pilot pantries. MEASURED values of
# the draw as committed at HEAD 328733e.
PILOT_POOL_SHA = "6fa082b2939d3779c5d3882bec8852254552673a98242c2129e65e6321958049"
TEST_POOL_SHA = "3e6ec4ed1ab4fed6df538ad1e3f1e6bcbd9adf55bad35a47ed968cb72461fcce"
PACK_SHA = "1c2bcf5a0ac31813e9e08279c7729830c0658474a4d7fed8c8bfd1a94379a313"


@pytest.mark.skipif(not PANTRIES.exists(), reason="the pantry draw is not in this checkout")
def test_committed_draw_keeps_pilot_test_pack_and_has_the_new_sizes():
    doc = json.loads(PANTRIES.read_text(encoding="utf-8"))
    pools = doc["pools"]
    assert {k: len(v) for k, v in pools.items() if k != "test"} == dict(POOL_SIZES)
    assert hashlib.sha256(canonical(pools["pilot"])).hexdigest() == PILOT_POOL_SHA
    assert hashlib.sha256(canonical(pools["test"])).hexdigest() == TEST_POOL_SHA
    assert doc["pack_core_sha256"] == PACK_SHA
    sha_file = (M4 / "test_pantries_sha256.txt").read_text(encoding="utf-8").strip()
    assert sha_file == TEST_POOL_SHA
    rows = [r for v in pools.values() for r in v]
    assert len({r["content_sha256"] for r in rows}) == len(rows)  # no duplicate content
    assert len({r["gold_id"] for r in rows}) == len(rows)
    dev = {r["title_group"] for k in POOL_NAMES_DEV for r in pools[k]}
    assert not dev & {r["title_group"] for r in pools["test"]}
    assert not set(doc["excluded"]["gold_ids"]) & {r["gold_id"] for r in rows}
    assert not set(doc["excluded"]["title_groups"]) & {r["title_group"] for r in rows}


POOL_NAMES_DEV = ("pilot", "dev", "futility", "reserve")


@pytest.mark.skipif(
    not (ROOT / "data/interim/judging_key.m4-pilot.v1.json").exists() or not PANTRIES.exists(),
    reason="the private pilot key is not in this checkout",
)
def test_the_committed_pilot_key_still_sits_inside_the_pilot_pool():
    key = json.loads((ROOT / "data/interim/judging_key.m4-pilot.v1.json").read_text("utf-8"))
    doc = json.loads(PANTRIES.read_text(encoding="utf-8"))
    pilot_ids = {r["pantry_id"] for r in doc["pools"]["pilot"]}
    assert {v["pantry_id"] for v in key["items"].values()} <= pilot_ids
    assert key["pack_core_sha256"] == doc["pack_core_sha256"]


REAL_PACK = os.environ.get("PANTRYCHEF_REAL_PACK")


@pytest.mark.skipif(
    not REAL_PACK
    or not (Path(REAL_PACK) / "core.v2.json.gz").exists()
    or not (M4 / "key_sha256.pilot.txt").exists(),
    reason="set PANTRYCHEF_REAL_PACK and keep the committed pilot key hash",
)
def test_the_committed_pilot_key_hash_still_reproduces_from_the_committed_draw():
    """CRUCIAL (2026-11-19): the dev pool grew from 60 to 100. The pilot sheet, its key hash and
    its answers are committed, so the new draw must rebuild the very same pilot key."""
    from scripts import judging_sheet as sj

    doc = json.loads(PANTRIES.read_text(encoding="utf-8"))
    pack = load_pack(REAL_PACK)
    arms = ("overlap", "shipped", "idf_flat")  # the order of the committed key
    _, key = sj.build_pool_sheet(
        pack, doc["pools"]["pilot"], arms, seed=42, name="pilot", take=10, repeats=4,
        config={"pool": "pilot", "pack_core_sha256": doc["pack_core_sha256"],
                "model_sha256": None, "arm_guess": False},
    )  # fmt: skip
    got = hashlib.sha256((json.dumps(key, indent=2, sort_keys=True) + "\n").encode()).hexdigest()
    assert got == (M4 / "key_sha256.pilot.txt").read_text(encoding="utf-8").strip()


def test_variants_shipped_matches_arm_order_and_agreement_is_valid(pack):
    items = usable_pantries(pack, "dev", set(), set())
    sc = VariantScorer(pack)
    for it in items:
        cands = it["cands"]  # already gold-out and at most 2 missing
        want = [c.recipe_id for c in order("shipped", cands)[:5]]
        got = sc.top5(set(it["pantry"].pantry), it["title_group"])
        assert got["shipped"] == want
    agree = top5_agreement(pack, items)
    assert set(agree) == set(VARIANTS)
    for a in agree.values():
        assert a["n"] == len(items)
        assert 0 <= a["identical"] <= a["mean_shared"] <= 1


# ---- the leak check (plan 5.4) ----


def tiny_doc():
    def row(split, n):
        return {
            "pantry_id": f"m4-{split}-g{n}",
            "gold_id": f"g{n}",
            "title_group": f"t{n}",
            "pantry": [f"i{n}"],
            "content_sha256": content_sha256([f"i{n}"]),
        }

    return {
        "pools": {
            "pilot": [row("dev", 1)],
            "dev": [row("dev", 2)],
            "futility": [row("dev", 3)],
            "reserve": [row("dev", 4)],
            "test": [row("test", 5), row("test", 6)],
        }
    }


def trained_on(rows):
    ids = sorted({r["pantry_id"] for r in rows})
    return {"pantries_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest()}


def test_leak_check_passes_on_clean_tiny_fixture():
    rows = [{"pantry_id": "m4-dev-g1"}, {"pantry_id": "m4-dev-g2"}]
    assert check_no_leak(tiny_doc(), rows, trained_on(rows)) == []


def test_leak_check_fails_on_planted_test_pantry():
    rows = [{"pantry_id": "m4-dev-g1"}, {"pantry_id": "m4-test-g5"}]
    bad = check_no_leak(tiny_doc(), rows, trained_on(rows))
    assert any("test pantry in training" in b for b in bad)


def test_leak_check_fails_on_planted_title_group_futility_and_hash():
    rows = [{"pantry_id": "m4-dev-g3", "title_group": "t5"}]
    bad = check_no_leak(tiny_doc(), rows, {"pantries_sha256": "0" * 64})
    assert any("futility" in b for b in bad)
    assert any("title group" in b for b in bad)
    assert any("pantries_sha256" in b for b in bad)


def test_leak_check_fails_on_shared_group_and_pilot_gold():
    doc = tiny_doc()
    doc["pools"]["dev"][0]["title_group"] = "t5"
    rows = [{"pantry_id": "m4-dev-g1"}]
    bad = check_no_leak(doc, rows, trained_on(rows), pilot_golds={"g2"})
    assert any("share a title group" in b for b in bad)
    assert any("pilot gold" in b for b in bad)


def test_leak_check_fails_when_a_dev_pantry_has_the_content_of_a_test_pantry():
    """RF6a: the same ingredient set in two pools, under different ids and golds."""
    doc = tiny_doc()
    doc["pools"]["dev"][0]["content_sha256"] = doc["pools"]["test"][0]["content_sha256"]
    rows = [{"pantry_id": "m4-dev-g1"}]
    bad = check_no_leak(doc, rows, trained_on(rows))
    assert any("same content" in b for b in bad), bad


def test_leak_check_fails_on_any_content_overlap_between_two_dev_pools():
    doc = tiny_doc()
    doc["pools"]["reserve"][0]["content_sha256"] = doc["pools"]["pilot"][0]["content_sha256"]
    rows = [{"pantry_id": "m4-dev-g1"}]
    assert any("same content" in b for b in check_no_leak(doc, rows, trained_on(rows)))


def test_leak_check_fails_when_a_pool_gold_sits_in_a_pilot_title_group():
    """RF6b: a pantry whose gold is a different recipe of a pilot recipe's title group."""
    doc = tiny_doc()
    doc["excluded"] = {"gold_ids": ["pilot-gold"], "title_groups": ["t2"]}  # t2 is a dev group
    rows = [{"pantry_id": "m4-dev-g1"}]
    bad = check_no_leak(doc, rows, trained_on(rows))
    assert any("pilot title group" in b for b in bad), bad
    doc["pools"]["dev"][0]["gold_id"] = "pilot-gold"  # and the pilot gold itself, from the doc
    assert any("pilot gold" in b for b in check_no_leak(doc, rows, trained_on(rows)))


def test_leak_check_fails_when_the_weights_name_another_training_table():
    """RF6c: trained_on.train_table_sha256 must equal the sha256 of the table file's bytes."""
    rows = [{"pantry_id": "m4-dev-g1"}, {"pantry_id": "m4-dev-g2"}]
    ok = {**trained_on(rows), "train_table_sha256": "ab" * 32}
    assert check_no_leak(tiny_doc(), rows, ok, table_sha256="ab" * 32) == []
    bad = check_no_leak(tiny_doc(), rows, ok, table_sha256="cd" * 32)
    assert any("train_table_sha256" in b for b in bad)
    assert any(
        "train_table_sha256" in b
        for b in check_no_leak(tiny_doc(), rows, trained_on(rows), table_sha256="x")
    )  # the weights name no table at all


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_test_pantries_absent_from_training():
    missing = [str(p.relative_to(ROOT)) for p in (PANTRIES, TRAIN, WEIGHTS) if not p.exists()]
    if missing:
        pytest.skip(f"not written yet (M4 step 8): {', '.join(missing)}")
    doc = json.loads(PANTRIES.read_text(encoding="utf-8"))
    table = json.loads(TRAIN.read_text(encoding="utf-8"))
    rows = table["rows"] if isinstance(table, dict) else table
    trained = json.loads(WEIGHTS.read_text(encoding="utf-8"))["trained_on"]
    spike = ROOT / "data/eval/graph_spike/pantries.v1.json"
    pilot = {
        p["source_recipe_id"]
        for p in json.loads(spike.read_text(encoding="utf-8"))["pantries"]
        if p.get("source_recipe_id")
    }
    assert check_no_leak(doc, rows, trained, pilot, table_sha256=sha256_of(TRAIN)) == []


def test_training_writers_and_leak_check_agree_on_formats(tmp_path):
    """Seam 5: lane C's table, its pantries hash and its weights file pass lane B's check."""
    import math

    import numpy as np

    from pantrychef.eval import pairwise as pw
    from pantrychef.rank import FEATURES

    def row(split, n):
        return {
            "pantry_id": f"m4-{split}-g{n}", "gold_id": f"g{n}", "title_group": f"t{n}",
            "pantry": [f"i{n}"], "content_sha256": content_sha256([f"i{n}"]),
        }  # fmt: skip

    dev = [row("dev", n) for n in range(40)]
    doc = {
        "pools": {"pilot": dev[:5], "dev": dev[5:35], "futility": dev[35:], "reserve": [],
                  "test": [row("test", 100), row("test", 101)]},
    }  # fmt: skip
    rng = np.random.default_rng(0)
    w = np.zeros(len(FEATURES))
    w[:2] = (2.0, -1.0)
    items = []
    for r in dev[:35]:  # pilot and dev pantries; the futility pantries stay out
        for k in range(3):
            z = rng.normal(size=len(FEATURES))
            y = int(rng.random() < 1 / (1 + math.exp(-float(w @ z))))
            items.append(
                pw.PairItem(r["pantry_id"], f"{r['pantry_id']}-{k}", "A", "B", y, tuple(z))
            )
    out = pw.run_train(
        items, weights_path=tmp_path / "w.json", table_path=tmp_path / "t.json",
        comparator="shipped", commit="abc", Cs=(0.1, 1.0), seed=0,
    )  # fmt: skip
    assert out["weights_written"]
    table = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    trained = json.loads((tmp_path / "w.json").read_text(encoding="utf-8"))["trained_on"]
    rows = table["rows"] if isinstance(table, dict) else table
    assert check_no_leak(doc, rows, trained, table_sha256=sha256_of(tmp_path / "t.json")) == []
    planted = [*rows, {"pantry_id": "m4-test-g100"}]
    assert any("test pantry in training" in b for b in check_no_leak(doc, planted, trained))
    # the hash is over sorted distinct ids joined by newline, utf8, no trailing newline
    ids = sorted({r["pantry_id"] for r in rows})
    assert trained["pantries_sha256"] == hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()
    assert trained["pantries_sha256"] == pw.pantries_sha256(ids)
