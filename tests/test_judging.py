"""Judging pilot: hand-computed scoring on a 6-item key, and sheet-builder properties."""

import json
from pathlib import Path

import pytest

from pantrychef.engine import load_pack
from scripts.judging_score import power_estimate, score
from scripts.judging_sheet import build_sheet, write_outputs

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "pack"

# i5 repeats i1 and i6 repeats i2. Left/right arms per item.
KEY = {
    "i1": {"left": "shipped", "right": "overlap", "repeat_of": None},
    "i2": {"left": "overlap", "right": "shipped", "repeat_of": None},
    "i3": {"left": "shipped", "right": "overlap", "repeat_of": None},
    "i4": {"left": "overlap", "right": "shipped", "repeat_of": None},
    "i5": {"left": "overlap", "right": "shipped", "repeat_of": "i1"},
    "i6": {"left": "shipped", "right": "overlap", "repeat_of": "i2"},
}
# (choice, would_cook_left, would_cook_right, seconds)
ANS = {
    "i1": ("A", "yes", "no", 10),  # left = shipped wins
    "i2": ("A", "yes", "yes", 20),  # left = overlap wins
    "i3": ("B", "yes", "no", 30),  # right = overlap wins
    "i4": ("tie", "no", "yes", 40),  # tie
    "i5": ("B", "no", "yes", 50),  # right = shipped wins (same as i1)
    "i6": ("A", "yes", "no", 60),  # left = shipped wins (i2 was overlap)
}
ROWS = [
    {
        "item_id": i,
        "choice": c,
        "would_cook_left": wl,
        "would_cook_right": wr,
        "seconds": str(s),
    }
    for i, (c, wl, wr, s) in ANS.items()
]


def test_score_hand_computed():
    r = score(KEY, ROWS)
    # Base items i1..i4: shipped wins 1 (i1), overlap wins 2 (i2, i3), tie 1 (i4).
    assert r["n_base"] == 4 and r["arms"] == ["overlap", "shipped"]
    pr = r["pairs"]["overlap_vs_shipped"]
    assert (pr["a_wins"], pr["b_wins"], pr["ties"], pr["n"]) == (2, 1, 1, 4)
    assert pr["win_rate_a"] == pytest.approx(2 / 3)
    assert pr["net_preference"] == pytest.approx(1 / 4)  # (2 - 1) / 4, overlap minus shipped
    assert pr["win_rate_ties_as_half"] == pytest.approx(2.5 / 4)
    assert r["tie_rate"] == pytest.approx(0.25)
    # Repeats: (i1,i5) both shipped = same. (i2,i6) overlap vs shipped = different.
    assert (r["repeats_same"], r["repeats_total"]) == (1, 2)
    assert r["median_seconds"] == 35  # 10,20,30,40,50,60
    # Would cook, base items. Shipped side: i1 L yes, i2 R yes, i3 L yes, i4 R yes = 4/4.
    # Overlap side: i1 R no, i2 L yes, i3 R no, i4 L no = 1/4.
    assert r["would_cook"]["shipped"] == pytest.approx(1.0)
    assert r["would_cook"]["overlap"] == pytest.approx(0.25)
    # Exact power for the observed tie rate (not the normal approximation).
    assert [row["n"] for row in r["power"]] == [40, 60, 80, 100]


def test_blank_seconds_give_no_median():
    rows = [{**r, "seconds": ""} for r in ROWS]
    assert score(KEY, rows)["median_seconds"] is None


def test_partly_blank_seconds_are_refused():
    rows = [dict(r) for r in ROWS]
    rows[0]["seconds"] = ""
    with pytest.raises(ValueError):
        score(KEY, rows)


def test_power_estimate_hand_computed():
    # p = 1/3: 1.96^2 * (2/9) / 0.1^2 = 85.37 -> 86 non-tie pantries; 86 / 0.75 = 114.7 -> 115.
    # Worst case p = 0.5: 1.96^2 * 0.25 / 0.01 = 96.04 -> 97 non-tie; 97 / 0.75 = 129.3 -> 130.
    p = power_estimate(1 / 3, 0.25)
    assert (p["non_tie_needed"], p["pantries_needed"]) == (86, 115)
    assert (p["worst_non_tie_needed"], p["worst_pantries_needed"]) == (97, 130)
    assert power_estimate(0.5, 1.0)["pantries_needed"] is None


def test_score_rejects_unknown_item_and_bad_choice():
    with pytest.raises(ValueError):
        score(KEY, [{**ROWS[0], "item_id": "zz"}])
    with pytest.raises(ValueError):
        score(KEY, [{**ROWS[0], "choice": "C"}])


@pytest.fixture(scope="module")
def built():
    pack = load_pack(FIXTURE)
    return build_sheet(pack, seed=42, n=6, repeats=2, d=3)


def test_sheet_is_blind_and_shaped(built):
    sheet, key = built
    text = json.dumps(sheet)
    assert len(sheet["items"]) == 8 == len(key["items"])
    for word in ("shipped", "overlap", "gold", "repeat"):
        assert word not in text
    for it in sheet["items"]:
        assert len(it["left"]) == len(it["right"]) == 5
        assert it["pantry"] == sorted(it["pantry"]) and all(
            isinstance(x, str) for x in it["pantry"]
        )
        for rec in it["left"] + it["right"]:
            assert set(rec) == {"title", "missing"}


def test_repeats_same_pantry_not_adjacent(built):
    sheet, key = built
    ids = [it["item_id"] for it in sheet["items"]]
    reps = {i: v["repeat_of"] for i, v in key["items"].items() if v["repeat_of"]}
    assert len(reps) == 2
    for rep, orig in reps.items():
        a, b = ids.index(rep), ids.index(orig)
        assert abs(a - b) >= 2
        by_id = {it["item_id"]: it for it in sheet["items"]}
        assert by_id[rep]["pantry"] == by_id[orig]["pantry"]
        assert key["items"][rep]["gold_id"] == key["items"][orig]["gold_id"]
    # base items use distinct gold recipes
    base = [v["gold_id"] for v in key["items"].values() if not v["repeat_of"]]
    assert len(set(base)) == 6


def test_sheet_is_deterministic(built):
    again = build_sheet(load_pack(FIXTURE), seed=42, n=6, repeats=2, d=3)
    assert again == built


def test_key_hash_is_pinned(built, tmp_path):
    sheet, key = built
    s, k, h = tmp_path / "s.json", tmp_path / "k.json", tmp_path / "h.txt"
    write_outputs(sheet, key, s, k, h)
    import hashlib

    assert h.read_text().strip() == hashlib.sha256(k.read_bytes()).hexdigest()
    write_outputs(sheet, key, s, k, h)  # same key: fine
    key2 = {**key, "seed": 43}
    with pytest.raises(SystemExit):
        write_outputs(sheet, key2, s, k, h)


# ---------------------------------------------------------------------------- M4 sheet tools

import gzip  # noqa: E402
import hashlib  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

from pantrychef.eval.arms import order  # noqa: E402
from pantrychef.eval.pantries import _group_key, _title_key, build_pantries  # noqa: E402
from scripts import judging_sheet as sj  # noqa: E402

ARMS3 = ("shipped", "overlap", "idf_flat")


def _pool(pack, split, k):
    """Pool records in the shape of data/eval/m4/pantries.v1.json (plan 8.3)."""
    by_id = {r.recipe_id: r for r in pack.recipes}
    out = []
    for p in build_pantries(pack, "popularity", 3, 42):
        if p.split != split or p.draw != 0:
            continue
        out.append(
            {
                "pantry_id": f"m4-{split}-{p.gold_id}",
                "gold_id": p.gold_id,
                "title_group": _group_key(by_id[p.gold_id]),
                "pantry": list(p.pantry),
                "content_sha256": hashlib.sha256(",".join(sorted(p.pantry)).encode()).hexdigest(),
            }
        )
    return out[:k]


@pytest.fixture(scope="module")
def fxpack():
    return load_pack(FIXTURE)


@pytest.fixture(scope="module")
def dev8(fxpack):
    return _pool(fxpack, "dev", 8)


@pytest.fixture(scope="module")
def m4(fxpack, dev8):
    return sj.build_pool_sheet(fxpack, dev8, ARMS3, seed=42, name="dev", repeats=3, min_gap=3)


def test_three_arms_give_three_items_per_pantry_every_pair_once(m4, dev8):
    sheet, key = m4
    base = [v for v in key["items"].values() if not v["repeat_of"]]
    skipped = key["skipped_pairs"]  # RF1: a same-set pair is recorded, not shown
    assert len(base) + len(skipped) == 3 * len(dev8) and len(sheet["items"]) == len(base) + 3
    want = [("idf_flat", "overlap"), ("idf_flat", "shipped"), ("overlap", "shipped")]
    for p in dev8:
        mine = [v for v in base if v["pantry_id"] == p["pantry_id"]]
        pairs = [tuple(sorted((v["left"], v["right"]))) for v in mine]
        pairs += [tuple(sorted(d["pair"])) for d in skipped if d["pantry_id"] == p["pantry_id"]]
        assert sorted(pairs) == want  # every unordered pair once, shown or recorded
    text = json.dumps(sheet)
    for word in (*ARMS3, "gold", "repeat", "probe", "m4-dev"):
        assert word not in text


@pytest.mark.parametrize("gap", [3, 4])
def test_items_of_one_pantry_sit_min_gap_apart(fxpack, dev8, gap):
    sheet, key = sj.build_pool_sheet(
        fxpack, dev8, ARMS3, seed=7, name="dev", repeats=3, min_gap=gap
    )
    where: dict[str, list[int]] = {}
    for pos, it in enumerate(sheet["items"]):
        where.setdefault(key["items"][it["item_id"]]["pantry_id"], []).append(pos)
    for pid, ps in where.items():
        assert all(b - a >= gap for a, b in zip(ps, ps[1:], strict=False)), pid


def test_pool_sheet_is_deterministic_and_seeded_by_name(fxpack, dev8, m4):
    assert sj.build_pool_sheet(fxpack, dev8, ARMS3, seed=42, name="dev", repeats=3) == m4
    assert sj.build_pool_sheet(fxpack, dev8, ARMS3, seed=42, name="dev2", repeats=3) != m4


def test_neutral_order_sorts_by_folded_title_then_id(m4):
    sheet, _ = m4
    for it in sheet["items"]:
        for side in ("left", "right"):
            titles = [r["title"].casefold() for r in it[side]]
            assert titles == sorted(titles)


def _rev(cands, pantry):  # the same 5 recipes as shipped, in the opposite order
    return order("shipped", cands)[:5][::-1]


def test_same_set_pairs_are_dropped_from_a_neutral_sheet_and_recorded(fxpack, dev8):
    """RF1: with neutral order the judge sees the same list twice, so the pair carries nothing."""
    kw = {"seed": 1, "name": "n", "orderers": {"twin": _rev}, "repeats": 2}
    arms = ("shipped", "twin", "overlap")
    sheet, key = sj.build_pool_sheet(fxpack, dev8[:4], arms, **kw)
    assert all(it["left"] != it["right"] for it in sheet["items"])  # no identical-looking item
    shown = {frozenset((v["left"], v["right"])) for v in key["items"].values()}
    assert frozenset(("shipped", "twin")) not in shown
    dropped = [d for d in key["skipped_pairs"] if d["pair"] == ["shipped", "twin"]]
    assert {d["pantry_id"] for d in dropped} == {p["pantry_id"] for p in dev8[:4]}
    base = [v for v in key["items"].values() if not v["repeat_of"]]
    assert len(base) + len(key["skipped_pairs"]) == 3 * 4  # every pair is shown or recorded
    assert any(v["repeat_of"] for v in key["items"].values())  # repeats still work


def test_without_neutral_order_a_reordered_pair_is_still_shown(fxpack, dev8):
    kw = {"seed": 1, "name": "n", "orderers": {"twin": _rev}, "neutral_order": False}
    sheet, key = sj.build_pool_sheet(fxpack, dev8[:3], ("shipped", "twin"), **kw)
    assert len(sheet["items"]) == 3 and key["skipped_pairs"] == []
    assert any(it["left"] != it["right"] for it in sheet["items"])


def test_a_dev_sheet_with_only_same_set_pairs_is_empty_not_a_blind_pair(fxpack, dev8):
    sheet, key = sj.build_pool_sheet(
        fxpack, dev8[:3], ("shipped", "twin"), seed=1, name="n", orderers={"twin": _rev}
    )
    assert sheet["items"] == [] and len(key["skipped_pairs"]) == 3


def test_gold_out_removes_gold_and_its_title_group(fxpack, dev8):
    def group_shown(**kw):
        sheet, key = sj.build_pool_sheet(fxpack, dev8, ARMS3, seed=42, name="dev", **kw)
        group = {p["pantry_id"]: p["title_group"] for p in dev8}
        return [
            group[key["items"][it["item_id"]]["pantry_id"]]
            in {_title_key(r["title"]) for r in it["left"] + it["right"]}
            for it in sheet["items"]
        ]

    assert not any(group_shown())  # default: gold-out on
    assert any(group_shown(gold_out=False))  # the control: without it the gold shows up


@pytest.fixture(scope="module")
def sibpack(tmp_path_factory):
    """The fixture pack plus a same-title sibling (upper case) of its first 20 recipes."""
    import copy

    core = json.loads((FIXTURE / "core.v2.json").read_text(encoding="utf-8"))
    for r in core["recipes"][:20]:
        sib = copy.deepcopy(r)
        sib.update(id=r["id"] + "-b", title=r["title"].upper(), page=r["page"] + "_b")
        core["recipes"].append(sib)
    d = tmp_path_factory.mktemp("sibpack")
    with gzip.open(d / "core.v2.json.gz", "wb") as fh:
        fh.write(json.dumps(core).encode("utf-8"))
    return load_pack(d)


def _group_shown(pack, pool, **kw):
    sheet, key = sj.build_pool_sheet(pack, pool, ARMS3, seed=42, name="dev", **kw)
    group = {p["pantry_id"]: p["title_group"] for p in pool}
    return [
        group[key["items"][it["item_id"]]["pantry_id"]]
        in {_title_key(r["title"]) for r in it["left"] + it["right"]}
        for it in sheet["items"]
    ]


def test_gold_out_drops_a_same_title_sibling_and_a_gold_only_mutation_is_caught(
    sibpack, monkeypatch
):
    """RI8: the pack has two recipes with one normalised title. Removing only the gold id would
    leave the sibling in the lists. This test must see that."""
    pool = _pool(sibpack, "dev", 40)
    assert any(
        p["gold_id"].endswith("-b") or p["gold_id"] + "-b" in {r.recipe_id for r in sibpack.recipes}
        for p in pool
    )
    assert not any(_group_shown(sibpack, pool))  # the real rule: the whole title group is out
    from pantrychef.eval import m4_lists

    gold_only = lambda group_of, gold, group: {gold}  # noqa: E731  the mutation
    monkeypatch.setattr(sj, "excluded_ids", gold_only)
    monkeypatch.setattr(m4_lists, "excluded_ids", gold_only)
    assert any(_group_shown(sibpack, pool))  # the sibling shows, so the check above would fail


def test_test_pool_skips_identical_lists_and_records_them(fxpack):
    pool = _pool(fxpack, "test", 12)
    kw = {"seed": 3, "name": "test", "take": 5, "skip_identical": True}
    sheet, key = sj.build_pool_sheet(fxpack, pool, ("shipped", "overlap"), **kw)
    assert len(sheet["items"]) == 5 and key["skipped"] == []

    def same(cands, pantry):
        return order("shipped", cands)[:5]

    with pytest.raises(ValueError, match="need 5"):  # every pair is identical: nothing usable
        sj.build_pool_sheet(fxpack, pool, ("shipped", "twin"), orderers={"twin": same}, **kw)
    with pytest.raises(ValueError, match="need 5"):  # same SET, other order: nothing usable (RF1)
        sj.build_pool_sheet(fxpack, pool, ("shipped", "twin"), orderers={"twin": _rev}, **kw)

    # "mixed" copies shipped on its first call (the first pantry) only: that pantry is skipped
    first = pool[0]["pantry_id"]
    calls = []

    def mixed(cands, pantry):
        calls.append(1)
        return order("shipped", cands) if len(calls) == 1 else order("overlap", cands)

    _, key = sj.build_pool_sheet(
        fxpack, pool, ("shipped", "mixed"), orderers={"mixed": mixed}, **kw
    )
    assert key["skipped"] == [first]
    assert first not in {v["pantry_id"] for v in key["items"].values()}


def test_probes_are_marked_and_come_from_dev(fxpack):
    test, dev = _pool(fxpack, "test", 6), _pool(fxpack, "dev", 6)
    sheet, key = sj.build_pool_sheet(
        fxpack, test, ("shipped", "overlap"), seed=5, name="test", take=6,
        probe_pantries=dev, probes=2, probe_arms=("shipped", "idf_flat"),
    )  # fmt: skip
    probes = {i: v for i, v in key["items"].items() if v["probe"]}
    assert len(sheet["items"]) == 8 and len(probes) == 2
    assert {v["pantry_id"] for v in probes.values()} == {p["pantry_id"] for p in dev[:2]}
    assert all({v["left"], v["right"]} == {"shipped", "idf_flat"} for v in probes.values())


# -- the model arm uses the real pantrychef.rank API (M4 integration, seam 1)


def _weights(tmp_path, w):
    from pantrychef.rank import FEATURES

    p = tmp_path / "model.json"
    p.write_text(json.dumps({"version": 1, "features": list(FEATURES), "weights": w}))
    return p


def test_model_arm_with_score_only_weights_gives_the_idf_flat_lists(fxpack, dev8, tmp_path):
    model = _weights(tmp_path, [1.0] + [0.0] * 7)
    orderers = sj._model_orderers(fxpack, ("shipped", "rank_linear"), str(model))
    kw = {"seed": 9, "name": "d", "repeats": 2}
    got, key = sj.build_pool_sheet(
        fxpack, dev8, ("shipped", "rank_linear"), orderers=orderers, **kw
    )
    want, _ = sj.build_pool_sheet(fxpack, dev8, ("shipped", "idf_flat"), **kw)
    assert got == want  # same 5 recipes, same neutral order, same sides
    assert {v["left"] for v in key["items"].values()} | {
        v["right"] for v in key["items"].values()
    } == {
        "shipped",
        "rank_linear",
    }


def test_model_arm_respects_gold_out(fxpack, dev8, tmp_path):
    model = _weights(tmp_path, [1.0] + [0.0] * 7)
    orderers = sj._model_orderers(fxpack, ("shipped", "rank_linear"), str(model))
    sheet, key = sj.build_pool_sheet(
        fxpack, dev8, ("shipped", "rank_linear"), seed=1, name="d", orderers=orderers
    )
    group = {p["pantry_id"]: p["title_group"] for p in dev8}
    for it in sheet["items"]:
        shown = {_title_key(r["title"]) for r in it["left"] + it["right"]}
        assert group[key["items"][it["item_id"]]["pantry_id"]] not in shown


def test_model_arm_needs_a_model_file(fxpack):
    with pytest.raises(SystemExit, match="--model"):
        sj._model_orderers(fxpack, ("shipped", "rank_linear"), None)
    assert sj._model_orderers(fxpack, ("shipped", "overlap"), None) == {}


def test_short_pool_raises(fxpack):
    with pytest.raises(ValueError, match="need 99"):
        sj.build_pool_sheet(fxpack, _pool(fxpack, "dev", 3), ARMS3, seed=1, name="d", take=99)


# -- the pack and the freeze


def _gz(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pack_hash_mismatch_refuses(tmp_path):
    digest = _gz(tmp_path / "core.v2.json.gz", b"{}")
    sj.check_pack_hash(tmp_path, digest)
    with pytest.raises(SystemExit, match="pack"):
        sj.check_pack_hash(tmp_path, "0" * 64)


def _git(root, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root, check=True, capture_output=True,
    )  # fmt: skip


@pytest.fixture
def frozen(tmp_path):
    """A tiny repo: one frozen file and a pack core, committed; the freeze (pairwise shape) is
    written but not committed. Returns ``(root, pack_core)``."""
    from pantrychef.eval import pairwise as pw

    _git(tmp_path, "init", "-q")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "frozen.py").write_text("x = 1\n", newline="\n")
    (tmp_path / "pool.txt").write_text("poolhash\n", newline="\n")
    pack = tmp_path / "core.v2.json.gz"
    pack_sha = _gz(pack, b"{}")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    freeze = pw.build_freeze(
        tmp_path, files=("scripts/frozen.py",), test_pool_file="pool.txt", pack_core=pack,
        pinned_pack_sha256=pack_sha, comparator="shipped", n_test=100, seed=42,
    )  # fmt: skip
    pw.write_freeze(tmp_path / sj.FREEZE, freeze)
    return tmp_path, pack


def test_freeze_file_has_one_shape_the_sheet_and_the_scorer_share(frozen):
    root, _ = frozen
    freeze = json.loads((root / sj.FREEZE).read_text())
    assert set(freeze) == {
        "version", "files", "pack_core_sha256", "test_pool_sha256", "comparator", "n_test",
        "seed", "commit",
    }  # fmt: skip
    assert list(freeze["files"]) == ["scripts/frozen.py"]


def test_test_sheet_refuses_without_a_committed_freeze(frozen):
    root, pack = frozen
    with pytest.raises(SystemExit, match="freeze"):
        sj.check_freeze(root, pack)  # the freeze exists but is not committed
    (root / sj.FREEZE).unlink()
    with pytest.raises(SystemExit, match="freeze"):
        sj.check_freeze(root, pack)  # no freeze file at all


def test_test_sheet_accepts_a_clean_matching_freeze(frozen):
    root, pack = frozen
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "freeze")
    sj.check_freeze(root, pack)


def test_test_sheet_refuses_a_changed_frozen_file_dirty_tree_or_pack(frozen):
    root, pack = frozen
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "freeze")
    pack.write_bytes(b"other")
    with pytest.raises(SystemExit, match="pack"):
        sj.check_freeze(root, pack)  # the pack differs from the frozen hash
    _gz(pack, b"{}")  # gzip of the same bytes is the same file again
    (root / "scripts" / "frozen.py").write_text("x = 2\n", newline="\n")
    with pytest.raises(SystemExit, match="clean"):
        sj.check_freeze(root, pack)  # dirty tree
    _git(root, "commit", "-q", "-am", "edit after freeze")
    with pytest.raises(SystemExit, match="frozen.py"):
        sj.check_freeze(root, pack)  # clean tree, but the frozen hash no longer matches


# -- the CLI


@pytest.fixture
def cli(tmp_path, monkeypatch, fxpack):
    """A tmp repo root with a hashed gzip copy of the fixture pack and a pantries file."""
    pack_dir = tmp_path / "pack"
    digest = _gz(pack_dir / "core.v2.json.gz", (FIXTURE / "core.v2.json").read_bytes())
    pools = {k: _pool(fxpack, "dev", 6) for k in ("pilot", "dev", "futility", "reserve")}
    pools["test"] = _pool(fxpack, "test", 12)
    pf = tmp_path / "data/eval/m4/pantries.v1.json"
    pf.parent.mkdir(parents=True)
    pf.write_text(
        json.dumps({"version": 1, "pack_core_sha256": digest, "salt": "m4", "pools": pools})
    )
    monkeypatch.setattr(sj, "ROOT", tmp_path)
    return tmp_path, pack_dir, pf


def _run(pack_dir, pf, *extra):
    return sj.main(["--pack", str(pack_dir), "--pantries", str(pf), *extra])


def test_cli_dev_sheet_writes_files_and_a_template(cli):
    root, pack_dir, pf = cli
    rc = _run(
        pack_dir, pf, "--pool", "dev", "--take", "4", "--arms", *ARMS3, "--name", "dev",
        "--repeats", "2",
    )  # fmt: skip
    assert rc == 0
    sheet = json.loads((root / "data/eval/m4/sheet.dev.v1.json").read_text())
    key_path = root / "data/interim/judging_key.m4-dev.v1.json"
    key = json.loads(key_path.read_text())
    assert len(sheet["items"]) == 3 * 4 - len(key["skipped_pairs"]) + 2
    sha = (root / "data/eval/m4/key_sha256.dev.txt").read_text().strip()
    assert sha == hashlib.sha256(key_path.read_bytes()).hexdigest()
    head = (root / "data/interim/answers_template.m4-dev.csv").read_text().splitlines()[0]
    assert head == "item_id,choice,strength,would_cook_left,would_cook_right,seconds,session"


def test_cli_out_dir_redirects_every_output(cli, tmp_path_factory):
    root, pack_dir, pf = cli
    out = tmp_path_factory.mktemp("out")
    rc = _run(
        pack_dir, pf, "--pool", "dev", "--take", "3", "--arms", *ARMS3, "--name", "dev",
        "--out-dir", str(out),
    )  # fmt: skip
    assert rc == 0
    made = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert made == [
        "data/eval/m4/key_sha256.dev.txt",
        "data/eval/m4/sheet.dev.v1.json",
        "data/interim/answers_template.m4-dev.csv",
        "data/interim/judging_key.m4-dev.v1.json",
    ]
    assert not (root / "data/interim").exists()  # nothing went to the repo root


def test_cli_refuses_a_different_pack(cli):
    _, pack_dir, pf = cli
    doc = json.loads(pf.read_text())
    doc["pack_core_sha256"] = "0" * 64
    pf.write_text(json.dumps(doc))
    with pytest.raises(SystemExit, match="pack"):
        _run(pack_dir, pf, "--pool", "dev", "--take", "3", "--arms", "shipped", "overlap",
             "--name", "dev")  # fmt: skip


def test_cli_arm_guess_is_for_the_test_pool_only(cli):
    _, pack_dir, pf = cli
    with pytest.raises(SystemExit, match="arm-guess"):
        _run(pack_dir, pf, "--pool", "dev", "--take", "3", "--arms", "shipped", "overlap",
             "--name", "dev", "--arm-guess")  # fmt: skip


def test_cli_test_pool_needs_the_freeze(cli):
    root, pack_dir, pf = cli
    (root / "model.json").write_text("{}")
    with pytest.raises(SystemExit, match="freeze"):
        _run(pack_dir, pf, "--pool", "test", "--take", "3", "--arms", "shipped", "overlap",
             "--name", "test", "--model", str(root / "model.json"))  # fmt: skip


def test_cli_refuses_to_switch_off_neutral_order_or_gold_out_on_an_m4_pool(cli):
    """RI4: the M4 keys record both as true. The flags exist only for the old M2 pilot."""
    _, pack_dir, pf = cli
    for flag in ("--no-neutral-order", "--no-gold-out"):
        with pytest.raises(SystemExit, match="neutral order|gold-out"):
            _run(pack_dir, pf, "--pool", "dev", "--take", "3", "--arms", *ARMS3, "--name", "dev",
                 flag)  # fmt: skip


WEIGHTS_VEC = [0.3, -1.5, 2.0, -0.7, 1.1, 0.9, -2.2, 1.4]  # mixed signs: lists differ from idf


@pytest.fixture
def tworld(cli):
    """The cli world plus weights, and a freeze for the test pool that is committed.

    The freeze pins the weights file, the pantries file, the test-pool hash, the comparator
    ``shipped``, ``n_test = 4`` and the seed. Returns ``(root, pack_dir, pf, weights_path)``.
    """
    from pantrychef.eval import pairwise as pw
    from pantrychef.eval.m4_pools import canonical
    from pantrychef.rank import FEATURES

    root, pack_dir, pf = cli
    w = root / pw.WEIGHTS_REL
    w.parent.mkdir(parents=True)
    w.write_text(json.dumps({"version": 1, "features": list(FEATURES), "weights": WEIGHTS_VEC}))
    doc = json.loads(pf.read_text())
    pool_sha = hashlib.sha256(canonical(doc["pools"]["test"])).hexdigest()
    (root / pw.TEST_POOL_FILE).write_text(pool_sha + "\n")
    (root / ".gitignore").write_text("pack/\n")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    freeze = pw.build_freeze(
        root, files=(pw.PANTRIES_REL, pw.WEIGHTS_REL), pack_core=pack_dir / "core.v2.json.gz",
        pinned_pack_sha256=doc["pack_core_sha256"], comparator="shipped", n_test=4, seed=42,
    )  # fmt: skip
    pw.write_freeze(root / sj.FREEZE, freeze)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "freeze")
    return root, pack_dir, pf, w


def _test_sheet(pack_dir, pf, w, **over):
    args = {"--pool": "test", "--take": "4", "--name": "test", "--model": str(w), "--seed": "42"}
    args.update(over)
    arms = args.pop("--arms", ["rank_linear", "shipped"])
    argv = ["--pack", str(pack_dir), "--pantries", str(over.pop("--pantries", pf))]
    for k, v in args.items():
        if k != "--pantries":
            argv += [k, v]
    return sj.main([*argv, "--arms", *arms])


def test_cli_builds_a_test_sheet_when_every_argument_matches_the_freeze(tworld):
    """The positive path of the test pool (RF7): --model, --arms, --take, --pantries, --seed."""
    root, pack_dir, pf, w = tworld
    assert _test_sheet(pack_dir, pf, w) == 0
    key = json.loads((root / "data/interim/judging_key.m4-test.v1.json").read_text())
    base = [v for v in key["items"].values() if not v["repeat_of"]]
    assert len(base) == 4 and key["pool"] == "test" and key["neutral_order"] and key["gold_out"]
    assert {a for v in base for a in (v["left"], v["right"])} == {"rank_linear", "shipped"}
    assert (root / "data/eval/m4/key_sha256.test.txt").is_file()


@pytest.mark.parametrize(
    "over,word",
    [
        ({"--take": "3"}, "take"),
        ({"--take": "5"}, "take"),
        ({"--arms": ["rank_linear", "idf_flat"]}, "arms"),
        ({"--arms": ["rank_linear", "shipped", "overlap"]}, "arms"),
        ({"--seed": "7"}, "seed"),
    ],
)
def test_cli_test_sheet_refuses_arguments_that_differ_from_the_freeze(tworld, over, word):
    root, pack_dir, pf, w = tworld
    with pytest.raises(SystemExit, match=word):
        _test_sheet(pack_dir, pf, w, **over)
    assert not (root / "data/eval/m4/key_sha256.test.txt").exists()


def test_cli_test_sheet_refuses_other_weights_or_another_pantries_file(tworld, tmp_path_factory):
    root, pack_dir, pf, w = tworld
    other_w = tmp_path_factory.mktemp("w") / "weights.json"
    d = json.loads(w.read_text())
    d["weights"] = [x + 0.5 for x in d["weights"]]
    other_w.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="model"):
        _test_sheet(pack_dir, pf, other_w)
    copy = tmp_path_factory.mktemp("p") / "pantries.v1.json"
    copy.write_text(pf.read_text() + "\n")  # the same pools, other bytes
    with pytest.raises(SystemExit, match="pantries"):
        _test_sheet(pack_dir, pf, w, **{"--pantries": copy})
    assert not (root / "data/eval/m4/key_sha256.test.txt").exists()


def test_cli_rejects_a_bad_number_of_arms(cli):
    _, pack_dir, pf = cli
    with pytest.raises(SystemExit):
        _run(pack_dir, pf, "--pool", "dev", "--arms", "shipped", "--name", "x")


# -- the old pilot call

REAL_PACK = os.environ.get("PANTRYCHEF_REAL_PACK")  # no silent fallback to build/pack


@pytest.mark.skipif(
    not REAL_PACK or not (Path(REAL_PACK) / "core.v2.json.gz").exists(),
    reason="set PANTRYCHEF_REAL_PACK to a folder with the real core.v2.json.gz (git ignores it)",
)
def test_old_pilot_call_still_gives_the_committed_key_hash():
    _, key = sj.build_sheet(load_pack(REAL_PACK))
    key_bytes = (json.dumps(key, indent=2, sort_keys=True) + "\n").encode("utf-8")
    sha_file = Path(__file__).resolve().parent.parent / "data/eval/judging/pilot_key_sha256.txt"
    assert hashlib.sha256(key_bytes).hexdigest() == sha_file.read_text().strip()


# ---------------------------------------------------------------------------- M4 scorer

from scripts import judging_score as js  # noqa: E402


def _k(left, right, rep=None, probe=False, pid="p"):
    return {"left": left, "right": right, "repeat_of": rep, "probe": probe, "pantry_id": pid}


# 3 arms, 3 pantries, 9 base items, 1 repeat (i10 repeats i1) and 1 drift probe (i11).
KEY3 = {
    "arms": ["shipped", "overlap", "idf_flat"],
    "items": {
        "i1": _k("shipped", "overlap", pid="p1"),
        "i2": _k("idf_flat", "shipped", pid="p1"),
        "i3": _k("overlap", "idf_flat", pid="p1"),
        "i4": _k("overlap", "shipped", pid="p2"),
        "i5": _k("shipped", "idf_flat", pid="p2"),
        "i6": _k("idf_flat", "overlap", pid="p2"),
        "i7": _k("shipped", "overlap", pid="p3"),
        "i8": _k("idf_flat", "shipped", pid="p3"),
        "i9": _k("overlap", "idf_flat", pid="p3"),
        "i10": _k("overlap", "shipped", rep="i1", pid="p1"),
        "i11": _k("shipped", "idf_flat", probe=True, pid="d1"),
    },
}
# item: (choice, strength, session). The winner is in the comment.
A3 = {
    "i1": ("A", "", "1"),  # shipped
    "i2": ("B", "", "1"),  # shipped
    "i3": ("B", "", "1"),  # idf_flat
    "i4": ("A", "", "1"),  # overlap
    "i5": ("tie", "", "1"),
    "i6": ("A", "2", "1"),  # idf_flat, clear
    "i7": ("A", "1", "2"),  # shipped, slight
    "i8": ("A", "1", "2"),  # idf_flat, slight
    "i9": ("tie", "", "2"),
    "i10": ("B", "", "2"),  # shipped (same as i1)
    "i11": ("A", "", "2"),  # shipped (probe)
}


def _rows3(strength=True, session=True):
    rows = []
    for n, (iid, (c, st, se)) in enumerate(A3.items(), start=1):
        r = {
            "item_id": iid,
            "choice": c,
            "would_cook_left": "yes" if iid == "i1" else "no",
            "would_cook_right": "no",
            "seconds": str(10 * n),
        }
        if strength:
            r["strength"] = st
        if session:
            r["session"] = se
        rows.append(r)
    return rows


def test_three_arm_pairs_hand_computed():
    r = js.score(KEY3, _rows3())
    assert r["n_base"] == 9 and r["arms"] == ["idf_flat", "overlap", "shipped"]
    assert r["tie_rate"] == pytest.approx(2 / 9)
    p = r["pairs"]["idf_flat_vs_overlap"]  # i3, i6 idf_flat; i9 tie
    assert (p["a_wins"], p["b_wins"], p["ties"], p["n"]) == (2, 0, 1, 3)
    assert p["net_preference"] == pytest.approx(2 / 3)
    assert p["win_rate_a"] == 1.0 and p["p_exact"] == pytest.approx(0.5)
    assert p["cp"][0] == pytest.approx(0.025**0.5, abs=1e-6) and p["cp"][1] == 1.0
    p = r["pairs"]["idf_flat_vs_shipped"]  # i2 shipped; i5 tie; i8 idf_flat
    assert (p["a_wins"], p["b_wins"], p["ties"]) == (1, 1, 1)
    assert p["win_rate_a"] == 0.5 and p["p_exact"] == 1.0 and p["net_preference"] == 0
    p = r["pairs"]["overlap_vs_shipped"]  # i1, i7 shipped; i4 overlap
    assert (p["a_wins"], p["b_wins"], p["ties"]) == (1, 2, 0)
    assert p["win_rate_a"] == pytest.approx(1 / 3) and p["net_preference"] == pytest.approx(-1 / 3)
    assert p["cp"] == pytest.approx((0.0084, 0.9057), abs=1e-3)  # CP interval for 1 of 3
    assert p["p_exact"] == 1.0
    assert (r["repeats_same"], r["repeats_total"]) == (1, 1)  # i10 repeats i1: both shipped
    assert r["median_seconds"] == 60
    assert r["would_cook"] == {"idf_flat": 0.0, "overlap": 0.0, "shipped": pytest.approx(1 / 6)}


def test_probes_never_count_in_the_primary_pairs():
    r = js.score(KEY3, _rows3())
    assert sum(p["n"] for p in r["pairs"].values()) == 9
    assert r["probes"] == [{"item_id": "i11", "pantry_id": "d1", "arms": ["idf_flat", "shipped"],
                            "outcome": "shipped"}]  # fmt: skip


def test_per_session_win_rates():
    r = js.score(KEY3, _rows3())
    s1, s2 = r["sessions"]["1"], r["sessions"]["2"]
    assert (s1["idf_flat_vs_overlap"]["a_wins"], s1["idf_flat_vs_overlap"]["b_wins"]) == (2, 0)
    assert (s1["idf_flat_vs_shipped"]["a_wins"], s1["idf_flat_vs_shipped"]["b_wins"]) == (0, 1)
    assert s1["idf_flat_vs_shipped"]["ties"] == 1
    assert s1["overlap_vs_shipped"]["win_rate_a"] == 0.5  # i1 shipped, i4 overlap
    assert s2["idf_flat_vs_shipped"]["win_rate_a"] == 1.0  # i8
    assert s2["overlap_vs_shipped"]["win_rate_a"] == 0.0  # i7
    assert s2["idf_flat_vs_overlap"]["win_rate_a"] is None  # i9 is a tie: no decided item
    assert "sessions" not in js.score(KEY3, _rows3(session=False))


def test_strength_column_blank_on_tie_ok_and_on_tie_fails():
    r = js.score(KEY3, _rows3())
    st = r["strength"]
    # signed toward the first arm of the pair. Blank on a decided item counts as missing.
    assert sorted(st["idf_flat_vs_shipped"]["scores"]) == [0, 1]  # i5 tie = 0, i8 +1; i2 missing
    assert st["idf_flat_vs_shipped"]["n_missing"] == 1
    assert sorted(st["idf_flat_vs_overlap"]["scores"]) == [0, 2]  # i9 tie 0, i6 +2; i3 missing
    assert st["overlap_vs_shipped"]["scores"] == [-1]  # i7 shipped slight; i1, i4 missing
    assert st["overlap_vs_shipped"]["n_missing"] == 2
    assert "strength" not in js.score(KEY3, _rows3(strength=False))
    rows = _rows3()
    rows[4]["strength"] = "1"  # i5 is a tie
    with pytest.raises(ValueError, match="tie"):
        js.score(KEY3, rows)
    rows = _rows3()
    rows[5]["strength"] = "3"
    with pytest.raises(ValueError, match="strength"):
        js.score(KEY3, rows)


def test_mixed_session_column_is_refused():
    rows = _rows3()
    rows[0]["session"] = ""
    with pytest.raises(ValueError, match="session"):
        js.score(KEY3, rows)


# A 2-arm test key: the model against the rule, 6 items, arm_guess on each. Registry arm names,
# because the result file validates them.
M, R = "rank_linear", "idf_flat"
KEYT = {
    "arms": [M, R],
    "items": {
        "j1": _k(M, R), "j2": _k(R, M), "j3": _k(M, R),
        "j4": _k(R, M), "j5": _k(M, R), "j6": _k(M, R),
    },
}  # fmt: skip
# item: (choice, arm_guess, would_cook_left, would_cook_right)
AT = {
    "j1": ("A", "left", "yes", "no"),  # model wins; guess right
    "j2": ("B", "left", "yes", "yes"),  # model wins; guess wrong
    "j3": ("B", "right", "no", "yes"),  # rule wins; guess wrong
    "j4": ("A", "right", "no", "no"),  # rule wins; guess right
    "j5": ("tie", "unsure", "yes", "no"),
    "j6": ("A", "left", "yes", "no"),  # model wins; guess right
}


def _rowst():
    return [
        {"item_id": i, "choice": c, "arm_guess": g, "would_cook_left": wl, "would_cook_right": wr,
         "seconds": "", "strength": "", "session": "1"}
        for i, (c, g, wl, wr) in AT.items()
    ]  # fmt: skip


def test_primary_test_analysis_hand_computed():
    r = js.score(KEYT, _rowst(), model_arm=M)
    p = r["primary"]
    assert (p["model"], p["rule"]) == (M, R)
    assert (p["W"], p["L"], p["T"], p["n"]) == (3, 2, 1, 6)
    assert p["win_rate"] == pytest.approx(0.6)
    assert p["cp"] == pytest.approx((0.1466, 0.9473), abs=1e-3)  # CP interval for 3 of 5
    assert p["gain"] == pytest.approx(0.1)
    assert p["gain_ci"] == pytest.approx((0.1466 - 0.5, 0.9473 - 0.5), abs=1e-3)
    assert p["p_exact"] == 1.0  # sign test, 3 of 5
    assert p["cp_lo_above_half"] is False
    assert p["tie_rate"] == pytest.approx(1 / 6)
    assert p["win_rate_ties_as_half"] == pytest.approx(3.5 / 6)
    assert p["worst_case_win_rate"] == pytest.approx(3 / 6)  # every tie goes to the rule
    assert p["net_preference"] == pytest.approx(1 / 6)  # (3 - 2) / 6


def test_arm_guess_accuracy_and_split_win_rates():
    g = js.score(KEYT, _rowst(), model_arm=M)["arm_guess"]
    assert (g["n_guessed"], g["n_right"], g["n_wrong"], g["n_unsure"]) == (5, 3, 2, 1)
    assert g["accuracy"] == pytest.approx(0.6)
    assert g["cp"] == pytest.approx((0.1466, 0.9473), abs=1e-3)
    assert g["unsure_share"] == pytest.approx(1 / 6)
    # model wins / losses among items where the guess was right (j1 W, j4 L, j6 W), wrong (j2 W,
    # j3 L) and unsure (j5 tie).
    assert (g["right"]["W"], g["right"]["L"]) == (2, 1)
    assert g["right"]["win_rate"] == pytest.approx(2 / 3)
    assert (g["wrong"]["W"], g["wrong"]["L"]) == (1, 1) and g["wrong"]["win_rate"] == 0.5
    assert (g["unsure"]["W"], g["unsure"]["L"]) == (0, 0) and g["unsure"]["win_rate"] is None
    assert "arm_guess" not in js.score(KEYT, _rowst())  # no model arm given: no analysis
    rows = _rowst()
    rows[0]["arm_guess"] = "middle"
    with pytest.raises(ValueError, match="arm_guess"):
        js.score(KEYT, rows, model_arm=M)


def test_secondary_would_cook_mcnemar_and_session_rates():
    r = js.score(KEYT, _rowst(), model_arm=M)
    w = r["secondary"]["would_cook"]
    # model yes and rule no: j1, j5, j6 (b = 3). Reverse: j3 (c = 1).
    assert (w["b"], w["c"]) == (3, 1)
    assert w["mean_diff"] == pytest.approx(2 / 6)
    assert w["p_mcnemar"] == pytest.approx(0.625)
    assert w["cp"] == pytest.approx((0.1943, 0.9937), abs=1e-3)  # CP interval for 3 of 4
    assert r["primary"]["sessions"]["1"]["win_rate"] == pytest.approx(0.6)


def test_model_arm_must_be_in_the_key():
    with pytest.raises(ValueError, match="model arm"):
        js.score(KEYT, _rowst(), model_arm="zzz")


def test_probe_agreement_between_dev_and_test_answers():
    test_key = {"items": {"t1": _k("shipped", "idf_flat", probe=True, pid="d1"),
                          "t2": _k("idf_flat", "shipped", probe=True, pid="d2")}}  # fmt: skip
    dev_key = {"items": {"a": _k("shipped", "idf_flat", pid="d1"),
                         "b": _k("shipped", "idf_flat", pid="d2")}}  # fmt: skip

    def rows(*cs):
        return [{"item_id": i, "choice": c} for i, c in zip(("t1", "t2"), cs, strict=True)]

    dev_rows = [{"item_id": "a", "choice": "A"}, {"item_id": "b", "choice": "A"}]
    # t1: test says A = shipped, dev says A = shipped: agree. t2: test says A = idf_flat, dev
    # says shipped: disagree.
    got = js.probe_agreement(test_key, rows("A", "A"), dev_key, dev_rows)
    assert got == {"n": 2, "agree": 1}


def test_power_table_rows_use_the_exact_method():
    rows = js.power_table(0.0)
    r40 = rows[0]
    assert (r40["n"], r40["decided"], r40["wins_needed"]) == (40, 40, 27)
    assert [round(r40[k], 2) for k in ("power_065", "power_070", "power_075")] == [0.44, 0.70, 0.9]
    assert r40["mdw"] == 0.725
    r100 = js.power_table(0.25)[3]
    assert (r100["n"], r100["decided"], r100["wins_needed"]) == (100, 75, 47)


def _write_scorer_inputs(tmp_path):
    import csv as csvmod

    key = {**KEYT, "pack_core_sha256": "ab" * 32, "neutral_order": True, "gold_out": True,
           "pool": "test"}  # fmt: skip
    kp, ap = tmp_path / "key.json", tmp_path / "ans.csv"
    kp.write_text(json.dumps(key))
    with open(ap, "w", newline="", encoding="utf-8") as f:
        w = csvmod.DictWriter(f, fieldnames=list(_rowst()[0]))
        w.writeheader()
        w.writerows(_rowst())
    return key, kp, ap


def test_result_doc_is_a_valid_result_file(tmp_path):
    from pantrychef.eval.results import load_result, write_result

    key, _, _ = _write_scorer_inputs(tmp_path)
    scored = js.score(key, _rowst(), model_arm=M)
    out = tmp_path / "results" / "m4_test.json"
    write_result(out, js.result_doc(key, scored, "cmd", "test", corpus_fingerprint="fp-1"))
    doc = load_result(out)
    assert doc["label"] == "MEASURED" and doc["seed"] == 42
    assert doc["corpus_fingerprint"] == "fp-1"  # RI7: the pack's own fingerprint
    win = next(m for m in doc["metrics"] if m["name"] == "pairwise_win_rate")
    assert (win["split"], win["arm"], win["n"]) == ("test", M, 5)
    assert win["value"] == pytest.approx(0.6) and win["ci"]["method"] == "clopper-pearson-exact"
    assert doc["comparisons"][0]["diff"] == pytest.approx(0.1)
    assert doc["config"]["n_test"] == 6


def test_scorer_main_prints_no_result_numbers(tmp_path, capsys):
    """RF3: the owner stays blind. main writes a file and prints at most the path."""
    _, kp, ap = _write_scorer_inputs(tmp_path)
    out = tmp_path / "scored.json"
    capsys.readouterr()
    rc = js.main(["--answers", str(ap), "--key", str(kp), "--out", str(out)])
    cap = capsys.readouterr()
    assert rc == 0 and cap.out == ""
    assert not any(ch.isdigit() for ch in cap.err.replace(str(out), ""))
    assert json.loads(out.read_text())["n_base"] == 6  # the numbers are in the file


def test_scorer_main_has_no_test_flag_and_needs_an_out_file(tmp_path, capsys):
    _, kp, ap = _write_scorer_inputs(tmp_path)
    with pytest.raises(SystemExit):
        js.main(["--answers", str(ap), "--key", str(kp), "--test", "--out", str(tmp_path / "o")])
    with pytest.raises(SystemExit):
        js.main(["--answers", str(ap), "--key", str(kp)])  # no --out: nothing to print to


@pytest.mark.parametrize("model", ["a_model", "z_model"])  # sorts first, then last
def test_primary_strength_is_signed_toward_the_model_whatever_the_arm_names(model):
    """RI5: +1 or +2 means the model list was preferred; the arm name order does not matter."""
    rule = "m_rule"
    rename = {M: model, R: rule}
    key = {
        "items": {i: _k(rename[k["left"]], rename[k["right"]]) for i, k in KEYT["items"].items()}
    }
    strong = {"j1": "2", "j2": "1", "j3": "1", "j4": "2", "j5": "", "j6": "1"}
    rows = [{**r, "strength": strong[r["item_id"]]} for r in _rowst()]
    st = js.score(key, rows, model_arm=model)["primary"]["strength"]
    # model wins: j1 (2), j2 (1), j6 (1). Rule wins: j3 (1), j4 (2). j5 is a tie (0).
    assert sorted(st["scores"]) == [-2, -1, 0, 1, 1, 2]
    assert sum(st["scores"]) == 1  # (2 + 1 + 1) - (1 + 2)
    assert st["mean"] == pytest.approx(1 / 6) and st["n_missing"] == 0
    assert "wilcoxon_p" in st
    # the per-pair block is unchanged: signed toward the first arm of the sorted pair
    pair = next(iter(js.score(key, rows, model_arm=model)["strength"].values()))
    first = sorted([model, rule])[0]
    assert sum(pair["scores"]) == (1 if first == model else -1)
