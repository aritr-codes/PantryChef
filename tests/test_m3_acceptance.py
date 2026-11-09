"""M3 acceptance script: guards, scoring and the result file. Invented fixtures in tmp_path only.

No real held-out name or input appears here. The script's real path never runs in a test.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from pantrychef.eval.results import load_result
from pantrychef.eval.stats import mcnemar_exact
from scripts import m3_acceptance as acc

V1 = (
    "id,name,synonyms,staple,provenance,is_a,form_of\n"
    "salt,salt,,1,hand,,\n"
    "black_pepper,black pepper,,1,hand,,\n"
    "butter,butter,,0,hand,,\n"
    "flour,flour,,0,hand,,\n"
)
V2 = V1 + "egg,egg,,0,hand,,\nthyme,thyme,dried thyme,0,hand,,\nghee,ghee,,0,hand,,\n"


def _label(*groups: list[str], skip: bool = False) -> dict:
    return {"groups": list(groups), "optional": False, "not_an_ingredient": skip}


def _write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf8")
    return path


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _lines(split: str, strata: dict[str, list[str]]) -> list[dict]:
    return [
        {"id": f"{split}-{s}-{i}", "text": t, "stratum": s, "split": split}
        for s, texts in strata.items()
        for i, t in enumerate(texts)
    ]


@pytest.fixture
def cfg(tmp_path) -> acc.Config:
    """A committed tmp repo, an invented v1 and v2 table, test+extra parser data, test inputs."""
    root = tmp_path / "repo"
    (root / "results").mkdir(parents=True)
    (root / ".gitignore").write_text("results/\n", encoding="utf8")
    d = root / "data"
    (d / "t1.csv").parent.mkdir(parents=True)
    (d / "t1.csv").write_text(V1, encoding="utf8")
    (d / "t2.csv").write_text(V2, encoding="utf8")
    sheet_lines = _lines(
        "test",
        {
            "random": ["2 cups flour", "1 egg", "3 tbsp butter"],
            "hard": ["1 tsp dried thyme"],
            "rare": ["1 knob ghee"],
        },
    ) + _lines("dev", {"random": ["1 tbsp butter"]})
    extra_lines = _lines("extra", {"random": ["4 eggs", "1 cup flour"]})
    _write(d / "sheet.json", {"snapshot_sha256": "ab" * 32, "lines": sheet_lines})
    _write(d / "extra.json", {"lines": extra_lines})
    names = {
        "test-random-0": ["flour"],
        "test-random-1": ["egg"],
        "test-random-2": ["butter"],
        "test-hard-0": ["thyme"],
        "test-rare-0": ["ghee"],
        "extra-random-0": ["egg"],
        "extra-random-1": ["flour"],
    }
    _write(
        d / "labels.test.json",
        {"labels": {k: _label(v) for k, v in names.items() if k.startswith("test")}},
    )
    _write(
        d / "labels.extra.json",
        {"labels": {k: _label(v) for k, v in names.items() if k.startswith("extra")}},
    )
    _write(d / "labels.dev.json", {"labels": {"dev-random-0": _label(["butter"])}})
    ids = {n: n for n in ("flour", "egg", "butter", "thyme", "ghee")}
    _write(d / "parser_map.json", {"version": 1, "mapper": "t", "map": ids})
    typed = {"butter": "butter", "egg": "egg", "ghee": "ghee", "thyme": "thyme"}
    split = {"assignment": {**dict.fromkeys(typed, "test"), "salt": "dev"}}
    _write(d / "inputs.split.json", split)
    _write(
        d / "inputs.labels.json",
        {"labels": {**{t: _label([t]) for t in typed}, "salt": _label(["salt"])}},
    )
    _write(d / "input_map.json", {"version": 1, "mapper": "t", "map": typed})
    _write(
        root / "results" / "pack.json",
        {
            "config": {"recipes": 2600, "recipes_fully_read_count": 1700, "core_bytes": 9},
            "metrics": [{"name": "recipes_fully_read", "value": 1700 / 2600}],
        },
    )
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    return acc.Config(
        root=root,
        split="test",
        sheet=d / "sheet.json",
        extra=d / "extra.json",
        parser_labels=(d / "labels.test.json", d / "labels.extra.json"),
        parser_map=d / "parser_map.json",
        input_split=d / "inputs.split.json",
        input_labels=d / "inputs.labels.json",
        input_map=d / "input_map.json",
        table_v1=d / "t1.csv",
        table_v2=d / "t2.csv",
        pack_result=root / "results" / "pack.json",
        out=root / "results" / "m3_acceptance.json",
        command="test",
        strict=True,
        expected={"test_lines": 5, "extra_lines": 2, "test_inputs": 4},
    )


def _commit(root: Path) -> None:
    _git(root, "add", "-A")
    _git(
        root,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-qm",
        "change",
        "--allow-empty",
    )


def _edit(path: Path, fn) -> None:
    """Edit a JSON fixture and commit it, so the tree stays clean."""
    doc = json.loads(path.read_text(encoding="utf8"))
    fn(doc)
    path.write_text(json.dumps(doc), encoding="utf8")
    _commit(path.parent.parent)


# ---- guards: each refuses with exit 1 and writes nothing ----------------------------------


def test_clean_tree_runs_and_writes(cfg):
    assert acc.run(cfg) == 0
    assert cfg.out.exists()


def test_dirty_tree_is_refused(cfg, capsys):
    (cfg.root / "stray.py").write_text("x = 1\n", encoding="utf8")
    assert acc.run(cfg) == 1
    assert not cfg.out.exists()
    assert "stray.py" in capsys.readouterr().out


def test_modified_tracked_file_is_refused(cfg):
    (cfg.root / "data" / "t2.csv").write_text(V2 + "kale,kale,,0,hand,,\n", encoding="utf8")
    assert acc.run(cfg) == 1
    assert not cfg.out.exists()


def test_known_untracked_scratch_does_not_count_as_dirty(cfg):
    for rel in (
        ".claude/a",
        ".codegraph/b",
        "CODEX_HANDOFF.md",
        "TestRun.md",
        "scratch_codex_audit_prompt.md",
        "temp_pytest/c",
        "data/interim/d",
        "data/eval/graph_spike/e",
    ):
        p = cfg.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf8")
    assert acc.run(cfg) == 0


def test_second_run_is_refused_and_the_file_is_untouched(cfg, capsys):
    assert acc.run(cfg) == 0
    first = cfg.out.read_bytes()
    assert acc.run(cfg) == 1
    assert cfg.out.read_bytes() == first
    assert "do not rescore" in capsys.readouterr().out


def test_missing_map_file_is_refused(cfg):
    cfg.parser_map.unlink()
    _commit(cfg.root)
    assert acc.run(cfg) == 1
    assert not cfg.out.exists()


def test_missing_input_map_file_is_refused(cfg):
    cfg.input_map.unlink()
    _commit(cfg.root)
    assert acc.run(cfg) == 1
    assert not cfg.out.exists()


@pytest.mark.parametrize("which", ["parser_map", "input_map"])
def test_gold_name_without_a_map_entry_is_refused(cfg, which, capsys):
    _edit(getattr(cfg, which), lambda d: d["map"].pop("ghee"))
    assert acc.run(cfg) == 1
    assert not cfg.out.exists()
    assert "ghee" in capsys.readouterr().out


@pytest.mark.parametrize("which", ["parser_map", "input_map"])
def test_id_outside_the_v2_table_is_refused(cfg, which, capsys):
    _edit(getattr(cfg, which), lambda d: d["map"].update(ghee="no_such_id"))
    assert acc.run(cfg) == 1
    assert not cfg.out.exists()
    assert "no_such_id" in capsys.readouterr().out


def test_unmapped_id_null_is_allowed(cfg):
    _edit(cfg.parser_map, lambda d: d["map"].update(ghee=None))
    assert acc.run(cfg) == 0


def test_label_name_missing_from_the_map_after_normalising_is_refused(cfg):
    # A gold name that differs from the map key by more than case and plural is not matched.
    _edit(cfg.parser_labels[1], lambda d: d["labels"]["extra-random-1"]["groups"].append(["kefir"]))
    assert acc.run(cfg) == 1
    assert not cfg.out.exists()


def test_label_missing_for_a_line_is_refused(cfg):
    _edit(cfg.parser_labels[0], lambda d: d["labels"].pop("test-hard-0"))
    assert acc.run(cfg) == 1
    assert not cfg.out.exists()


def test_wrong_set_size_is_refused(cfg):
    assert (
        acc.run(replace(cfg, expected={"test_lines": 6, "extra_lines": 2, "test_inputs": 4})) == 1
    )
    assert not cfg.out.exists()


def test_map_file_with_no_map_key_is_refused(cfg):
    _write(cfg.parser_map, {"version": 1, "mapper": "t"})
    _commit(cfg.root)
    assert acc.run(cfg) == 1


def test_empty_random_stratum_is_refused(cfg):
    _edit(cfg.sheet, lambda d: [r.update(stratum="hard") for r in d["lines"]])
    _edit(cfg.extra, lambda d: [r.update(stratum="hard") for r in d["lines"]])
    assert acc.run(cfg) == 1
    assert not cfg.out.exists()


def test_missing_pack_result_is_refused(cfg):
    cfg.pack_result.unlink()
    _commit(cfg.root)
    assert acc.run(cfg) == 1
    assert not cfg.out.exists()


# ---- scoring and the result file --------------------------------------------------------


def test_all_targets_met_result(cfg):
    assert acc.run(cfg) == 0
    doc = load_result(cfg.out)  # validates against the registry
    c = doc["config"]
    assert c["all_targets_met"] is True and c["stop_and_report"] is False
    t = {x["name"]: x for x in c["targets"]}
    assert set(t) == {
        "mention_accuracy_random",
        "parser_precision_random",
        "input_accuracy_m3",
        "recipes_fully_read",
        "recipes",
    }
    assert t["mention_accuracy_random"]["n"] == 5 and t["mention_accuracy_random"]["value"] == 1.0
    assert t["recipes"]["value"] == 2600 and t["recipes"]["target"] == 2500
    assert t["recipes_fully_read"]["target"] == 0.60
    assert all(x["status"] == "PASS" for x in t.values())
    assert 0 < t["mention_accuracy_random"]["wilson_lo"] < 1
    # random pools test (3) and extra (2) lines; hard and rare stay separate
    assert c["parser"]["random"]["lines"] == 5
    assert c["parser"]["hard"]["lines"] == 1 and c["parser"]["rare"]["lines"] == 1
    assert doc["config"]["pack"]["core_bytes"] == 9
    assert {m["split"] for m in doc["metrics"]} == {"test", "all"}


def test_m1_vs_m3_inputs_are_paired(cfg):
    # v1 has butter only; v2 reads egg, thyme and ghee too: M1 right on 1 of 4, M3 on 4 of 4.
    acc.run(cfg)
    inp = load_result(cfg.out)["config"]["inputs"]
    assert (inp["m1"]["correct"], inp["m3"]["correct"], inp["n"]) == (1, 4, 4)
    assert (inp["m3_only_correct"], inp["m1_only_correct"]) == (3, 0)
    assert inp["mcnemar_p"] == mcnemar_exact(3, 0)
    assert inp["diff"] == 0.75
    assert inp["bootstrap"]["seed"] == 46 and inp["bootstrap"]["resamples"] == 10_000
    assert inp["bootstrap"]["lo"] <= 0.75 <= inp["bootstrap"]["hi"]


def test_a_failed_target_is_reported_and_never_softened(cfg, capsys):
    # The M3 resolver misses "ghee" when the table v2 loses the row: 3 of 4 inputs, below 0.90.
    cfg.table_v2.write_text(V2.replace("ghee,ghee,,0,hand,,\n", ""), encoding="utf8")
    _commit(cfg.root)
    _edit(cfg.parser_map, lambda d: d["map"].update(ghee=None))
    _edit(cfg.input_map, lambda d: d["map"].update(ghee=None))
    assert acc.run(cfg) == 0
    c = load_result(cfg.out)["config"]
    t = {x["name"]: x for x in c["targets"]}
    assert t["input_accuracy_m3"]["status"] == "FAIL" and t["input_accuracy_m3"]["target"] == 0.90
    assert c["all_targets_met"] is False and c["stop_and_report"] is True
    assert "input_accuracy_m3" in c["failed"]
    assert "STOP AND REPORT" in capsys.readouterr().out


def test_status_is_exact_at_the_target():
    assert acc.status(0.9, 0.90) == "PASS"
    assert acc.status(135 / 150, 0.90) == "PASS"
    assert acc.status(0.8999, 0.90) == "FAIL"


def test_paired_counts_and_p_value():
    m1 = [1, 1, 0, 0, 0, 0, 0, 0, 0, 1]
    m3 = [1, 1, 1, 1, 1, 1, 1, 1, 1, 0]
    p = acc.paired(m1, m3, seed=46, resamples=500)
    assert (p["m3_only_correct"], p["m1_only_correct"]) == (7, 1)
    assert p["mcnemar_p"] == mcnemar_exact(7, 1) == 0.0703125
    assert p["diff"] == pytest.approx(0.6)


# ---- the dev path ----------------------------------------------------------------------


def test_dev_run_reads_dev_halves_only_and_writes_to_out(cfg, tmp_path):
    dev = replace(
        cfg,
        split="dev",
        extra=None,
        input_map=None,
        parser_labels=(cfg.parser_labels[0].parent / "labels.dev.json",),
        strict=False,
        expected=None,
        out=tmp_path / "dev_out.json",
    )
    # The test and extra files must not be opened: remove them.
    cfg.parser_labels[0].unlink()
    cfg.parser_labels[1].unlink()
    (cfg.root / "data" / "extra.json").unlink()
    assert acc.run(dev) == 0
    doc = load_result(dev.out)
    assert {m["split"] for m in doc["metrics"] if m["name"] != "recipes_fully_read"} == {"dev"}
    assert doc["config"]["parser"]["random"]["lines"] == 1
    assert doc["config"]["inputs"]["n"] == 1  # only the "salt" dev input


def test_dev_dry_run_never_writes_the_acceptance_path(cfg, monkeypatch):
    monkeypatch.setattr(acc, "RESULT", cfg.out)
    assert acc.main(["--dry-run-on", "dev", "--out", str(cfg.out)]) == 1
    assert not cfg.out.exists()


def test_dry_run_needs_out():
    with pytest.raises(SystemExit):
        acc.main(["--dry-run-on", "dev"])


def test_real_run_takes_no_out():
    with pytest.raises(SystemExit):
        acc.main(["--out", "x.json"])


def test_targets_are_the_plan_values():
    assert acc.TARGETS == {
        "mention_accuracy_random": 0.90,
        "parser_precision_random": 0.90,
        "input_accuracy_m3": 0.90,
        "recipes_fully_read": 0.60,
        "recipes": 2500,
    }
    assert acc.EXPECTED == {"test_lines": 150, "extra_lines": 100, "test_inputs": 83}
