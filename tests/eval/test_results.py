import copy
import json
import subprocess
from pathlib import Path

import pytest

from pantrychef.eval import results
from pantrychef.eval.results import (
    ARMS,
    METRICS,
    MetricSpec,
    NotSelectable,
    assert_selectable,
    git_facts,
    load_result,
    validate,
    write_result,
)

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40


def doc():
    return {
        "schema": 1,
        "label": "MEASURED",
        "what": "w",
        "command": "c",
        "commit": SHA,
        "dirty": False,
        "dirty_paths": [],
        "config": {},
        "seed": 1,
        "corpus_fingerprint": "f",
        "arms": [{"name": "overlap", "features_used": ["have", "total"]}],
        "metrics": [
            {
                "name": "recall_at_10",
                "role": "sanity",
                "depends_on": ["gold_recipe_lines", "have", "total", "idf"],
                "arm": "overlap",
                "split": "test",
                "n": 10,
                "value": 0.5,
            }
        ],
        "comparisons": [],
        "environment": {},
    }


def git(root, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    (tmp_path / "a.txt").write_text("a")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


# ---- git_facts ----


def test_git_clean(repo):
    commit, dirty, paths = git_facts(repo)
    assert len(commit) == 40
    assert (dirty, paths) == (False, [])


def test_git_tracked_change_is_dirty(repo):
    (repo / "a.txt").write_text("changed")
    assert git_facts(repo)[1:] == (True, ["a.txt"])


def test_git_untracked_is_dirty_but_ignored_is_not(repo):
    (repo / "ignored.txt").write_text("x")
    assert git_facts(repo)[1] is False
    (repo / "new.txt").write_text("x")  # scratch file outside the code folders: not dirty
    assert git_facts(repo)[1] is False
    (repo / "scripts").mkdir()
    (repo / "scripts" / "new.py").write_text("x")
    assert git_facts(repo)[1:] == (True, ["scripts/new.py"])


def test_git_exclude_and_results_dir(repo):
    (repo / "scripts").mkdir()
    (repo / "scripts" / "out.json").write_text("{}")
    (repo / "results").mkdir()
    (repo / "results" / "other.json").write_text("{}")
    assert git_facts(repo, exclude=(repo / "scripts" / "out.json",))[1:] == (False, [])
    assert git_facts(repo)[2] == ["scripts/out.json"]


def test_git_dirty_paths_capped_at_20(repo):
    for i in range(25):
        (repo / "scripts").mkdir(exist_ok=True)
        (repo / "scripts" / f"f{i:02}.txt").write_text("x")
    _, dirty, paths = git_facts(repo)
    assert dirty and len(paths) == 20


# ---- validate ----


def test_valid_doc_passes():
    validate(doc())


@pytest.mark.parametrize(
    "key",
    [
        "schema", "label", "what", "command", "commit", "dirty", "dirty_paths", "config",
        "seed", "corpus_fingerprint", "arms", "metrics", "comparisons", "environment",
    ],
)  # fmt: skip
def test_missing_required_key(key):
    d = doc()
    del d[key]
    with pytest.raises(ValueError, match=key):
        validate(d)


@pytest.mark.parametrize(
    "key,bad",
    [
        ("schema", 2),
        ("label", "GUESS"),
        ("what", ""),
        ("commit", "xyz"),
        ("commit", "A" * 40),
        ("dirty", "no"),
        ("dirty_paths", "a"),
        ("dirty_paths", ["a"] * 21),
        ("config", []),
        ("seed", 1.5),
        ("seed", True),
        ("corpus_fingerprint", ""),
        ("arms", {}),
        ("metrics", {}),
        ("comparisons", None),
        ("environment", []),
        ("raw", []),
    ],
)
def test_wrong_type_or_value(key, bad):
    d = doc()
    d[key] = bad
    with pytest.raises(ValueError):
        validate(d)


@pytest.mark.parametrize(
    "key,bad",
    [
        ("name", 3),
        ("role", "bogus"),
        ("depends_on", "x"),
        ("arm", 5),
        ("split", "train"),
        ("n", -1),
        ("n", 1.5),
        ("value", "0.5"),
        ("value", True),
        ("ci", {"lo": 0}),
        ("group", []),
    ],
)
def test_metric_field_errors(key, bad):
    d = doc()
    d["metrics"][0][key] = bad
    with pytest.raises(ValueError):
        validate(d)


def test_metric_missing_key():
    d = doc()
    del d["metrics"][0]["split"]
    with pytest.raises(ValueError, match="split"):
        validate(d)


def test_good_ci_and_group_pass():
    d = doc()
    d["metrics"][0]["ci"] = {"lo": 0.1, "hi": 0.9, "level": 0.95, "method": "m", "n_clusters": 3}
    d["metrics"][0]["group"] = {"pantry_size": 3}
    validate(d)


def test_registry_checks():
    d = doc()
    d["metrics"][0]["name"] = "made_up"
    with pytest.raises(ValueError, match="made_up"):
        validate(d)
    d = doc()
    d["metrics"][0]["role"] = "selection"
    with pytest.raises(ValueError, match="role"):
        validate(d)
    d = doc()
    d["metrics"][0]["depends_on"] = []
    with pytest.raises(ValueError, match="depends_on"):
        validate(d)
    d = doc()
    d["metrics"][0]["arm"] = "ghost"
    with pytest.raises(ValueError, match="ghost"):
        validate(d)
    d = doc()
    d["arms"][0]["name"] = "ghost"
    with pytest.raises(ValueError, match="ghost"):
        validate(d)
    d = doc()
    d["arms"][0]["features_used"] = ["idf"]
    with pytest.raises(ValueError, match="features_used"):
        validate(d)


def test_comparison_checks():
    d = doc()
    d["comparisons"] = [
        {"metric": "recall_at_10", "role": "sanity", "a": "shipped", "b": "overlap",
         "split": "test", "diff": 0.1,
         "ci": {"lo": 0.0, "hi": 0.2, "level": 0.95, "method": "m", "n_clusters": 3}}
    ]  # fmt: skip
    validate(d)
    bad = copy.deepcopy(d)
    bad["comparisons"][0]["role"] = "selection"
    with pytest.raises(ValueError, match="role"):
        validate(bad)
    bad = copy.deepcopy(d)
    bad["comparisons"][0]["ci"] = {}
    with pytest.raises(ValueError, match="lo"):
        validate(bad)
    bad = copy.deepcopy(d)
    bad["comparisons"][0]["metric"] = "nope"
    with pytest.raises(ValueError, match="nope"):
        validate(bad)
    bad = copy.deepcopy(d)
    bad["comparisons"][0]["a"] = "nope"
    with pytest.raises(ValueError, match="nope"):
        validate(bad)
    bad = copy.deepcopy(d)
    del bad["comparisons"][0]["diff"]
    with pytest.raises(ValueError, match="diff"):
        validate(bad)


# ---- write_result / load_result ----


def test_write_and_load_roundtrip(repo):
    out = repo / "results" / "x.json"
    d = doc()
    d["commit"] = "0" * 40  # the caller cannot choose the commit
    d["dirty"] = True
    written = write_result(out, d, root=repo)
    assert written["commit"] == git_facts(repo)[0]
    assert written["dirty"] is False  # the result file is excluded
    assert set(written["environment"]) >= {"python", "platform"}
    raw = out.read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw
    text = raw.decode()
    assert text.startswith('{\n  "arms"')  # sorted keys, indent 2
    assert json.loads(text) == load_result(out)


def test_write_rejects_invalid(repo):
    d = doc()
    d["metrics"][0]["name"] = "made_up"
    with pytest.raises(ValueError):
        write_result(repo / "x.json", d, root=repo)
    assert not (repo / "x.json").exists()


def test_load_rejects_invalid(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"schema": 1}')
    with pytest.raises(ValueError):
        load_result(p)


def test_node_sample_loads():
    sample = Path(__file__).resolve().parents[1] / "fixtures" / "results" / "node_sample.json"
    d = load_result(sample)
    assert d["metrics"][0]["role"] == "latency"


# ---- registries and assert_selectable ----


def test_registry_contents():
    assert ARMS == {
        "random": (),
        "overlap": ("have", "total"),
        "idf_flat": ("idf", "have", "total"),
        "shipped": ("idf", "have", "total", "group"),
    }
    assert METRICS["recall_at_10"].role == "sanity"
    assert METRICS["mrr_at_10"].depends_on == ("gold_recipe_lines", "have", "total", "idf")
    assert METRICS["makeable_at_10"].role == "product"
    assert METRICS["hit_rate"].role == "product"
    assert METRICS["visible_rate"].depends_on == ("have", "total", "idf", "group")
    assert METRICS["pairwise_win_rate"].role == "selection"
    assert METRICS["pairwise_win_rate"].depends_on == ()
    for n in ("latency_p50_ms", "latency_p95_ms", "latency_max_ms"):
        assert METRICS[n].role == "latency"


def test_sanity_metric_not_selectable():
    with pytest.raises(NotSelectable):
        assert_selectable("recall_at_10", list(ARMS))
    with pytest.raises(NotSelectable):
        assert_selectable("visible_rate", ["random"])


def test_shared_feature_not_selectable(monkeypatch):
    spec = MetricSpec("selection", ("idf", "x"), "claimed independent")
    monkeypatch.setitem(results.METRICS, "fake_selection", spec)
    with pytest.raises(NotSelectable, match="idf"):
        assert_selectable("fake_selection", ["overlap", "shipped"])
    assert_selectable("fake_selection", ["random", "overlap"])  # no shared feature


def test_pairwise_win_rate_selectable_for_all_arms():
    assert_selectable("pairwise_win_rate", list(ARMS))


def test_every_selection_metric_has_justification():
    for name, spec in METRICS.items():
        if spec.role == "selection":
            assert spec.justification.strip(), name


def test_unknown_names_raise():
    with pytest.raises(ValueError):
        assert_selectable("nope", ["random"])
    with pytest.raises(ValueError):
        assert_selectable("pairwise_win_rate", ["nope"])


def test_product_and_sanity_metrics_share_features_with_arms():
    """Review fix R1: if a product or sanity metric were used to select, the dependency check
    must fail, because the metric reads the same features (have, total, idf) as the arms."""
    from pantrychef.eval import results as r

    for name in ("makeable_at_10", "hit_rate", "recall_at_10", "mrr_at_10", "visible_rate"):
        spec = r.METRICS[name]
        assert {"have", "total"} <= set(spec.depends_on), name
        promoted = r.MetricSpec("selection", spec.depends_on, "test only")
        old = r.METRICS[name]
        r.METRICS[name] = promoted
        try:
            with pytest.raises(r.NotSelectable):
                r.assert_selectable(name, ["overlap", "random"])
        finally:
            r.METRICS[name] = old


def test_every_results_file_validates():
    """Every committed results file passes the Python validator (the Node writer is not checked
    against the registry, so this is the one place that does it)."""
    from pantrychef.eval import results as r

    files = [p for p in (ROOT / "results").glob("*.json") if p.name != "schema.v1.json"]
    assert files
    for p in files:
        r.load_result(p)


def test_m3_metrics_registered():
    from pantrychef.eval import results as r

    for name in ("mention_accuracy", "input_accuracy", "agreed_error_rate", "recipes_fully_read"):
        spec = r.METRICS[name]
        assert spec.role == "product", name
        assert spec.justification.strip(), name
        with pytest.raises(r.NotSelectable):
            r.assert_selectable(name, ["random"])
    assert r.METRICS["mention_accuracy"].depends_on == ("ingredient_table", "parser_rules")
    assert r.METRICS["agreed_error_rate"].depends_on == ()
