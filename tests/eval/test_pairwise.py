"""Pair features, BT fit, nested grouped CV, one-SE rule, writers and freeze checks.

All data here is synthetic. Hand values are in the comments.
"""

from __future__ import annotations

import hashlib
import json
import math

import numpy as np
import pytest

from pantrychef.eval import pairwise as pw
from pantrychef.rank import FEATURES

SETS = {"F1": ("score", "missing"), "F2": ("score", "missing", "total_c", "short"), "F3": FEATURES}


def vec(*head: float) -> tuple[float, ...]:
    return tuple(head) + (0.0,) * (len(FEATURES) - len(head))


def synthetic(n_pantries=40, per=3, w_true=(2.0, -1.0), seed=0, tie_every=0):
    rng = np.random.default_rng(seed)
    w = np.zeros(len(FEATURES))
    w[: len(w_true)] = w_true
    items = []
    for p in range(n_pantries):
        for k in range(per):
            z = rng.normal(size=len(FEATURES))
            y = int(rng.random() < 1 / (1 + math.exp(-float(w @ z))))
            if tie_every and (p * per + k) % tie_every == 0:
                y = None
            items.append(pw.PairItem(f"p{p:03d}", f"p{p:03d}-{k}", "A", "B", y, tuple(z)))
    return items


# ---------------------------------------------------------------- pair features


def test_pair_features_are_mean_a_minus_mean_b():
    a = [vec(1, 2), vec(3, 4)]  # mean (2, 3)
    b = [vec(0, 1), vec(0, 3), vec(3, 5)]  # mean (1, 3)
    assert pw.pair_z(a, b)[:2] == (1.0, 0.0)
    assert pw.pair_z(b, a)[:2] == (-1.0, -0.0)  # antisymmetric


def test_make_item_maps_outcomes():
    a, b = [vec(1)], [vec(0)]
    assert pw.make_item("p", "i", "x", "y", a, b, "A").y == 1
    assert pw.make_item("p", "i", "x", "y", a, b, "B").y == 0
    assert pw.make_item("p", "i", "x", "y", a, b, "tie").y is None
    with pytest.raises(ValueError):
        pw.make_item("p", "i", "x", "y", a, b, "left")


def test_mirrored_rows_and_ties_dropped():
    items = [
        pw.PairItem("p", "1", "x", "y", 1, vec(1, 2)),
        pw.PairItem("p", "2", "x", "y", 0, vec(3, 0)),
        pw.PairItem("q", "3", "x", "y", None, vec(9, 9)),
    ]
    x, y = pw.mirrored(items)
    assert x[:, :2].tolist() == [[1, 2], [-1, -2], [3, 0], [-3, -0]]
    assert y.tolist() == [1, 0, 0, 1]


# ---------------------------------------------------------------- fit


def test_fit_recovers_known_weight_signs():
    items = synthetic(n_pantries=150, w_true=(2.0, -1.5))
    fit = pw.fit_weights(items, SETS["F3"], C=1.0)
    assert fit.weights[0] > 0.5 and fit.weights[1] < -0.3
    assert len(fit.weights) == len(FEATURES)


def test_weights_outside_the_set_are_zero():
    fit = pw.fit_weights(synthetic(), SETS["F1"], C=1.0)
    assert all(w == 0.0 for w in fit.weights[2:])
    assert fit.weights[0] != 0.0


def test_fit_is_symmetric_under_swapping_a_and_b():
    items = synthetic(n_pantries=30)
    swapped = [
        pw.PairItem(i.pantry_id, i.item_id, i.arm_b, i.arm_a, None if i.y is None else 1 - i.y,
                    tuple(-v for v in i.z))
        for i in items
    ]  # fmt: skip
    f1 = pw.fit_weights(items, SETS["F3"], C=0.3)
    f2 = pw.fit_weights(swapped, SETS["F3"], C=0.3)
    assert np.allclose(f1.weights, f2.weights, atol=1e-6)
    z = items[0].z
    d1 = pw.pair_score(f1.weights, z)
    d2 = pw.pair_score(f1.weights, tuple(-v for v in z))
    assert d2 == -d1


def test_standardisation_scales_only_and_folds_into_raw_weights():
    items = synthetic(n_pantries=30)
    fit = pw.fit_weights(items, SETS["F3"], C=1.0)
    assert all(m == 0.0 for m in fit.mean)  # centring would break antisymmetry
    x, _ = pw.mirrored(items)
    assert np.allclose(fit.sd, np.sqrt((x**2).mean(axis=0)))
    # raw weights on raw z give the same logits as standardised weights on z / sd
    assert fit.weights[0] == pytest.approx(fit.std_weights[0] / fit.sd[0])


def test_constant_zero_column_gets_sd_one_and_weight_zero():
    items = [
        pw.PairItem("p", str(k), "x", "y", k % 2, vec(1.0 if k % 2 else -1.0)) for k in range(10)
    ]
    fit = pw.fit_weights(items, FEATURES, C=1.0)
    assert fit.sd[1] == 1.0 and fit.weights[1] == 0.0


# ---------------------------------------------------------------- folds and CV


def test_grouped_folds_keep_a_pantry_whole():
    ids = [f"p{i % 17}" for i in range(60)]
    folds = pw.grouped_folds(ids, 5, seed=1)
    assert len(folds) == 5
    seen = [p for f in folds for p in f]
    assert sorted(seen) == sorted(set(ids))  # every pantry once, no pantry in two folds
    assert max(map(len, folds)) - min(map(len, folds)) <= 1
    assert pw.grouped_folds(ids, 5, seed=1) == folds  # deterministic


def test_grouped_folds_need_enough_pantries():
    with pytest.raises(ValueError):
        pw.grouped_folds(["a", "b"], 5, seed=0)


def test_nested_cv_never_splits_a_pantry_and_reports_folds():
    items = synthetic(n_pantries=40, tie_every=4)
    res = pw.nested_cv(items, SETS, Cs=(0.1, 1.0), outer_k=5, inner_k=4, seed=3)
    pantries = {i.pantry_id for i in items if i.y is not None}
    held = [set(f["test_pantries"]) for f in res["outer"]]
    assert set().union(*held) == pantries
    assert sum(map(len, held)) == len(pantries)  # disjoint
    for f in res["outer"]:
        assert not set(f["train_pantries"]) & set(f["test_pantries"])
        assert set(f["train_pantries"]) | set(f["test_pantries"]) == pantries
        assert f["choice"]["feature_set"] in SETS
    assert res["n_decided"] == sum(i.y is not None for i in items)


def test_nested_cv_beats_chance_with_a_real_signal():
    items = synthetic(n_pantries=60, w_true=(2.0, -1.5))
    res = pw.nested_cv(items, SETS, Cs=(0.1, 1.0), outer_k=5, inner_k=4, seed=0)
    assert res["outer_logloss"] < math.log(2)
    assert res["outer_accuracy"] > 0.6
    assert res["chance_logloss"] == pytest.approx(0.6931, abs=1e-4)
    assert "f1_logloss" in res


def test_check1_is_below_chance():
    assert pw.check_futility_1(0.60)["pass"] is True
    assert pw.check_futility_1(math.log(2))["pass"] is False
    assert pw.check_futility_1(0.80)["pass"] is False


# ---------------------------------------------------------------- one-SE rule


def cell(s, c, mean, se):
    return pw.Cell(s, c, mean, se)


def test_one_se_prefers_the_smaller_set_within_one_se():
    cells = [cell("F3", 0.01, 0.58, 0.03), cell("F1", 0.1, 0.60, 0.05), cell("F2", 0.1, 0.59, 0.02)]
    # best = F3 0.58, limit = 0.58 + 0.03 = 0.61; F1 (0.60) and F2 (0.59) qualify; F1 is smallest
    assert pw.one_se_pick(cells, SETS) == ("F1", 0.1)


def test_one_se_picks_the_smaller_set_on_an_exact_tie_and_then_smaller_c():
    cells = [
        cell("F3", 0.1, 0.60, 0.0),
        cell("F1", 0.3, 0.60, 0.0),
        cell("F1", 0.03, 0.60, 0.0),
    ]
    assert pw.one_se_pick(cells, SETS) == ("F1", 0.03)


def test_one_se_keeps_a_clearly_better_big_set():
    cells = [cell("F1", 0.1, 0.70, 0.01), cell("F3", 0.1, 0.55, 0.01)]
    assert pw.one_se_pick(cells, SETS) == ("F3", 0.1)


# ---------------------------------------------------------------- writers


def test_pantries_sha256_is_hash_of_sorted_unique_ids():
    want = hashlib.sha256(b"a\nb").hexdigest()
    assert pw.pantries_sha256(["b", "a", "b"]) == want


def test_training_table_round_trips_and_has_no_text(tmp_path):
    items = synthetic(n_pantries=6, tie_every=5)
    path = tmp_path / "t.json"
    digest = pw.write_training_table(path, items)
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert b"\r" not in path.read_bytes() and b"\x00" not in path.read_bytes()
    assert pw.read_training_table(path) == items
    raw = json.loads(path.read_text(encoding="utf8"))
    assert set(raw["rows"][0]) == {"pantry_id", "item_id", "arm_a", "arm_b", "y", "z"}


def test_weights_file_round_trips(tmp_path):
    items = synthetic(n_pantries=30)
    out = pw.run_train(
        items,
        sets=SETS,
        Cs=(0.1, 1.0),
        seed=0,
        weights_path=tmp_path / "w.json",
        table_path=tmp_path / "t.json",
        comparator="shipped",
        commit="abc",
    )
    assert out["check1"]["pass"]
    data = json.loads((tmp_path / "w.json").read_text(encoding="utf8"))
    assert data["features"] == list(FEATURES) and data["version"] == 1
    assert len(data["weights"]) == 8
    assert data["standardisation"]["mean"] == [0.0] * 8 and len(data["standardisation"]["sd"]) == 8
    tr = data["trained_on"]
    assert tr["pantries_sha256"] == pw.pantries_sha256(i.pantry_id for i in items)
    assert (
        tr["train_table_sha256"] == hashlib.sha256((tmp_path / "t.json").read_bytes()).hexdigest()
    )
    assert (tr["n_pantries"], tr["n_items"], tr["n_decided"]) == (30, 90, 90)
    assert data["comparator"] == "shipped" and data["commit"] == "abc"
    assert data["cv"]["outer_logloss"] == out["cv"]["outer_logloss"]
    assert pw.read_weights(tmp_path / "w.json") == data
    # weights outside the chosen set are exactly 0
    names = SETS[data["feature_set"]]
    assert all(w == 0.0 for f, w in zip(FEATURES, data["weights"], strict=True) if f not in names)


def test_run_train_writes_no_weights_when_check1_fails(tmp_path):
    rng = np.random.default_rng(1)
    items = [
        pw.PairItem(
            f"p{i}", f"p{i}-0", "A", "B", int(rng.integers(0, 2)), tuple(rng.normal(size=8))
        )
        for i in range(40)
    ]
    out = pw.run_train(
        items,
        sets={"F1": SETS["F1"]},
        Cs=(1.0,),
        seed=0,
        weights_path=tmp_path / "w.json",
        table_path=tmp_path / "t.json",
        comparator="shipped",
        commit="abc",
    )
    assert out["check1"]["pass"] is False  # pure noise: held-out loss is not below chance
    assert not (tmp_path / "w.json").exists()
    assert (tmp_path / "t.json").exists()


# ---------------------------------------------------------------- freeze


class FakeGit:
    """Fake of the git callable. ``log`` maps a path to its commits, newest first."""

    def __init__(self, dirty="", tracked=None, log=None, head="h" * 40):
        self.dirty, self.tracked, self.log, self.head = dirty, tracked, log or {}, head

    def __call__(self, root, *args):
        if args[:2] == ("status", "--porcelain"):
            return self.dirty
        if args[0] == "ls-files":
            rel = args[-1]
            if self.tracked is not None and rel not in self.tracked:
                raise pw.GitError(rel)
            return rel
        if args[:2] == ("rev-parse", "HEAD"):
            return self.head + "\n"
        raise AssertionError(args)

    def commits(self, root, rel):
        return list(self.log.get(rel, []))

    @staticmethod
    def is_ancestor(root, older, newer):
        # like ``git merge-base --is-ancestor``: a commit is its own ancestor (RF5)
        return int(older[1:]) <= int(newer[1:])  # commits are named c1, c2, ...


def repo(tmp_path, files=("a.txt", "b.txt")):
    for f in files:
        (tmp_path / f).write_text(f"content of {f}\n", encoding="utf8", newline="\n")
    (tmp_path / "pool.txt").write_text("poolhash\n", encoding="utf8")
    pack = tmp_path / "core.json.gz"
    pack.write_bytes(b"pack-bytes")
    return pack, hashlib.sha256(b"pack-bytes").hexdigest()


def test_build_freeze_lists_every_hash(tmp_path):
    pack, pack_sha = repo(tmp_path)
    fr = pw.build_freeze(
        tmp_path,
        files=("a.txt", "b.txt"),
        test_pool_file="pool.txt",
        pack_core=pack,
        pinned_pack_sha256=pack_sha,
        comparator="shipped",
        n_test=100,
        seed=42,
        git=FakeGit(),
    )
    assert fr["files"] == {
        "a.txt": hashlib.sha256(b"content of a.txt\n").hexdigest(),
        "b.txt": hashlib.sha256(b"content of b.txt\n").hexdigest(),
    }
    assert fr["pack_core_sha256"] == pack_sha
    assert fr["test_pool_sha256"] == "poolhash"
    assert (fr["comparator"], fr["n_test"], fr["seed"], fr["commit"]) == (
        "shipped",
        100,
        42,
        "h" * 40,
    )


def test_freeze_default_list_covers_the_plan_step_12_files():
    for rel in (
        "web/src/rank_model.v1.json",
        "data/eval/m4/train_table.v1.json",
        "data/eval/m4/analysis_plan.v1.md",
        "data/eval/m4/pantries.v1.json",
        "data/eval/m4/test_pantries_sha256.txt",
        "data/eval/m4/ui_decision.v1.json",
        "pantrychef/rank.py",
        "pantrychef/engine.py",
        "pantrychef/eval/pairwise.py",
        "pantrychef/eval/stats.py",
        "pantrychef/eval/arms.py",
        "pantrychef/eval/pantries.py",
        "pantrychef/eval/results.py",
        "scripts/judging_sheet.py",
        "scripts/judging_score.py",
        "scripts/m4_rank.py",
    ):
        assert rel in pw.FREEZE_FILES


@pytest.mark.parametrize("what", ["dirty", "untracked", "missing", "pack"])
def test_build_freeze_refuses(tmp_path, what):
    pack, pack_sha = repo(tmp_path)
    git = FakeGit(
        dirty=" M a.txt\n" if what == "dirty" else "",
        tracked={"b.txt"} if what == "untracked" else None,
    )
    files = ("a.txt", "nope.txt") if what == "missing" else ("a.txt", "b.txt")
    with pytest.raises(pw.FreezeError):
        pw.build_freeze(
            tmp_path,
            files=files,
            test_pool_file="pool.txt",
            pack_core=pack,
            pinned_pack_sha256="0" * 64 if what == "pack" else pack_sha,
            comparator="shipped",
            n_test=100,
            seed=42,
            git=git,
        )


def frozen(tmp_path, **kw):
    """Build a freeze plus its key, key hash and answers. Return ``(args, git)``."""
    pack, pack_sha = repo(tmp_path)
    (tmp_path / "key.json").write_text('{"key": 1}\n', encoding="utf8", newline="\n")
    key_sha = hashlib.sha256((tmp_path / "key.json").read_bytes()).hexdigest()
    (tmp_path / "key_sha256.test.txt").write_text(key_sha + "\n", encoding="utf8")
    (tmp_path / "answers.csv").write_text("a,b\n", encoding="utf8")
    git = FakeGit(
        log={"freeze.json": ["c1"], "key_sha256.test.txt": ["c2"], "answers.csv": ["c3"]}, **kw
    )
    fr = pw.build_freeze(
        tmp_path,
        files=("a.txt", "b.txt"),
        test_pool_file="pool.txt",
        pack_core=pack,
        pinned_pack_sha256=pack_sha,
        comparator="shipped",
        n_test=100,
        seed=42,
        git=git,
    )
    (tmp_path / "freeze.json").write_text(json.dumps(fr), encoding="utf8")
    args = {
        "freeze_rel": "freeze.json",
        "pack_core": pack,
        "key_path": tmp_path / "key.json",
        "key_hash_rel": "key_sha256.test.txt",
        "answers_rel": "answers.csv",
        "git": git,
        "commits": git.commits,
        "is_ancestor": git.is_ancestor,
    }
    return args, git


def test_check_freeze_passes_on_a_clean_ordered_history(tmp_path):
    args, _ = frozen(tmp_path)
    assert pw.check_freeze(tmp_path, **args) == []


def test_check_freeze_flags_a_changed_frozen_file_and_pack(tmp_path):
    args, _ = frozen(tmp_path)
    (tmp_path / "a.txt").write_text("edited\n", encoding="utf8")
    args["pack_core"].write_bytes(b"other pack")
    problems = pw.check_freeze(tmp_path, **args)
    assert any("a.txt" in p for p in problems)
    assert any("pack" in p for p in problems)


def test_check_freeze_flags_dirty_tree_and_untracked_inputs(tmp_path):
    args, git = frozen(tmp_path)
    git.dirty = " M pantrychef/rank.py\n"
    git.tracked = {"freeze.json", "key_sha256.test.txt"}  # answers.csv not tracked
    problems = pw.check_freeze(tmp_path, **args)
    assert any("clean" in p or "differ" in p for p in problems)
    assert any("answers.csv" in p and "tracked" in p for p in problems)


@pytest.mark.parametrize("rel", ["freeze.json", "key_sha256.test.txt", "answers.csv"])
def test_check_freeze_needs_exactly_one_commit_each(tmp_path, rel):
    args, git = frozen(tmp_path)
    git.log[rel] = ["c1", "c2"] if rel == "freeze.json" else [*git.log[rel], "c9"]
    assert any(rel in p and "exactly one commit" in p for p in pw.check_freeze(tmp_path, **args))
    git.log[rel] = []
    assert any(rel in p and "exactly one commit" in p for p in pw.check_freeze(tmp_path, **args))


def test_check_freeze_flags_wrong_commit_order(tmp_path):
    args, git = frozen(tmp_path)
    git.log["key_sha256.test.txt"] = ["c0"]  # key hash committed before the freeze
    assert any("order" in p for p in pw.check_freeze(tmp_path, **args))
    git.log["key_sha256.test.txt"] = ["c2"]
    git.log["answers.csv"] = ["c2"]  # answers not after key hash
    assert any("order" in p for p in pw.check_freeze(tmp_path, **args))


def test_check_freeze_flags_a_key_that_differs_from_its_committed_hash(tmp_path):
    args, _ = frozen(tmp_path)
    (tmp_path / "key.json").write_text('{"key": 2}\n', encoding="utf8", newline="\n")
    assert any("key" in p and "hash" in p for p in pw.check_freeze(tmp_path, **args))


def test_check_freeze_defaults_use_the_real_git_helpers(tmp_path):
    """Seam 3: with no injected fakes, check_freeze reads real history (results.commits)."""
    import subprocess

    def g(*args):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=tmp_path, check=True, capture_output=True,
        )  # fmt: skip

    g("init", "-q")
    pack, pack_sha = repo(tmp_path)
    g("add", "-A")
    g("commit", "-q", "-m", "base")
    fr = pw.build_freeze(
        tmp_path, files=("a.txt", "b.txt"), test_pool_file="pool.txt", pack_core=pack,
        pinned_pack_sha256=pack_sha, comparator="shipped", n_test=100, seed=42,
    )  # fmt: skip
    pw.write_freeze(tmp_path / "freeze.json", fr)
    g("add", "freeze.json")
    g("commit", "-q", "-m", "freeze")
    (tmp_path / "key.json").write_text('{"key": 1}\n', encoding="utf8", newline="\n")
    key_sha = hashlib.sha256((tmp_path / "key.json").read_bytes()).hexdigest()
    (tmp_path / "key_sha256.test.txt").write_text(key_sha + "\n", encoding="utf8", newline="\n")
    g("add", "key_sha256.test.txt")
    g("commit", "-q", "-m", "key hash")
    (tmp_path / "answers.csv").write_text("a,b\n", encoding="utf8", newline="\n")
    g("add", "answers.csv")
    g("commit", "-q", "-m", "answers")
    args = {
        "freeze_rel": "freeze.json", "pack_core": pack, "key_path": tmp_path / "key.json",
        "key_hash_rel": "key_sha256.test.txt", "answers_rel": "answers.csv",
    }  # fmt: skip
    assert pw.check_freeze(tmp_path, **args) == []
    (tmp_path / "a.txt").write_text("edited\n", encoding="utf8", newline="\n")
    assert any("a.txt" in p for p in pw.check_freeze(tmp_path, **args))
    g("checkout", "--", "a.txt")
    # answers committed before the key hash: wrong order
    args["key_hash_rel"], args["answers_rel"] = "answers.csv", "key_sha256.test.txt"
    assert any("order" in p for p in pw.check_freeze(tmp_path, **args))


def test_freeze_problems_alone_cover_files_pack_and_a_missing_freeze(tmp_path):
    args, _ = frozen(tmp_path)
    kw = {"pack_core": args["pack_core"], "freeze_rel": "freeze.json", "git": args["git"]}
    assert pw.freeze_problems(tmp_path, **kw) == []
    (tmp_path / "b.txt").write_text("edited\n", encoding="utf8")
    assert any("b.txt" in p for p in pw.freeze_problems(tmp_path, **kw))
    (tmp_path / "freeze.json").unlink()
    assert pw.freeze_problems(tmp_path, **kw) == ["no freeze file at freeze.json"]


def test_build_freeze_lets_a_generated_file_be_new(tmp_path):
    pack, pack_sha = repo(tmp_path)
    kw = {
        "files": ("a.txt", "b.txt"), "test_pool_file": "pool.txt", "pack_core": pack,
        "pinned_pack_sha256": pack_sha, "comparator": "shipped", "n_test": 100, "seed": 42,
    }  # fmt: skip
    git = FakeGit(tracked={"a.txt"})  # b.txt is new
    with pytest.raises(pw.FreezeError, match="b.txt"):
        pw.build_freeze(tmp_path, git=git, **kw)
    assert pw.build_freeze(tmp_path, git=git, generated=("b.txt",), **kw)["files"]["b.txt"]


def test_check_freeze_reports_missing_key_files_instead_of_crashing(tmp_path):
    args, git = frozen(tmp_path)
    (tmp_path / "key.json").unlink()
    (tmp_path / "key_sha256.test.txt").unlink()
    problems = pw.check_freeze(tmp_path, **args)
    assert any("key_sha256.test.txt" in p and "missing" in p for p in problems)
    assert any("key.json" in p and "missing" in p for p in problems)


NL = chr(10)
CRB = chr(13).encode()


def real_history(tmp_path, together: tuple[str, ...] = ()):
    """A temp git repo with a freeze, a key hash and answers. ``together`` names two of
    ``freeze``, ``key``, ``answers`` that go into ONE commit. Returns the check_freeze kwargs."""
    import subprocess

    def g(*args):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=tmp_path, check=True, capture_output=True,
        )  # fmt: skip

    g("init", "-q")
    pack, pack_sha = repo(tmp_path)
    g("add", "-A")
    g("commit", "-q", "-m", "base")
    fr = pw.build_freeze(
        tmp_path, files=("a.txt", "b.txt"), test_pool_file="pool.txt", pack_core=pack,
        pinned_pack_sha256=pack_sha, comparator="shipped", n_test=100, seed=42,
    )  # fmt: skip
    pw.write_freeze(tmp_path / "freeze.json", fr)
    (tmp_path / "key.json").write_text('{"key": 1}' + NL, encoding="utf8", newline=NL)
    key_sha = hashlib.sha256((tmp_path / "key.json").read_bytes()).hexdigest()
    (tmp_path / "key_sha256.test.txt").write_text(key_sha + NL, encoding="utf8", newline=NL)
    (tmp_path / "answers.csv").write_text("a,b" + NL, encoding="utf8", newline=NL)
    files = {"freeze": "freeze.json", "key": "key_sha256.test.txt", "answers": "answers.csv"}
    pending = list(files)
    while pending:
        group = [n for n in pending if n == pending[0] or n in together and pending[0] in together]
        for n in group:
            g("add", files[n])
        g("commit", "-q", "-m", "+".join(group))
        pending = [n for n in pending if n not in group]
    return {
        "freeze_rel": "freeze.json", "pack_core": pack, "key_path": tmp_path / "key.json",
        "key_hash_rel": "key_sha256.test.txt", "answers_rel": "answers.csv",
    }  # fmt: skip


def test_real_git_three_distinct_commits_in_order_pass(tmp_path):
    assert pw.check_freeze(tmp_path, **real_history(tmp_path)) == []


@pytest.mark.parametrize("together", [("key", "answers"), ("freeze", "key")])
def test_real_git_two_files_in_one_commit_fail(tmp_path, together):
    """RF5: ``git merge-base --is-ancestor A A`` is true, so a shared commit used to pass."""
    problems = pw.check_freeze(tmp_path, **real_history(tmp_path, together))
    assert any("different commits" in p or "distinct" in p for p in problems), problems


@pytest.mark.parametrize("a,b", [("c1", "c1"), ("c2", "c2")])
def test_check_freeze_needs_distinct_commits_even_with_a_lenient_ancestor_fake(tmp_path, a, b):
    args, git = frozen(tmp_path)
    git.log["key_sha256.test.txt"] = [a]
    git.log["freeze.json"] = [a]
    git.log["answers.csv"] = [b if b != a else "c3"]
    assert any(
        "distinct" in p or "different commits" in p for p in pw.check_freeze(tmp_path, **args)
    )


def test_freeze_default_list_covers_the_code_that_builds_and_scores_lists():
    for rel in (
        "pantrychef/eval/m4_lists.py",
        "pantrychef/eval/m4_run.py",
        "pantrychef/eval/m4_pools.py",
    ):
        assert rel in pw.FREEZE_FILES


def test_freeze_list_covers_the_import_closure_of_the_three_scripts():
    """RF4: every in-repo module the sheet, scorer and CLI import is frozen."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]

    def module_file(m):
        for p in (root / (m.replace(".", "/") + ".py"), root / m.replace(".", "/") / "__init__.py"):
            if p.exists():
                return p
        return None

    seen: set[Path] = set()

    def walk(path):
        if path in seen:
            return
        seen.add(path)
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                mods = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
            for m in mods:
                if m.split(".")[0] in ("pantrychef", "scripts") and (f := module_file(m)):
                    walk(f)

    for s in ("scripts/m4_rank.py", "scripts/judging_sheet.py", "scripts/judging_score.py"):
        walk(root / s)
    code = {p.relative_to(root).as_posix() for p in seen if p.name != "__init__.py"}
    assert code - set(pw.FREEZE_FILES) == set()


def test_a_frozen_file_with_carriage_returns_is_refused_and_flagged(tmp_path):
    """RI6: the freeze hashes working-tree bytes, so a CRLF file would hash differently from LF."""
    pack, pack_sha = repo(tmp_path)
    (tmp_path / "a.txt").write_bytes(b"line one" + CRB + NL.encode() + b"line two")
    kw = {
        "files": ("a.txt", "b.txt"), "test_pool_file": "pool.txt", "pack_core": pack,
        "pinned_pack_sha256": pack_sha, "comparator": "shipped", "n_test": 100, "seed": 42,
    }  # fmt: skip
    with pytest.raises(pw.FreezeError, match="carriage return"):
        pw.build_freeze(tmp_path, git=FakeGit(), **kw)
    (tmp_path / "ok").mkdir()
    args, _ = frozen(tmp_path / "ok")  # an LF freeze, then a CRLF edit
    (tmp_path / "ok" / "a.txt").write_bytes(b"x" + CRB + NL.encode())
    assert any("a.txt" in p for p in pw.check_freeze(tmp_path / "ok", **args))


def order_repo(tmp_path, order):
    """A temp git repo where ``key_sha256.x.txt`` and ``answers.x.csv`` are committed in the given
    order. ``order`` is a list of groups, each a tuple of the two names that share a commit."""
    import subprocess

    def g(*args):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=tmp_path, check=True, capture_output=True,
        )  # fmt: skip

    g("init", "-q")
    (tmp_path / "base.txt").write_text("x" + NL, newline=NL)
    g("add", "-A")
    g("commit", "-q", "-m", "base")
    names = {"key": "key_sha256.x.txt", "answers": "answers.x.csv"}
    for n in names.values():
        (tmp_path / n).write_text("data" + NL, newline=NL)
    for group in order:
        for n in group:
            g("add", names[n])
        g("commit", "-q", "-m", "+".join(group))
    return {"key_hash_rel": names["key"], "answers_rel": names["answers"]}


def test_key_before_answers_passes_when_the_key_hash_has_its_own_earlier_commit(tmp_path):
    kw = order_repo(tmp_path, [("key",), ("answers",)])
    assert pw.key_order_problems(tmp_path, **kw) == []


@pytest.mark.parametrize(
    "order,word",
    [
        ([("key", "answers")], "different commits"),  # one shared commit
        ([("answers",), ("key",)], "before"),  # the answers came first
        ([("key",)], "answers"),  # the answers are not committed
        ([("answers",)], "key"),  # the key hash is not committed
    ],
)
def test_key_before_answers_fails_on_a_shared_reversed_or_missing_commit(tmp_path, order, word):
    kw = order_repo(tmp_path, order)
    problems = pw.key_order_problems(tmp_path, **kw)
    assert problems and any(word in p for p in problems), problems


def test_key_before_answers_outside_git_is_a_problem_not_a_crash(tmp_path):
    problems = pw.key_order_problems(tmp_path, key_hash_rel="k.txt", answers_rel="a.csv")
    assert problems and any("git" in p for p in problems)


def test_run_train_records_the_label_source_in_the_weights_and_the_table(tmp_path):
    """Amendment 2: ``training_labels`` is ``human`` by default, ``model_judged`` when asked."""
    items = synthetic(n_pantries=30)
    for labels in ("human", "model_judged"):
        kw = {
            "sets": SETS, "Cs": (0.1, 1.0), "seed": 0,
            "weights_path": tmp_path / f"w-{labels}.json",
            "table_path": tmp_path / f"t-{labels}.json", "comparator": "shipped", "commit": "abc",
        }  # fmt: skip
        if labels != "human":
            kw["training_labels"] = labels
        pw.run_train(items, **kw)
        weights = json.loads((tmp_path / f"w-{labels}.json").read_text(encoding="utf8"))
        table = json.loads((tmp_path / f"t-{labels}.json").read_text(encoding="utf8"))
        assert weights["trained_on"]["training_labels"] == labels
        assert table["training_labels"] == labels
    assert len(pw.read_training_table(tmp_path / "t-model_judged.json")) == len(items)


def test_build_freeze_records_extra_facts(tmp_path):
    pack, pack_sha = repo(tmp_path)
    fr = pw.build_freeze(
        tmp_path, files=("a.txt", "b.txt"), test_pool_file="pool.txt", pack_core=pack,
        pinned_pack_sha256=pack_sha, comparator="shipped", n_test=100, seed=42,
        git=FakeGit(), extra={"training_labels": "model_judged", "comparator_source": "default"},
    )  # fmt: skip
    assert fr["training_labels"] == "model_judged" and fr["comparator_source"] == "default"
    assert fr["comparator"] == "shipped"
