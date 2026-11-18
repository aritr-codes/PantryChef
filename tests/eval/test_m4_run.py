"""M4 wiring (plan section 10): dev-score, train, futility, freeze and score, and the seams.

Everything runs on the fixture pack, in temp folders (``--root``). Answers are synthetic: a
deterministic judge that prefers the list with the higher mean ``score`` feature. They test the
pipeline and the sign of the weights. They say nothing about quality.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from pantrychef.engine import load_pack
from pantrychef.eval import m4_run, results
from pantrychef.eval import pairwise as pw
from pantrychef.eval.arms import CandidateIndex
from pantrychef.eval.m4_lists import excluded_ids, feature_map, model_orderer, top_lists
from pantrychef.eval.m4_pools import VARIANTS, build_pools, canonical, check_no_leak
from pantrychef.eval.pantries import _group_key
from pantrychef.rank import load_model
from scripts import judging_score as js
from scripts import judging_sheet as sj
from scripts import m4_rank as m4

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pack"
ARMS3 = ("shipped", "overlap", "idf_flat")
SIZES = (("pilot", 3), ("dev", 8), ("futility", 3), ("reserve", 2))
PLAN = """# Plan

## 6. Power

### 6.1 Pre-registered analysis (copied into the freeze)

- **Primary.** Model against the IDF rule on test.
- **Ship rule.** The model ships only when `CP_lo > 0.5`.

## 7. Features and the model

Not part of 6.1.
"""


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root, check=True, capture_output=True,
    )  # fmt: skip


# ---------------------------------------------------------------- the synthetic world


def synth_answers(env, name, *, flip=False, label=None, arm_guess=False, orderers=None) -> Path:
    """Write ``answers.NAME.v1.csv``: the judge prefers the higher mean ``score`` list."""
    root = env.root
    key = json.loads((root / f"data/interim/judging_key.m4-{name}.v1.json").read_text())
    pools = {r["pantry_id"]: r for rows in env.doc["pools"].values() for r in rows}
    index = CandidateIndex(env.pack, set(env.pack.default_staples))
    group_of = {r.recipe_id: _group_key(r) for r in env.pack.recipes}
    cols = ["item_id", "choice", "strength", "would_cook_left", "would_cook_right", "seconds"]
    cols += ["session"] + (["arm_guess"] if arm_guess else []) + (["judge"] if label else [])
    out = root / f"data/eval/m4/answers.{name}.v1.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for iid, k in key["items"].items():
            rec = pools[k["pantry_id"]]
            gone = excluded_ids(group_of, rec["gold_id"], rec["title_group"])
            tops = top_lists(index, (k["left"], k["right"]), rec["pantry"], gone, orderers or {})
            fm = feature_map(env.pack, rec["pantry"])
            mean = {
                a: sum(fm[c.recipe_id][0] for c in t) / len(t) for a, t in tops.items()
            }  # the first feature is ``score``
            d = mean[k["left"]] - mean[k["right"]]
            d = -d if flip else d
            choice = "A" if d > 0 else "B" if d < 0 else "tie"
            row = {
                "item_id": iid, "choice": choice,
                "strength": "" if choice == "tie" else "1",
                "would_cook_left": "yes" if d >= 0 else "no",
                "would_cook_right": "yes" if d <= 0 else "no",
                "seconds": "5", "session": "s1", "arm_guess": "unsure", "judge": label or "",
            }  # fmt: skip
            w.writerow([row[c] for c in cols])
    return out


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """A temp root with the fixture pack, the pools and the pilot and dev sheets."""
    root = tmp_path_factory.mktemp("m4world")
    pack_dir = root / "pack"
    pack_dir.mkdir()
    with gzip.open(pack_dir / "core.v2.json.gz", "wb") as fh:
        fh.write((FIXTURE / "core.v2.json").read_bytes())
    pack = load_pack(pack_dir)
    spike = root / "data/eval/graph_spike/pantries.v1.json"
    spike.parent.mkdir(parents=True)
    spike.write_text(json.dumps({"pantries": []}), encoding="utf-8")
    doc, _ = build_pools(pack, sha(pack_dir / "core.v2.json.gz"), spike, SIZES)
    pf = root / "data/eval/m4/pantries.v1.json"
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_bytes(canonical(doc))
    (root / "data/eval/m4/test_pantries_sha256.txt").write_text(
        hashlib.sha256(canonical(doc["pools"]["test"])).hexdigest() + chr(10), newline=chr(10)
    )
    e = SimpleNamespace(root=root, pack_dir=pack_dir, pack=pack, doc=doc, pf=pf)
    common = ["--pack", str(pack_dir), "--pantries", str(pf), "--out-dir", str(root)]
    sj.main([*common, "--pool", "pilot", "--arms", *ARMS3, "--name", "pilot"])
    sj.main([*common, "--pool", "dev", "--take", "8", "--arms", *ARMS3, "--name", "dev",
             "--repeats", "2"])  # fmt: skip
    synth_answers(e, "pilot")
    synth_answers(e, "dev")
    return e


def fresh(env, tmp_path) -> SimpleNamespace:
    """A private copy of the world, so a test can change files."""
    root = tmp_path / "w"
    shutil.copytree(env.root, root)
    return SimpleNamespace(
        root=root,
        pack_dir=root / "pack",
        pack=env.pack,
        doc=env.doc,
        pf=root / "data/eval/m4/pantries.v1.json",
    )


def sheet_key(e, name) -> dict:
    return json.loads((e.root / f"data/interim/judging_key.m4-{name}.v1.json").read_text())


def base_items(e, *names) -> list[dict]:
    return [v for n in names for v in sheet_key(e, n)["items"].values() if not v["repeat_of"]]


def run(cmd, env, *extra):
    """Run a command in a temp root. The temp roots are not git repos, so the commit-order check
    (RI3) is off here. ``run_strict`` leaves it on."""
    return run_strict(cmd, env, "--allow-uncommitted", *extra)


def run_strict(cmd, env, *extra):
    return m4.main([cmd, "--root", str(env.root), "--pack", str(env.pack_dir), *extra])


def diverse_weights(e) -> Path:
    """Replace the trained weights in a temp copy with mixed-sign ones. The synthetic judge makes
    the trained model order lists like ``idf_flat`` (same top 5), which RF1 then drops."""
    w = e.root / "web/src/rank_model.v1.json"
    d = json.loads(w.read_text())
    d["weights"] = [0.3, -1.5, 2.0, -0.7, 1.1, 0.9, -2.2, 1.4]
    w.write_text(json.dumps(d, indent=2) + chr(10), encoding="utf-8", newline=chr(10))
    return w


def printed(capsys) -> list[str]:
    return [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]


def only_go_stop_and_paths(lines):
    return all(ln in ("GO", "STOP") or ln.startswith("wrote ") for ln in lines)


@pytest.fixture(scope="module")
def scored(env, tmp_path_factory):
    """dev-score on the world (pilot and dev sheets joined, D7)."""
    e = fresh(env, tmp_path_factory.mktemp("scored"))
    assert run("dev-score", e, "--name", "pilot", "dev") == 0
    return e


@pytest.fixture(scope="module")
def trained(scored, tmp_path_factory):
    e = fresh(scored, tmp_path_factory.mktemp("trained"))
    assert run("train", e, "--name", "pilot", "dev") == 0
    return e


# ---------------------------------------------------------------- seam 4: the shim is gone


def test_registry_shim_is_gone_and_variants_still_run(env, tmp_path):
    assert not hasattr(m4, "_shim_registry")
    metrics_before, arms_before = set(results.METRICS), set(results.ARMS)
    e = fresh(env, tmp_path)
    assert run("variants", e) == 0
    doc = results.load_result(e.root / "results/m4_idf_variants.json")
    assert "registry_shim" not in doc["config"]  # RI7: the shim and its empty marker are gone
    assert doc["corpus_fingerprint"] == e.pack.info.corpus_fingerprint
    assert {a["name"] for a in doc["arms"]} == set(VARIANTS)
    assert (set(results.METRICS), set(results.ARMS)) == (metrics_before, arms_before)


# ---------------------------------------------------------------- pure helpers


def stats(a, b, aw, bw, ties=0):
    return js._pair_stats(a, b, aw, bw, ties)


def test_choose_rule_hand_cases():
    def pairs(idf_w, ship_w, ov_vs_idf=(0, 0), ov_vs_ship=(0, 0)):
        return {
            "idf_flat_vs_shipped": stats("idf_flat", "shipped", idf_w, ship_w, 3),
            "overlap_vs_shipped": stats("overlap", "shipped", *ov_vs_ship),
            "idf_flat_vs_overlap": stats("idf_flat", "overlap", *reversed(ov_vs_idf)),
        }

    # 20 of 24 decided: CP lower bound about 0.63, above 0.5: idf_flat
    r = m4_run.choose_rule(pairs(20, 4))
    assert r["rule"] == "idf_flat" and r["overlap_beats_rule"] is False
    assert (r["idf_flat_vs_shipped"]["W"], r["idf_flat_vs_shipped"]["L"]) == (20, 4)
    assert r["idf_flat_vs_shipped"]["T"] == 3  # ties drop out of W and L only
    # 9 of 12: the lower bound is about 0.43: shipped
    assert m4_run.choose_rule(pairs(9, 3))["rule"] == "shipped"
    # nothing decided: shipped
    assert m4_run.choose_rule(pairs(0, 0))["rule"] == "shipped"
    # exactly even
    assert m4_run.choose_rule(pairs(10, 10))["rule"] == "shipped"


def test_choose_rule_reports_overlap_beating_the_chosen_rule_without_acting():
    shipped_chosen = {
        "idf_flat_vs_shipped": stats("idf_flat", "shipped", 5, 5),
        "overlap_vs_shipped": stats("overlap", "shipped", 22, 2),
        "idf_flat_vs_overlap": stats("idf_flat", "overlap", 2, 20),
    }
    r = m4_run.choose_rule(shipped_chosen)
    assert r["rule"] == "shipped" and r["overlap_beats_rule"] is True  # reported, rule unchanged
    idf_chosen = {
        "idf_flat_vs_shipped": stats("idf_flat", "shipped", 24, 2),
        "overlap_vs_shipped": stats("overlap", "shipped", 2, 24),
        "idf_flat_vs_overlap": stats("idf_flat", "overlap", 24, 2),
    }
    r = m4_run.choose_rule(idf_chosen)
    assert r["rule"] == "idf_flat" and r["overlap_beats_rule"] is False
    assert r["overlap_vs_rule"]["W"] == 2 and r["overlap_vs_rule"]["L"] == 24


def test_futility_stop_rule_is_stop_when_wins_do_not_beat_losses():
    assert m4_run.futility_verdict(5, 4)["stop"] is False
    assert m4_run.futility_verdict(4, 4)["stop"] is True
    assert m4_run.futility_verdict(3, 4)["stop"] is True
    assert m4_run.futility_verdict(0, 0)["stop"] is True  # no decided item


def test_model_judge_rows_are_refused_unless_allowed_and_never_on_test():
    rows = [{"item_id": "i1", "judge": "judge_model"}, {"item_id": "i2", "judge": ""}]
    with pytest.raises(SystemExit, match="model"):
        m4_run.check_judge(rows, allow=False, stage="dev")
    m4_run.check_judge(rows, allow=True, stage="dev")
    with pytest.raises(SystemExit, match="test"):
        m4_run.check_judge(rows, allow=True, stage="test")  # no flag lets a model into the test
    m4_run.check_judge([{"item_id": "i1"}], allow=False, stage="test")  # no column: fine


def test_section_6_1_is_copied_verbatim_or_from_its_fence():
    text = m4_run.section_6_1(PLAN)
    assert text.startswith("### 6.1 ") and "Ship rule" in text and "## 7." not in text
    assert text.endswith("\n") and "\r" not in text
    fenced = PLAN.replace(
        "- **Primary.**", "```text\nFENCED ANALYSIS\nline two\n```\n\n- **Primary.**"
    )
    assert m4_run.section_6_1(fenced) == "FENCED ANALYSIS\nline two\n"
    with pytest.raises(SystemExit, match="6.1"):
        m4_run.section_6_1("# nothing here\n")


def test_the_real_plan_has_a_section_6_1_with_the_ship_rule():
    plan = Path(__file__).resolve().parents[2] / "docs/plans/2026-11-18-m4-search-ranking.md"
    text = m4_run.section_6_1(plan.read_text(encoding="utf-8"))
    assert "Ship rule" in text and "CP_lo > 0.5" in text and "### 7." not in text


def test_model_orderer_agrees_with_the_candidate_index(env):
    """The index candidates and ``candidate_rows`` are the same set (the orderer checks it)."""
    weights = (1.0,) + (0.0,) * 7
    order_fn = model_orderer(env.pack, weights)
    index = CandidateIndex(env.pack, set(env.pack.default_staples))
    for rec in env.doc["pools"]["test"]:
        cands = [c for c in index.candidates(set(rec["pantry"])) if c.total - c.have <= 2]
        assert [c.recipe_id for c in order_fn(cands, rec["pantry"])]  # no ValueError


# ---------------------------------------------------------------- dev-score


def test_dev_score_writes_the_result_files_and_prints_only_go_or_stop(scored, capsys):
    # the fixture ran it once; run again here to look at the output
    e = scored
    capsys.readouterr()
    rc = run("dev-score", e, "--name", "pilot", "dev")
    lines = printed(capsys)
    assert only_go_stop_and_paths(lines), lines
    assert rc == 0 and lines[0] == "GO"
    for name in ("m4_dev_pairs", "m4_arm_overlap", "m4_arm_shipped", "m4_arm_idf_flat"):
        doc = results.load_result(e.root / f"results/{name}.json")
        assert doc["label"] == "MEASURED"
    pairs = results.load_result(e.root / "results/m4_dev_pairs.json")
    cfg = pairs["config"]
    assert cfg["comparator"] in ("shipped", "idf_flat")
    assert set(cfg["pairs"]) == {"idf_flat_vs_overlap", "idf_flat_vs_shipped", "overlap_vs_shipped"}
    assert cfg["model_judged"] is False and "overlap_beats_rule" in cfg
    assert {m["name"] for m in pairs["metrics"]} >= {"pairwise_win_rate"}
    assert all(m["split"] == "dev" for m in pairs["metrics"])


def test_dev_score_counts_add_up_over_both_sheets(scored):
    cfg = json.loads((scored.root / "results/m4_dev_pairs.json").read_text())["config"]
    total = {k: v["a_wins"] + v["b_wins"] + v["ties"] for k, v in cfg["pairs"].items()}
    want: dict[str, int] = {}
    for name in ("pilot", "dev"):
        for v in sheet_key(scored, name)["items"].values():
            if not v["repeat_of"]:
                k = "_vs_".join(sorted((v["left"], v["right"])))
                want[k] = want.get(k, 0) + 1
    assert total == want  # one item per shown pair; same-set pairs are not counted (RF1)


def test_dev_score_applies_the_rule_with_the_synthetic_judge(scored):
    cfg = json.loads((scored.root / "results/m4_dev_pairs.json").read_text())["config"]
    p = cfg["pairs"]["idf_flat_vs_shipped"]
    lo = js.clopper_pearson(p["a_wins"], p["a_wins"] + p["b_wins"])[0] if p["a_wins"] else 0.0
    assert cfg["comparator"] == ("idf_flat" if lo > 0.5 else "shipped")


def test_dev_score_refuses_model_judge_unless_allowed_and_then_labels_it(env, tmp_path):
    e = fresh(env, tmp_path)
    synth_answers(e, "dev", label="judge_model")
    synth_answers(e, "pilot", label="judge_model")
    with pytest.raises(SystemExit, match="model"):
        run("dev-score", e, "--name", "pilot", "dev")
    assert not (e.root / "results/m4_dev_pairs.json").exists()
    assert run("dev-score", e, "--name", "pilot", "dev", "--allow-model-judge") == 0
    pairs = results.load_result(e.root / "results/m4_dev_pairs.json")
    assert pairs["config"]["model_judged"] is True
    assert "model-judged" in pairs["what"]
    assert {m["name"] for m in pairs["metrics"]} == {"pilot_pairwise_win_rate"}
    arm = results.load_result(e.root / "results/m4_arm_shipped.json")
    assert "model-judged" in arm["what"] and arm["config"]["model_judged"] is True


def test_dev_score_refuses_a_key_with_a_futility_or_test_pantry(env, tmp_path):
    e = fresh(env, tmp_path)
    path = e.root / "data/interim/judging_key.m4-dev.v1.json"
    key = json.loads(path.read_text())
    first = next(iter(key["items"].values()))
    first["pantry_id"] = e.doc["pools"]["test"][0]["pantry_id"]
    path.write_text(json.dumps(key, indent=2, sort_keys=True) + "\n")
    (e.root / "data/eval/m4/key_sha256.dev.txt").write_text(sha(path) + "\n")  # hash is fine
    with pytest.raises(SystemExit, match="dev pool"):
        run("dev-score", e, "--name", "dev")


def test_dev_score_refuses_a_key_that_differs_from_its_committed_hash(env, tmp_path):
    e = fresh(env, tmp_path)
    path = e.root / "data/interim/judging_key.m4-dev.v1.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(SystemExit, match="hash"):
        run("dev-score", e, "--name", "dev")


def test_dev_score_selection_uses_the_registry_guard(env, monkeypatch, tmp_path):
    e = fresh(env, tmp_path)
    seen = []
    real = results.assert_selectable
    monkeypatch.setattr(
        m4_run.results, "assert_selectable", lambda m, a: (seen.append((m, a)), real(m, a))
    )
    run("dev-score", e, "--name", "pilot", "dev")
    assert seen and seen[0][0] == "pairwise_win_rate"


# ---------------------------------------------------------------- train


def test_train_writes_weights_table_cv_and_arm_files_with_the_right_sign(trained, capsys):
    e = trained
    w = json.loads((e.root / "web/src/rank_model.v1.json").read_text())
    assert w["weights"][0] > 0  # the judge prefers more IDF mass per list: score gets a plus
    pairs = json.loads((e.root / "results/m4_dev_pairs.json").read_text())["config"]
    assert w["comparator"] == pairs["comparator"]
    table = json.loads((e.root / "data/eval/m4/train_table.v1.json").read_text())
    assert w["trained_on"]["train_table_sha256"] == sha(e.root / "data/eval/m4/train_table.v1.json")
    base = base_items(e, "pilot", "dev")
    assert w["trained_on"]["n_pantries"] == len({v["pantry_id"] for v in base})
    # repeats and probes are not training items; ties stay in the table as ``y = null``
    assert len(table["rows"]) == len(base)
    assert check_no_leak(e.doc, table["rows"], w["trained_on"]) == []
    cv = results.load_result(e.root / "results/m4_cv.json")
    assert cv["label"] == "ESTIMATE"
    assert {m["name"] for m in cv["metrics"]} == {"cv_pairwise_logloss", "cv_pairwise_accuracy"}
    arm = results.load_result(e.root / "results/m4_arm_rank_linear.json")
    assert arm["arms"][0]["name"] == "rank_linear" and arm["metrics"] == []
    assert arm["config"]["weights_sha256"] == sha(e.root / "web/src/rank_model.v1.json")


def test_train_prints_only_go_and_paths(scored, tmp_path, capsys):
    e = fresh(scored, tmp_path)
    capsys.readouterr()
    assert run("train", e, "--name", "pilot", "dev") == 0
    lines = printed(capsys)
    assert only_go_stop_and_paths(lines), lines
    assert lines[0] == "GO"
    text = "\n".join(lines)
    assert "logloss" not in text and "weights" not in text.replace("rank_model", "")


def test_train_takes_the_comparator_from_the_dev_pairs_file(scored, tmp_path):
    e = fresh(scored, tmp_path)
    p = e.root / "results/m4_dev_pairs.json"
    doc = json.loads(p.read_text())
    doc["config"]["comparator"] = (
        "idf_flat" if doc["config"]["comparator"] == "shipped" else "shipped"
    )
    p.write_text(json.dumps(doc))
    assert run("train", e, "--name", "pilot", "dev") == 0
    w = json.loads((e.root / "web/src/rank_model.v1.json").read_text())
    assert w["comparator"] == doc["config"]["comparator"]


def test_train_needs_the_dev_pairs_file(env, tmp_path):
    e = fresh(env, tmp_path)
    with pytest.raises(SystemExit, match="m4_dev_pairs"):
        run("train", e, "--name", "pilot", "dev")


def test_train_refuses_model_judged_work_without_the_flag(env, tmp_path):
    e = fresh(env, tmp_path)
    synth_answers(e, "dev", label="judge_model")
    synth_answers(e, "pilot", label="judge_model")
    run("dev-score", e, "--name", "pilot", "dev", "--allow-model-judge")
    with pytest.raises(SystemExit, match="model"):
        run("train", e, "--name", "pilot", "dev")
    assert not (e.root / "web/src/rank_model.v1.json").exists()
    assert run("train", e, "--name", "pilot", "dev", "--allow-model-judge") == 0


def test_train_refuses_when_the_answers_changed_judge_since_dev_score(scored, tmp_path):
    e = fresh(scored, tmp_path)  # dev-score ran on human answers
    synth_answers(e, "dev", label="judge_model")
    synth_answers(e, "pilot", label="judge_model")
    with pytest.raises(SystemExit, match="disagree"):
        run("train", e, "--name", "pilot", "dev", "--allow-model-judge")
    assert not (e.root / "web/src/rank_model.v1.json").exists()


def test_model_judged_train_says_so_in_its_result_files(env, tmp_path):
    e = fresh(env, tmp_path)
    synth_answers(e, "dev", label="judge_model")
    synth_answers(e, "pilot", label="judge_model")
    run("dev-score", e, "--name", "pilot", "dev", "--allow-model-judge")
    assert run("train", e, "--name", "pilot", "dev", "--allow-model-judge") == 0
    for stem in ("m4_cv", "m4_arm_rank_linear"):
        doc = json.loads((e.root / f"results/{stem}.json").read_text())
        assert doc["config"]["model_judged"] is True and "model-judged" in doc["what"]


def test_train_writes_no_weights_when_check_1_fails(scored, tmp_path, monkeypatch, capsys):
    e = fresh(scored, tmp_path)
    monkeypatch.setattr(pw, "check_futility_1", lambda ll: {"pass": False, "outer_logloss": ll})
    capsys.readouterr()
    assert run("train", e, "--name", "pilot", "dev") == 3
    assert printed(capsys)[0] == "STOP"
    assert not (e.root / "web/src/rank_model.v1.json").exists()
    assert not (e.root / "results/m4_arm_rank_linear.json").exists()
    assert (e.root / "data/eval/m4/train_table.v1.json").exists()
    assert (e.root / "results/m4_cv.json").exists()


def test_train_items_use_the_sheet_list_logic(scored):
    """A training item's feature difference equals the means of the 5-recipe lists."""
    e = scored
    key = json.loads((e.root / "data/interim/judging_key.m4-dev.v1.json").read_text())
    rows = m4_run.read_answers(e.root / "data/eval/m4/answers.dev.v1.csv")
    items = m4_run.training_items(e.pack, e.doc, [("dev", key, rows)])
    base = [k for k in key["items"].values() if not k["repeat_of"] and not k.get("probe")]
    assert len(items) == len(base) > 10
    k = key["items"][items[0].item_id.split(":", 1)[1]]
    rec = next(r for r in e.doc["pools"]["dev"] if r["pantry_id"] == k["pantry_id"])
    idx = CandidateIndex(e.pack, set(e.pack.default_staples))
    gone = excluded_ids(
        {r.recipe_id: _group_key(r) for r in e.pack.recipes}, rec["gold_id"], rec["title_group"]
    )
    tops = top_lists(idx, (k["left"], k["right"]), rec["pantry"], gone, {})
    fm = feature_map(e.pack, rec["pantry"])
    mean = lambda arm: [sum(fm[c.recipe_id][i] for c in tops[arm]) / 5 for i in range(8)]  # noqa: E731
    z = [a - b for a, b in zip(mean(k["left"]), mean(k["right"]), strict=True)]
    assert list(items[0].z) == pytest.approx(z)
    assert (items[0].arm_a, items[0].arm_b) == (k["left"], k["right"])


# ---------------------------------------------------------------- pilot-score (RF3)

PILOT_LINES = [
    r"check 1 self-consistency: (PASS|FAIL)",
    r"check 2 discrimination: (PASS|FAIL)",
    r"check 3 cost: (PASS|FAIL)",
    r"check 4 power: (PASS|FAIL)",
    r"pilot: (PASS|FAIL)",
]


def rewrite_answers(e, name, fn):
    """Change the synthetic answers: ``fn(row, key_item)`` edits a row in place."""
    path = e.root / f"data/eval/m4/answers.{name}.v1.csv"
    key = sheet_key(e, name)["items"]
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        fn(r, key[r["item_id"]])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def pilot_world(env, tmp_path, *, label=None) -> SimpleNamespace:
    """A copy of the world whose pilot sheet has 4 repeats (the protocol shape)."""
    e = fresh(env, tmp_path)
    for rel in ("data/eval/m4/key_sha256.pilot.txt", "data/interim/judging_key.m4-pilot.v1.json"):
        (e.root / rel).unlink()
    rc = sj.main(
        ["--pack", str(e.pack_dir), "--pantries", str(e.pf), "--pool", "pilot", "--arms",
         *ARMS3, "--name", "pilot", "--repeats", "4", "--min-gap", "2", "--out-dir", str(e.root)]
    )  # fmt: skip
    assert rc == 0
    assert len([v for v in sheet_key(e, "pilot")["items"].values() if v["repeat_of"]]) == 4
    synth_answers(e, "pilot", label=label)
    return e


def pilot_checks_of(e) -> dict:
    return json.loads((e.root / "results/m4_timing_pilot.json").read_text())["config"]["checks"]


def test_pilot_score_prints_the_four_checks_and_the_verdict_and_nothing_else(env, tmp_path, capsys):
    e = pilot_world(env, tmp_path)
    capsys.readouterr()
    rc = run("pilot-score", e, "--name", "pilot")
    lines = printed(capsys)
    assert len(lines) == 5 and all(
        re.fullmatch(p, ln) for p, ln in zip(PILOT_LINES, lines, strict=True)
    )
    assert rc == (0 if lines[-1] == "pilot: PASS" else 3)


def test_pilot_score_writes_the_result_file_with_the_checks_and_the_power_table(env, tmp_path):
    e = pilot_world(env, tmp_path)
    assert run("pilot-score", e, "--name", "pilot") == 0  # the synthetic judge passes all four
    doc = results.load_result(e.root / "results/m4_timing_pilot.json")
    assert (
        doc["label"] == "MEASURED" and doc["corpus_fingerprint"] == e.pack.info.corpus_fingerprint
    )
    checks = doc["config"]["checks"]
    assert checks == {
        "check1_self_consistency": True, "check2_discrimination": True, "check3_cost": True,
        "check4_power": True, "overall": True,
    }  # fmt: skip
    assert {m["name"] for m in doc["metrics"]} == {
        "pairwise_tie_rate", "judge_repeat_agreement", "judge_median_seconds",
    }  # fmt: skip
    assert all(m["split"] == "pilot" for m in doc["metrics"])
    power = doc["config"]["analysis"]["power"]
    assert [r["n"] for r in power] == [40, 60, 80, 100]


def test_pilot_score_fails_check_2_when_every_item_is_a_tie(env, tmp_path, capsys):
    e = pilot_world(env, tmp_path)

    def tie(row, _):
        row.update(choice="tie", strength="")

    rewrite_answers(e, "pilot", tie)
    capsys.readouterr()
    rc = run("pilot-score", e, "--name", "pilot")
    lines = printed(capsys)
    assert rc == 3 and lines[1] == "check 2 discrimination: FAIL" and lines[-1] == "pilot: FAIL"
    assert pilot_checks_of(e)["overall"] is False


def test_pilot_score_fails_check_1_when_the_repeats_disagree(env, tmp_path, capsys):
    e = pilot_world(env, tmp_path)

    def flip_repeats(row, item):
        if item["repeat_of"] and row["choice"] in ("A", "B"):
            row["choice"] = "B" if row["choice"] == "A" else "A"

    rewrite_answers(e, "pilot", flip_repeats)
    capsys.readouterr()
    assert run("pilot-score", e, "--name", "pilot") == 3
    assert printed(capsys)[0] == "check 1 self-consistency: FAIL"


def test_pilot_score_fails_check_3_when_the_median_time_is_90_s_or_more(env, tmp_path, capsys):
    e = pilot_world(env, tmp_path)
    rewrite_answers(e, "pilot", lambda row, _: row.update(seconds="90"))
    capsys.readouterr()
    assert run("pilot-score", e, "--name", "pilot") == 3
    assert printed(capsys)[2] == "check 3 cost: FAIL"


def test_pilot_score_refuses_model_judge_answers_and_a_dry_run_cannot_pass_check_3(
    env, tmp_path, capsys
):
    e = pilot_world(env, tmp_path, label="judge_model")
    with pytest.raises(SystemExit, match="model"):
        run("pilot-score", e, "--name", "pilot")
    capsys.readouterr()
    assert run("pilot-score", e, "--name", "pilot", "--allow-model-judge") == 3
    assert printed(capsys)[2] == "check 3 cost: FAIL"  # a model cannot time itself
    doc = json.loads((e.root / "results/m4_timing_pilot.json").read_text())
    assert doc["config"]["model_judged"] is True and "model-judged" in doc["what"]


def test_pilot_score_refuses_a_key_with_a_non_pilot_pantry(env, tmp_path):
    e = fresh(env, tmp_path)  # the world's "dev" sheet holds dev pantries
    with pytest.raises(SystemExit, match="pilot pool"):
        run("pilot-score", e, "--name", "dev")


# ---------------------------------------------------------------- commit order (RI3)


def commit_world(scored, tmp_path, order) -> SimpleNamespace:
    """A git repo whose pilot and dev key hashes and answers are committed in ``order``:
    a list of groups of path words, ``keys`` and ``answers``."""
    e = fresh(scored, tmp_path)
    (e.root / ".gitignore").write_text("pack/\nresults/\n")
    git(e.root, "init", "-q")
    git(e.root, "add", ".gitignore")
    git(e.root, "commit", "-q", "-m", "base")
    paths = {
        "keys": [f"data/eval/m4/key_sha256.{n}.txt" for n in ("pilot", "dev")],
        "answers": [f"data/eval/m4/answers.{n}.v1.csv" for n in ("pilot", "dev")],
    }
    for group in order:
        git(e.root, "add", *[p for word in group for p in paths[word]])
        git(e.root, "commit", "-q", "-m", "+".join(group))
    return e


def every_result(e):
    return [json.loads(p.read_text()) for p in sorted((e.root / "results").glob("m4_*.json"))]


def test_dev_score_and_train_pass_when_the_key_hashes_come_first_and_say_so(scored, tmp_path):
    e = commit_world(scored, tmp_path, [("keys",), ("answers",)])
    assert run_strict("dev-score", e, "--name", "pilot", "dev") == 0
    assert run_strict("train", e, "--name", "pilot", "dev") == 0
    docs = [d for d in every_result(e) if "commit_order_checked" in d["config"]]
    assert len(docs) >= 6  # dev pairs, three arms, cv, the model arm
    assert all(d["config"]["commit_order_checked"] is True for d in docs)


@pytest.mark.parametrize(
    "order,word",
    [
        ([("keys", "answers")], "different commits"),
        ([("answers",), ("keys",)], "before"),
        ([("keys",)], "answers"),
    ],
)
def test_dev_score_refuses_a_wrong_commit_order(scored, tmp_path, order, word):
    e = commit_world(scored, tmp_path, order)
    with pytest.raises(SystemExit, match=word):
        run_strict("dev-score", e, "--name", "pilot", "dev")


def test_dev_score_outside_git_refuses_without_the_flag_and_marks_every_file_with_it(
    scored, tmp_path
):
    e = fresh(scored, tmp_path)
    for cmd in ("dev-score", "train"):
        with pytest.raises(SystemExit, match="commit order"):
            run_strict(cmd, e, "--name", "pilot", "dev")
    assert run("dev-score", e, "--name", "pilot", "dev") == 0
    assert run("train", e, "--name", "pilot", "dev") == 0
    docs = [d for d in every_result(e) if "commit_order_checked" in d["config"]]
    assert len(docs) >= 6 and all(d["config"]["commit_order_checked"] is False for d in docs)


def test_pilot_and_futility_also_check_the_commit_order(env, tmp_path):
    e = pilot_world(env, tmp_path)
    with pytest.raises(SystemExit, match="commit order"):
        run_strict("pilot-score", e, "--name", "pilot")
    assert run("pilot-score", e, "--name", "pilot") == 0
    assert pilot_checks_of(e)["overall"] is True
    doc = json.loads((e.root / "results/m4_timing_pilot.json").read_text())
    assert doc["config"]["commit_order_checked"] is False


# ---------------------------------------------------------------- keys, fingerprint, draw


def test_dev_score_records_the_flags_of_the_keys_and_refuses_a_key_without_them(env, tmp_path):
    e = fresh(env, tmp_path)
    assert run("dev-score", e, "--name", "pilot", "dev") == 0
    cfg = json.loads((e.root / "results/m4_dev_pairs.json").read_text())["config"]
    assert cfg["gold_out"] is True and cfg["neutral_order"] is True
    for flag in ("gold_out", "neutral_order"):
        path = e.root / "data/interim/judging_key.m4-dev.v1.json"
        key = json.loads(path.read_text())
        key[flag] = False
        path.write_text(json.dumps(key, indent=2, sort_keys=True) + chr(10))
        (e.root / "data/eval/m4/key_sha256.dev.txt").write_text(sha(path) + chr(10))
        with pytest.raises(
            SystemExit, match=flag.replace("_", " ").replace("gold out", "gold-out")
        ):
            run("dev-score", e, "--name", "pilot", "dev")


def test_dev_docs_take_the_flags_from_the_caller():
    merged = {"pairs": {}, "would_cook": {}, "n_base": 0}
    rule = m4_run.choose_rule({})
    docs = m4_run.dev_docs(
        merged, rule, names=["dev"], pack_sha="x", corpus_fingerprint="fp", model_judged=False,
        command="c", commit_order_checked=True, gold_out=False, neutral_order=False,
    )  # fmt: skip
    assert docs["m4_dev_pairs"]["config"]["gold_out"] is False
    assert docs["m4_dev_pairs"]["config"]["neutral_order"] is False
    assert docs["m4_arm_shipped"]["config"]["gold_out"] is False


def test_every_dev_and_train_result_file_carries_the_pack_fingerprint(trained):
    """RI7: one corpus fingerprint everywhere, the one the pack itself states."""
    want = trained.pack.info.corpus_fingerprint
    names = ["m4_dev_pairs", "m4_arm_overlap", "m4_arm_shipped", "m4_arm_idf_flat", "m4_cv"]
    names.append("m4_arm_rank_linear")
    for stem in names:
        doc = results.load_result(trained.root / f"results/{stem}.json")
        assert doc["corpus_fingerprint"] == want, stem


def test_pantries_refuses_a_draw_with_duplicate_content_before_it_writes(
    env, tmp_path, monkeypatch
):
    """RI9: the old code wrote the files and then returned 1."""
    e = fresh(env, tmp_path)
    shutil.rmtree(e.root / "data/eval/m4")
    stats = {"usable_dev": 1, "duplicates": [["m4-dev-a", "m4-test-b"]]}
    monkeypatch.setattr(m4, "build_pools", lambda *a, **k: (e.doc, stats))
    with pytest.raises(SystemExit, match="same content"):
        run("pantries", e)
    assert not (e.root / "data/eval/m4").exists()  # nothing written


# ---------------------------------------------------------------- train, stale weights (RI1)


def test_train_removes_stale_weights_when_check_1_fails(trained, tmp_path, monkeypatch, capsys):
    e = fresh(trained, tmp_path)
    assert (e.root / "web/src/rank_model.v1.json").exists()
    assert (e.root / "results/m4_arm_rank_linear.json").exists()
    monkeypatch.setattr(pw, "check_futility_1", lambda ll: {"pass": False, "outer_logloss": ll})
    capsys.readouterr()
    assert run("train", e, "--name", "pilot", "dev") == 3
    assert printed(capsys)[0] == "STOP"
    assert not (e.root / "web/src/rank_model.v1.json").exists()  # an old model must not linger
    assert not (e.root / "results/m4_arm_rank_linear.json").exists()


def test_futility_refuses_weights_that_name_another_comparator_than_the_dev_pairs(
    trained, tmp_path
):
    e = futility_world(trained, tmp_path, flip=False)
    w = e.root / "web/src/rank_model.v1.json"
    d = json.loads(w.read_text())
    d["comparator"] = "idf_flat" if d["comparator"] == "shipped" else "shipped"
    w.write_text(json.dumps(d))
    with pytest.raises(SystemExit, match="comparator"):
        run("futility", e)


def test_futility_result_records_the_weights_hash_the_freeze_checks(trained, tmp_path):
    e = futility_world(trained, tmp_path, flip=False)
    run("futility", e)
    doc = json.loads((e.root / "results/m4_futility.json").read_text())
    assert doc["config"]["weights_sha256"] == sha(e.root / "web/src/rank_model.v1.json")
    assert doc["corpus_fingerprint"] == e.pack.info.corpus_fingerprint


# ---------------------------------------------------------------- futility


def futility_world(trained, tmp_path, *, flip):
    e = fresh(trained, tmp_path)
    w = diverse_weights(e)
    comparator = json.loads(w.read_text())["comparator"]
    rc = sj.main(
        ["--pack", str(e.pack_dir), "--pantries", str(e.pf), "--pool", "futility", "--arms",
         "rank_linear", comparator, "--model", str(w), "--name", "futility", "--out-dir",
         str(e.root)]
    )  # fmt: skip
    assert rc == 0
    orderers = {"rank_linear": model_orderer(e.pack, load_model(w))}
    synth_answers(e, "futility", flip=flip, orderers=orderers)
    return e


def test_futility_goes_when_the_model_wins_more(trained, tmp_path, capsys):
    e = futility_world(trained, tmp_path, flip=False)
    capsys.readouterr()
    rc = run("futility", e)
    lines = printed(capsys)
    doc = results.load_result(e.root / "results/m4_futility.json")
    verdict = doc["config"]["futility"]
    assert only_go_stop_and_paths(lines), lines
    assert (rc, lines[0]) == ((3, "STOP") if verdict["stop"] else (0, "GO"))
    assert verdict["stop"] == (verdict["W"] <= verdict["L"])
    assert doc["comparisons"] == [] or doc["comparisons"][0]["split"] == "futility"
    assert all(m["split"] == "futility" for m in doc["metrics"])


def test_futility_stops_when_the_rule_wins_more(trained, tmp_path):
    """The flipped judge swaps every win and loss. Whichever side the rule wins on, W <= L stops."""
    got = {}
    for flip in (False, True):
        e = futility_world(trained, tmp_path / str(flip), flip=flip)
        run("futility", e)
        got[flip] = json.loads((e.root / "results/m4_futility.json").read_text())["config"][
            "futility"
        ]
    a, b = got[False], got[True]
    assert (a["W"], a["L"]) == (b["L"], b["W"]) and a["W"] != a["L"]
    assert sorted((a["stop"], b["stop"])) == [False, True]
    assert all(g["stop"] == (g["W"] <= g["L"]) for g in (a, b))


def test_futility_refuses_when_the_weights_changed_after_the_sheet(trained, tmp_path):
    e = futility_world(trained, tmp_path, flip=False)
    w = e.root / "web/src/rank_model.v1.json"
    w.write_text(w.read_text() + " ")
    with pytest.raises(SystemExit, match="weights"):
        run("futility", e)


def test_futility_refuses_model_judge_answers_unless_allowed(trained, tmp_path):
    e = futility_world(trained, tmp_path, flip=False)
    orderers = {
        "rank_linear": model_orderer(e.pack, load_model(e.root / "web/src/rank_model.v1.json"))
    }
    synth_answers(e, "futility", label="judge_model", orderers=orderers)
    with pytest.raises(SystemExit, match="model"):
        run("futility", e)
    assert run("futility", e, "--allow-model-judge") in (0, 3)
    doc = json.loads((e.root / "results/m4_futility.json").read_text())
    assert "model-judged" in doc["what"]


# ---------------------------------------------------------------- freeze and score (real git)


def git_world(trained, tmp_path) -> SimpleNamespace:
    """A git repo with every frozen input and every gate file committed.

    The plan sits in the repo (``docs/plans``), the UI decision says yes, the futility result says
    GO and the weights have mixed signs. Only the freeze and the test files are still to come.
    """
    e = fresh(trained, tmp_path)
    weights = diverse_weights(e)
    for rel in pw.FREEZE_FILES:
        p = e.root / rel
        if not p.exists() and rel != "data/eval/m4/analysis_plan.v1.md":
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"# stub {rel}\n", encoding="utf-8", newline="\n")
    write_json(
        e.root / "data/eval/m4/ui_decision.v1.json",
        {"approved": True, "decided_on": "2026-11-18", "text": "yes"},
    )
    plan = e.root / "docs/plans/2026-11-18-m4-search-ranking.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(PLAN, encoding="utf-8", newline="\n")
    comparator = json.loads(weights.read_text())["comparator"]
    write_json(  # the shape of the real futility result, only the keys the gates read
        e.root / "results/m4_futility.json",
        {
            "config": {
                "futility": {"W": 3, "L": 1, "stop": False, "comparator": comparator},
                "comparator": comparator,
                "model_judged": False,
                "weights_sha256": sha(weights),
            }
        },
    )
    (e.root / ".gitignore").write_text("pack/\n")  # the pack is not committed, as in the repo
    git(e.root, "init", "-q")
    git(e.root, "add", "-A")
    git(e.root, "commit", "-q", "-m", "base")
    return e


def write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + chr(10), encoding="utf-8", newline=chr(10))


def edit_json(e, rel: str, fn) -> None:
    """Change a JSON file of the world and commit it, so the tree stays clean."""
    path = e.root / rel
    doc = json.loads(path.read_text())
    fn(doc)
    write_json(path, doc)
    git(e.root, "commit", "-q", "-am", f"edit {rel}")


def test_freeze_dry_run_prints_what_would_be_frozen_and_writes_nothing(trained, tmp_path, capsys):
    e = git_world(trained, tmp_path)
    capsys.readouterr()
    rc = run("freeze", e, "--dry-run")
    out = capsys.readouterr().out
    assert rc == 0 and "GO" in out, out
    assert f"{len(pw.FREEZE_FILES)} files" in out
    assert "analysis_plan.v1.md" in out
    assert not (e.root / "data/eval/m4/analysis_plan.v1.md").exists()
    assert not (e.root / "data/eval/m4/freeze.v1.json").exists()
    assert "shipped" not in out and "idf_flat" not in out  # the comparator stays hidden


def test_freeze_dry_run_lists_blockers_on_a_dirty_tree(trained, tmp_path, capsys):
    e = git_world(trained, tmp_path)
    (e.root / "web/src/rank_model.v1.json").write_text("changed\n")
    rc = run("freeze", e, "--dry-run")
    out = capsys.readouterr().out
    assert rc == 3 and "STOP" in out and "not clean" in out
    assert not (e.root / "data/eval/m4/freeze.v1.json").exists()


def test_freeze_dry_run_outside_git_is_a_stop(trained, tmp_path, capsys):
    e = fresh(trained, tmp_path)
    rc = run("freeze", e, "--dry-run")
    assert rc == 3 and "STOP" in capsys.readouterr().out


def test_freeze_has_no_plan_option_and_copies_the_plan_of_the_repo(trained, tmp_path):
    """RI2: the plan always comes from docs/plans/2026-11-18-m4-search-ranking.md in the root."""
    e = git_world(trained, tmp_path)
    with pytest.raises(SystemExit):
        run("freeze", e, "--plan", str(tmp_path / "other.md"))
    (e.root / "docs/plans/2026-11-18-m4-search-ranking.md").unlink()
    git(e.root, "commit", "-q", "-am", "no plan")
    with pytest.raises(SystemExit, match="plan"):
        run("freeze", e)
    assert not (e.root / "data/eval/m4/freeze.v1.json").exists()


def test_freeze_writes_the_plan_copy_and_the_freeze_on_a_clean_tree(trained, tmp_path, capsys):
    e = git_world(trained, tmp_path)
    capsys.readouterr()
    assert run("freeze", e) == 0
    lines = printed(capsys)
    assert only_go_stop_and_paths(lines), lines
    plan_copy = (e.root / "data/eval/m4/analysis_plan.v1.md").read_text(encoding="utf-8")
    assert plan_copy == m4_run.section_6_1(PLAN)
    fr = json.loads((e.root / "data/eval/m4/freeze.v1.json").read_text())
    assert list(fr["files"]) == list(pw.FREEZE_FILES)  # every file of plan step 12
    assert fr["files"]["data/eval/m4/analysis_plan.v1.md"] == sha(
        e.root / "data/eval/m4/analysis_plan.v1.md"
    )
    assert fr["pack_core_sha256"] == e.doc["pack_core_sha256"]
    assert (
        fr["test_pool_sha256"]
        == (e.root / "data/eval/m4/test_pantries_sha256.txt").read_text().strip()
    )
    pairs = json.loads((e.root / "results/m4_dev_pairs.json").read_text())["config"]
    assert (fr["comparator"], fr["n_test"], fr["seed"]) == (pairs["comparator"], 100, 42)
    assert len(fr["commit"]) == 40


def test_freeze_refuses_a_dirty_tree_and_writes_nothing(trained, tmp_path):
    e = git_world(trained, tmp_path)
    (e.root / "web/src/rank_model.v1.json").write_text("changed\n")
    with pytest.raises(SystemExit, match="not clean"):
        run("freeze", e)
    assert not (e.root / "data/eval/m4/freeze.v1.json").exists()
    assert not (e.root / "data/eval/m4/analysis_plan.v1.md").exists()


def test_freeze_refuses_a_different_pack(trained, tmp_path):
    e = git_world(trained, tmp_path)
    doc = json.loads(e.pf.read_text())
    doc["pack_core_sha256"] = "0" * 64
    e.pf.write_text(json.dumps(doc))
    git(e.root, "commit", "-q", "-am", "pin another pack")
    with pytest.raises(SystemExit, match="pack"):
        run("freeze", e)


# ---------------------------------------------------------------- the freeze gates (RI1)


def refused(e, word):
    with pytest.raises(SystemExit, match=word):
        run("freeze", e)
    assert not (e.root / "data/eval/m4/freeze.v1.json").exists()


@pytest.mark.parametrize("approved", [False, "no", "maybe", None])
def test_freeze_stops_unless_the_ui_decision_is_yes(trained, tmp_path, approved):
    e = git_world(trained, tmp_path)
    edit_json(e, "data/eval/m4/ui_decision.v1.json", lambda d: d.update(approved=approved))
    refused(e, "UI decision")


def test_freeze_accepts_a_yes_in_words_and_needs_the_file(trained, tmp_path):
    e = git_world(trained, tmp_path)
    edit_json(e, "data/eval/m4/ui_decision.v1.json", lambda d: d.update(approved="yes"))
    assert run("freeze", e, "--dry-run") == 0
    (e.root / "data/eval/m4/ui_decision.v1.json").unlink()
    git(e.root, "commit", "-q", "-am", "no decision")
    refused(e, "ui_decision")


def test_freeze_needs_a_futility_go_and_a_passed_check_1(trained, tmp_path):
    e = git_world(trained, tmp_path)
    edit_json(e, "results/m4_futility.json", lambda d: d["config"]["futility"].update(stop=True))
    refused(e, "check 2")
    edit_json(e, "results/m4_futility.json", lambda d: d["config"]["futility"].update(stop=False))
    assert run("freeze", e, "--dry-run") == 0
    edit_json(e, "results/m4_cv.json", lambda d: d["config"]["check1"].update(**{"pass": False}))
    refused(e, "check 1")


def test_freeze_needs_the_futility_result_at_all(trained, tmp_path):
    e = git_world(trained, tmp_path)
    (e.root / "results/m4_futility.json").unlink()
    git(e.root, "commit", "-q", "-am", "no futility")
    refused(e, "m4_futility")


def test_freeze_refuses_model_judged_results(trained, tmp_path):
    e = git_world(trained, tmp_path)
    edit_json(e, "results/m4_futility.json", lambda d: d["config"].update(model_judged=True))
    refused(e, "model-judged")


def test_freeze_cross_checks_the_comparator_between_weights_and_results(trained, tmp_path):
    e = git_world(trained, tmp_path)
    other = (
        "idf_flat"
        if json.loads((e.root / WEIGHTS_REL).read_text())["comparator"] == "shipped"
        else "shipped"
    )
    edit_json(e, "results/m4_futility.json", lambda d: d["config"].update(comparator=other))
    refused(e, "comparator")


def test_freeze_cross_checks_the_weights_and_the_table_on_disk(trained, tmp_path):
    e = git_world(trained, tmp_path)
    edit_json(e, "results/m4_futility.json", lambda d: d["config"].update(weights_sha256="0" * 64))
    refused(e, "other weights")
    edit_json(
        e,
        "results/m4_futility.json",
        lambda d: d["config"].update(weights_sha256=sha(e.root / WEIGHTS_REL)),
    )
    edit_json(e, "data/eval/m4/train_table.v1.json", lambda d: d.update(note="edited"))
    refused(e, "training table")


WEIGHTS_REL = "web/src/rank_model.v1.json"


# ---------------------------------------------------------------- score (real git)


def committed_test_sheet(e, *, pool=None):
    """Freeze, then the test sheet, key hash and answers, one commit each and in that order.

    ``pool`` replaces the test pool the sheet is built from (a wrong selection, for RF7).
    """
    assert run("freeze", e, "--n-test", "6") == 0
    git(e.root, "add", "data/eval/m4/analysis_plan.v1.md", "data/eval/m4/freeze.v1.json")
    git(e.root, "commit", "-q", "-m", "freeze")
    weights = e.root / "web/src/rank_model.v1.json"
    comparator = json.loads(weights.read_text())["comparator"]
    orderers = {"rank_linear": model_orderer(e.pack, load_model(weights))}
    sheet, key = sj.build_pool_sheet(
        e.pack, pool or e.doc["pools"]["test"], ("rank_linear", comparator), seed=42,
        name="test", take=6, repeats=1, orderers=orderers, skip_identical=True,
        probe_pantries=e.doc["pools"]["dev"], probes=2, probe_arms=("shipped", "idf_flat"),
        config={"pool": "test", "pack_core_sha256": e.doc["pack_core_sha256"],
                "model_sha256": sha(weights), "arm_guess": True},
    )  # fmt: skip
    sj.write_outputs(
        sheet, key, e.root / "data/eval/m4/sheet.test.v1.json",
        e.root / "data/interim/judging_key.m4-test.v1.json",
        e.root / "data/eval/m4/key_sha256.test.txt",
    )  # fmt: skip
    git(e.root, "add", "data/eval/m4/key_sha256.test.txt")
    git(e.root, "commit", "-q", "-m", "key hash")
    synth_answers(e, "test", arm_guess=True, orderers=orderers)
    return comparator


def test_score_refuses_before_the_freeze_is_committed_and_writes_nothing(trained, tmp_path, capsys):
    e = git_world(trained, tmp_path)
    capsys.readouterr()
    rc = run("score", e)
    out = capsys.readouterr().out
    assert rc == 3 and out.splitlines()[0] == "STOP"
    assert not (e.root / "results/m4_test.json").exists()


def test_score_runs_when_every_freeze_rule_passes(trained, tmp_path, capsys):
    e = git_world(trained, tmp_path)
    comparator = committed_test_sheet(e)
    git(e.root, "add", "data/eval/m4/answers.test.v1.csv")
    git(e.root, "commit", "-q", "-m", "answers")
    capsys.readouterr()
    rc = run("score", e)
    lines = printed(capsys)
    assert rc in (0, 3) and lines[0] in ("GO", "STOP"), lines
    assert only_go_stop_and_paths(lines), lines
    doc = results.load_result(e.root / "results/m4_test.json")
    assert doc["config"]["comparator"] == comparator
    assert doc["config"]["analysis"]["primary"]["model"] == "rank_linear"
    assert doc["config"]["freeze_commit"] and "probe_agreement" in doc["config"]["analysis"]
    assert doc["corpus_fingerprint"] == e.pack.info.corpus_fingerprint  # RI7


def test_score_stops_when_the_key_holds_another_selection_than_the_frozen_one(
    trained, tmp_path, capsys
):
    """RF7: the test sheet was built from the pool in another order, so it holds other pantries."""
    e = git_world(trained, tmp_path)
    committed_test_sheet(e, pool=list(reversed(e.doc["pools"]["test"])))
    git(e.root, "add", "data/eval/m4/answers.test.v1.csv")
    git(e.root, "commit", "-q", "-m", "answers")
    capsys.readouterr()
    assert run("score", e) == 3
    out = capsys.readouterr().out
    assert "STOP" in out and "frozen selection" in out
    assert not (e.root / "results/m4_test.json").exists()


def test_score_stops_on_a_changed_frozen_file_or_a_second_answers_commit(trained, tmp_path, capsys):
    e = git_world(trained, tmp_path)
    committed_test_sheet(e)
    git(e.root, "add", "data/eval/m4/answers.test.v1.csv")
    git(e.root, "commit", "-q", "-m", "answers")
    (e.root / "data/eval/m4/answers.test.v1.csv").write_text(
        (e.root / "data/eval/m4/answers.test.v1.csv").read_text() + "\n"
    )
    git(e.root, "commit", "-q", "-am", "edit the answers")  # a second commit of the answers
    capsys.readouterr()
    assert run("score", e) == 3
    out = capsys.readouterr().out
    assert "STOP" in out and "exactly one commit" in out
    assert not (e.root / "results/m4_test.json").exists()
    # a frozen file changes after the freeze
    e2 = git_world(trained, tmp_path / "again")
    committed_test_sheet(e2)
    git(e2.root, "add", "data/eval/m4/answers.test.v1.csv")
    git(e2.root, "commit", "-q", "-m", "answers")
    (e2.root / "web/src/rank_model.v1.json").write_text("edited after the freeze\n")
    git(e2.root, "commit", "-q", "-am", "edit")
    capsys.readouterr()
    assert run("score", e2) == 3
    assert "rank_model.v1.json" in capsys.readouterr().out
