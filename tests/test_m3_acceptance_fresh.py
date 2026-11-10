"""M3 acceptance run 2 script: guards, scoring, result file. Invented fixtures in tmp_path only.

No real held-out name appears here. The script's real path never runs in a test.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from pantrychef.eval.results import load_result
from pantrychef.ingredients.table import DEFAULT_WORDS_PATH
from scripts import m3_acceptance_fresh as fresh

TABLE = (
    "id,name,synonyms,staple,provenance,is_a,form_of\n"
    "salt,salt,,1,hand,,\n"
    "black_pepper,black pepper,,1,hand,,\n"
    "butter,butter,,0,hand,,\n"
    "flour,flour,,0,hand,,\n"
    "egg,egg,,0,hand,,\n"
)
LINES = {"f-0": "2 cups flour", "f-1": "1 egg", "f-2": "3 tbsp butter"}
NAMES = {"f-0": "flour", "f-1": "egg", "f-2": "butter"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _label(name: str) -> dict:
    return {"groups": [[name]], "optional": False, "not_an_ingredient": False}


def _write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf8")
    return path


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _commit(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "change", "--allow-empty")


@pytest.fixture
def cfg(tmp_path) -> fresh.Config:
    root = tmp_path / "repo"
    (root / "results").mkdir(parents=True)
    (root / ".gitignore").write_text("results/\n", encoding="utf8")
    d = root / "data"
    d.mkdir()
    (d / "t.csv").write_text(TABLE, encoding="utf8")
    lines = [{"id": k, "text": v, "stratum": "random", "split": "fresh"} for k, v in LINES.items()]
    _write(d / "fresh.json", {"snapshot_sha256": "ab" * 32, "lines": lines})
    _write(d / "labels.json", {"labels": {k: _label(n) for k, n in NAMES.items()}})
    _write(
        d / "map.json",
        {"version": 1, "mapper": "t", "owner_checked": True, "map": {n: n for n in NAMES.values()}},
    )
    _write(
        root / "results" / "pack.json",
        {
            "dirty": False,
            "config": {
                "recipes": 2600,
                "recipes_fully_read_count": 1700,
                "core_bytes": 9,
                "build_dirty": False,
                "table_sha256": _sha(d / "t.csv"),
                "words_sha256": _sha(DEFAULT_WORDS_PATH),
            },
            "metrics": [{"name": "recipes_fully_read", "value": 1700 / 2600}],
        },
    )
    _git(root, "init", "-q")
    _commit(root)
    return fresh.Config(
        root=root,
        fresh=d / "fresh.json",
        labels=d / "labels.json",
        id_map=d / "map.json",
        table=d / "t.csv",
        words=DEFAULT_WORDS_PATH,
        pack_result=root / "results" / "pack.json",
        out=root / "results" / "m3_acceptance_fresh.json",
        expected_lines=3,
        command="test",
    )


def test_clean_run_passes_and_writes(cfg, capsys):
    assert fresh.run(cfg) == 0
    doc = load_result(cfg.out)
    c = doc["config"]
    assert c["attempt"] == 2 and c["split"] == "fresh"
    assert c["all_targets_met"] is True and c["stop_and_report"] is False
    by = {t["name"]: t for t in c["targets"]}
    assert by["mention_accuracy_random"]["value"] == 1.0
    assert by["recipes_fully_read"]["status"] == "PASS"
    assert "STOP AND REPORT" not in capsys.readouterr().out


def test_failed_target_says_stop_and_report(cfg, capsys):
    pack = json.loads(cfg.pack_result.read_text(encoding="utf8"))
    pack["config"]["recipes_fully_read_count"] = 100
    pack["metrics"][0]["value"] = 100 / 2600
    cfg.pack_result.write_text(json.dumps(pack), encoding="utf8")
    _commit(cfg.root)
    assert fresh.run(cfg) == 0
    c = load_result(cfg.out)["config"]
    assert c["stop_and_report"] is True and c["failed"] == ["recipes_fully_read"]
    assert "STOP AND REPORT" in capsys.readouterr().out


def test_wrong_prediction_lowers_mention_accuracy(cfg):
    labels = json.loads(cfg.labels.read_text(encoding="utf8"))
    labels["labels"]["f-1"] = _label("salt")
    cfg.labels.write_text(json.dumps(labels), encoding="utf8")
    m = json.loads(cfg.id_map.read_text(encoding="utf8"))
    m["map"]["salt"] = "salt"
    cfg.id_map.write_text(json.dumps(m), encoding="utf8")
    _commit(cfg.root)
    assert fresh.run(cfg) == 0
    c = load_result(cfg.out)["config"]
    assert "mention_accuracy_random" in c["failed"]


def test_dirty_tree_refused(cfg, capsys):
    (cfg.root / "stray.py").write_text("x = 1\n", encoding="utf8")
    assert fresh.run(cfg) == 1
    assert not cfg.out.exists()
    assert "stray.py" in capsys.readouterr().out


def test_existing_result_refused(cfg):
    assert fresh.run(cfg) == 0
    first = cfg.out.read_bytes()
    assert fresh.run(cfg) == 1
    assert cfg.out.read_bytes() == first


def test_unchecked_map_refused(cfg):
    m = json.loads(cfg.id_map.read_text(encoding="utf8"))
    m["owner_checked"] = False
    cfg.id_map.write_text(json.dumps(m), encoding="utf8")
    _commit(cfg.root)
    assert fresh.run(cfg) == 1
    assert not cfg.out.exists()


def test_map_missing_a_name_refused(cfg, capsys):
    m = json.loads(cfg.id_map.read_text(encoding="utf8"))
    del m["map"]["flour"]
    cfg.id_map.write_text(json.dumps(m), encoding="utf8")
    _commit(cfg.root)
    assert fresh.run(cfg) == 1
    assert not cfg.out.exists()
    assert "flour" not in capsys.readouterr().out  # counts only, no gold names


def test_wrong_line_count_refused(cfg):
    assert fresh.run(fresh.Config(**{**cfg.__dict__, "expected_lines": 200})) == 1
    assert not cfg.out.exists()


def test_non_random_stratum_refused(cfg):
    doc = json.loads(cfg.fresh.read_text(encoding="utf8"))
    doc["lines"][0]["stratum"] = "hard"
    cfg.fresh.write_text(json.dumps(doc), encoding="utf8")
    _commit(cfg.root)
    assert fresh.run(cfg) == 1


def test_missing_label_refused(cfg):
    labels = json.loads(cfg.labels.read_text(encoding="utf8"))
    del labels["labels"]["f-2"]
    cfg.labels.write_text(json.dumps(labels), encoding="utf8")
    _commit(cfg.root)
    assert fresh.run(cfg) == 1


def test_stale_pack_hash_refused(cfg):
    cfg.table.write_text(TABLE + "kale,kale,,0,hand,,\n", encoding="utf8")
    _commit(cfg.root)
    assert fresh.run(cfg) == 1
    assert not cfg.out.exists()
