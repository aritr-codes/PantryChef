"""The graph spike entry point, end to end on an invented repository (M3 Task 8).

A tiny git repository holds the real ingredient table and words (data), six invented
pages and a few invented pantries. Nothing here reads the real pantries or the real corpus.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import shutil
import subprocess

import pytest

from pantrychef.eval import graph_spike as gs
from pantrychef.eval.results import load_result
from pantrychef.ingredients.table import DEFAULT_WORDS_PATH, TABLE_V2_PATH
from scripts import graph_spike as cli

GRAPH = "data/eval/graph_spike"


def page(i, title, lines):
    body = "\n".join(f"*{x}" for x in lines)
    return {
        "page_id": 1000 + i,
        "title": f"Cookbook:{title}",
        "revision_id": 5000 + i,
        "timestamp": "2025-01-01T00:00:00Z",
        "wikitext": f"==Ingredients==\n{body}\n\n==Procedure==\n#Mix.\n",
    }


PAGES = [
    page(1, "Cheese toast", ["2 slices bread", "100 g cheese"]),
    page(2, "Cheesy onions", ["1 onion", "100 g cheese"]),
    page(3, "Garlic soup", ["3 cloves garlic", "1 onion"]),
    page(4, "Garlic toast", ["2 slices bread", "1 tsp garlic"]),
    *[page(10 + i, f"Onion soup {i}", ["1 onion", "1 cup water"]) for i in range(6)],
    *[page(20 + i, f"Onion jam {i}", ["1 onion", "1 cup sugar"]) for i in range(6)],
]
PANTRIES = {
    "version": 1,
    "split": "dev",
    "never_in": "M4 test split",
    "writer": {"model": "Sonnet", "date": "2026-11-09", "prompt": "p", "profiles": ["a", "b"]},
    "pantries": [
        {"id": "pilot01", "source": "m2_pilot:item01", "source_recipe_id": "r1",
         "names": ["paneer", "onion", "bread"]},
        {"id": "pilot02", "source": "m2_pilot:item02", "source_recipe_id": "r2",
         "names": ["paneer", "onion", "zzz unknown"]},
        {"id": "new01", "source": "spike_writer", "profile": "a",
         "names": ["garlic paste", "onion", "bread"]},
        {"id": "new02", "source": "spike_writer", "profile": "b",
         "names": ["garlic paste", "onion"]},
    ],
}  # fmt: skip


def git(root, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    root = tmp_path
    git(root, "init", "-q")
    (root / "data" / "ingredients").mkdir(parents=True)
    (root / "data" / "raw").mkdir()
    (root / "pantrychef" / "pack").mkdir(parents=True)
    (root / GRAPH).mkdir(parents=True)
    shutil.copy(TABLE_V2_PATH, root / "data" / "ingredients" / "ingredients.v2.csv")
    shutil.copy(DEFAULT_WORDS_PATH, root / "data" / "ingredients" / "words.v1.json")
    raw = "".join(json.dumps(r) + "\n" for r in PAGES).encode()
    (root / "data" / "raw" / "snap.jsonl.gz").write_bytes(gzip.compress(raw, mtime=0))
    (root / "pantrychef" / "pack" / "allowlist.json").write_text(
        json.dumps({"inputs": {"snapshot": {"path": "data/raw/snap.jsonl.gz",
                                            "retrieved_on": "2026-11-03"}}})
    )  # fmt: skip
    (root / GRAPH / "pantries.v1.json").write_text(json.dumps(PANTRIES))
    (root / ".gitignore").write_text("data/interim/\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "base")
    return root


def run(root, *args):
    return cli.main(["--root", str(root), *args])


def test_pantries_command_reports_unknown_names(repo, capsys):
    assert run(repo, "pantries") == 0
    out = capsys.readouterr().out
    assert "4 pantries, 2 pilot, 2 new" in out
    assert "pilot02: zzz unknown" in out


def test_pantries_command_flags_a_non_dev_file(repo):
    doc = {**PANTRIES, "split": "test"}
    (repo / GRAPH / "pantries.v1.json").write_text(json.dumps(doc))
    assert run(repo, "pantries") == 1


def test_freeze_sheet_score_end_to_end(repo, capsys):
    assert run(repo, "freeze", "--option", "a") == 0
    out = capsys.readouterr().out
    assert "make_now|is_a: 3" in out and "one_away|is_a: 1" in out
    assert "PRE-CHECK: a group has fewer than 20" in out
    assert "is_a: 4 new items from 2 pantries" in out
    assert "PRE-CHECK: T1 cannot pass for is_a" in out
    assert "PRE-CHECK: T1 cannot pass for form_of" in out
    fz = json.loads((repo / GRAPH / "freeze.v1.json").read_text())
    assert fz["pool_counts"]["new"] == {
        "make_now|form_of": 3, "make_now|is_a": 3, "one_away|form_of": 1, "one_away|is_a": 1,
    }  # fmt: skip
    assert fz["pool_counts"]["edge_types"] == {
        "is_a": {"new": 4, "pantries": 2},
        "form_of": {"new": 4, "pantries": 2},
    }
    assert fz["pool_by_edge"] == [["garlic_paste", "form_of", "garlic", 4],
                                  ["paneer", "is_a", "cheese", 4]]  # fmt: skip
    assert fz["unknown_names"] == {"pilot02": ["zzz unknown"]}
    assert fz["edge_source_hits"]["pilot"] >= 2 and fz["max_depth_observed"] == 1
    assert gs.check_freeze(repo / GRAPH / "freeze.v1.json", repo) == []
    git(repo, "add", GRAPH)
    git(repo, "commit", "-q", "-m", "freeze")

    assert run(repo, "sheet") == 0
    sheet = repo / "data" / "interim" / "graph_spike_sheet.v1.csv"
    with open(sheet, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0]) == list(gs.SHEET_COLUMNS)
    assert len(rows) == 8 + 8 + 10  # new items, decoys, repeats
    key = json.loads((repo / "data" / "interim" / "graph_spike_key.v1.json").read_text())
    digest = (repo / GRAPH / "key_sha256.txt").read_text().strip()
    key_file = repo / "data" / "interim" / "graph_spike_key.v1.json"
    assert hashlib.sha256(key_file.read_bytes()).hexdigest() == digest
    for r in rows:
        assert not any(w in " ".join(r.values()).lower() for w in ("is_a", "form_of", "pilot0"))
    assert run(repo, "sheet") == 0  # same inputs give the same key
    git(repo, "add", GRAPH + "/key_sha256.txt")
    git(repo, "commit", "-q", "-m", "key hash")

    with open(repo / GRAPH / "answers.v1.csv", "w", encoding="utf-8", newline="") as fh:
        fh.write("# I have not read the is_a and form_of columns or the edge labels.\n")
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["item_id", "answer", "unmet_lines", "seconds", "note"])
        for iid in key["items"]:
            w.writerow([iid, "yes", "", "30", ""])
    git(repo, "add", GRAPH + "/answers.v1.csv")
    git(repo, "commit", "-q", "-m", "answers")

    assert run(repo, "score") == 0
    res = load_result(repo / "results" / "m3_graph_spike.json")
    raw = res["raw"]
    assert raw["rater"] == {"count": 1, "read_edges": "no", "median_seconds": 30.0}
    assert raw["verdict"] in ("accepted", "rejected", "exploration")
    assert raw["freeze_sha256"] == gs.sha256_lf(repo / GRAPH / "freeze.v1.json")
    assert raw["pantries"] == {"n": 4, "pilot": 2, "new": 2,
                               "unknown_names": {"pilot02": ["zzz unknown"]}}  # fmt: skip
    assert raw["rated"] == {
        "new": 8,
        "decoys": 8,
        "repeats": 10,
        "strata_mode": raw["rated"]["strata_mode"],
    }
    assert set(raw["rated"]["strata_mode"].values()) == {"census"}
    names = {m["name"] for m in res["metrics"]}
    assert {"graph_net_new_per_pantry", "graph_new_precision_make_now"} <= names
    assert res["seed"] == 46 and {a["name"] for a in res["arms"]} == {
        "table_flat",
        "graph_traversal",
    }


def test_freeze_refuses_to_overwrite_and_leaves_no_half_freeze(repo):
    (repo / GRAPH / "pantries.v1.json").unlink()
    with pytest.raises(SystemExit):
        run(repo, "freeze", "--option", "a")
    assert not (repo / GRAPH / "table.frozen.csv").exists()
    (repo / GRAPH / "pantries.v1.json").write_text(json.dumps(PANTRIES))
    assert run(repo, "freeze", "--option", "a") == 0
    with pytest.raises(SystemExit, match="exists"):
        run(repo, "freeze", "--option", "a")


def test_freeze_option_b_needs_the_labels(repo):
    with pytest.raises(SystemExit, match="option b needs"):
        run(repo, "freeze", "--option", "b")
    assert not (repo / GRAPH / "table.frozen.csv").exists()


def _frozen(repo):
    assert run(repo, "freeze", "--option", "a") == 0
    git(repo, "add", GRAPH)
    git(repo, "commit", "-q", "-m", "freeze")


def test_sheet_and_score_stop_when_a_frozen_input_changes(repo):
    _frozen(repo)
    table = repo / GRAPH / "table.frozen.csv"
    table.write_bytes(table.read_bytes() + b"\n")
    with pytest.raises(SystemExit, match="table_sha256"):
        run(repo, "sheet")
    with pytest.raises(SystemExit, match="table_sha256"):
        run(repo, "score")


def test_sheet_refuses_a_different_key(repo):
    _frozen(repo)
    (repo / GRAPH / "key_sha256.txt").write_text("0" * 64 + "\n")
    with pytest.raises(SystemExit, match="key must not change"):
        run(repo, "sheet")


def _answered(repo, line="# I have read the is_a and form_of columns.", commit_key=True):
    """Make the sheet, commit the key hash, and write (not commit) the answers file."""
    assert run(repo, "sheet") == 0
    if commit_key:
        git(repo, "add", GRAPH + "/key_sha256.txt")
        git(repo, "commit", "-q", "-m", "key hash")
    key = json.loads((repo / "data" / "interim" / "graph_spike_key.v1.json").read_text())
    with open(repo / GRAPH / "answers.v1.csv", "w", encoding="utf-8", newline="") as fh:
        if line:
            fh.write(line + "\n")
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["item_id", "answer", "unmet_lines", "seconds", "note"])
        for iid in key["items"]:
            w.writerow([iid, "no", "1", "", ""])


def _commit_answers(repo):
    git(repo, "add", GRAPH + "/answers.v1.csv")
    git(repo, "commit", "-q", "-m", "answers")


def _ready(repo, **kw):
    _frozen(repo)
    _answered(repo, **kw)
    _commit_answers(repo)


def test_sheet_needs_the_freeze_committed_and_clean(repo):
    assert run(repo, "freeze", "--option", "a") == 0
    with pytest.raises(SystemExit, match="not tracked"):
        run(repo, "sheet")  # the freeze is not committed yet
    git(repo, "add", GRAPH)
    git(repo, "commit", "-q", "-m", "freeze")
    fz = repo / GRAPH / "freeze.v1.json"
    fz.write_text(fz.read_text() + "\n")  # still valid JSON, but no longer the committed file
    with pytest.raises(SystemExit, match="differ from their commit"):
        run(repo, "sheet")


def test_an_ignored_frozen_file_is_refused_even_though_git_status_is_silent(repo):
    (repo / ".gitignore").write_text("data/interim/\n*.csv\n")  # a rule that hides the table copy
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore csv")
    assert run(repo, "freeze", "--option", "a") == 0
    git(repo, "add", GRAPH)  # skips the ignored table.frozen.csv without an error
    git(repo, "commit", "-q", "-m", "freeze")
    assert (repo / GRAPH / "table.frozen.csv").exists()
    for call in (("sheet",), ("skip", "--reason", "x")):
        with pytest.raises(SystemExit, match=r"table.frozen.csv is not tracked.*git add -f"):
            run(repo, *call)
    git(repo, "add", "-f", GRAPH + "/table.frozen.csv")
    git(repo, "commit", "-q", "-m", "table copy")
    assert run(repo, "sheet") == 0


def test_an_ignored_answers_file_is_refused_with_the_fix(repo):
    _frozen(repo)
    _answered(repo)
    (repo / ".gitignore").write_text("data/interim/\n*.csv\n")
    with pytest.raises(SystemExit, match="git add -f"):
        run(repo, "score")


def test_an_ignored_key_hash_is_refused_with_the_fix(repo):
    (repo / ".gitignore").write_text("data/interim/\nkey_sha256.txt\n")
    _frozen(repo)
    _answered(repo, commit_key=False)
    git(repo, "add", "-f", GRAPH + "/answers.v1.csv")
    git(repo, "commit", "-q", "-m", "answers")
    with pytest.raises(SystemExit, match="git add -f"):
        run(repo, "score")


def test_score_needs_answers_committed_after_the_freeze(repo):
    _frozen(repo)
    _answered(repo)
    with pytest.raises(SystemExit, match="not committed"):
        run(repo, "score")
    _commit_answers(repo)
    assert run(repo, "score") == 0
    # a second commit on the freeze file breaks the one-commit rule
    fz = repo / GRAPH / "freeze.v1.json"
    fz.write_text(fz.read_text() + "\n")
    git(repo, "add", GRAPH + "/freeze.v1.json")
    git(repo, "commit", "-q", "-m", "touch freeze")
    with pytest.raises(SystemExit, match="exactly one commit"):
        run(repo, "score")


def test_score_refuses_answers_committed_with_the_key_hash(repo):
    _frozen(repo)
    _answered(repo, commit_key=False)
    git(repo, "add", GRAPH + "/key_sha256.txt", GRAPH + "/answers.v1.csv")
    git(repo, "commit", "-q", "-m", "both")
    with pytest.raises(SystemExit, match="older ancestor"):
        run(repo, "score")


def test_score_refuses_a_key_hash_in_the_freeze_commit(repo):
    _frozen(repo)
    _answered(repo, commit_key=False)
    git(repo, "add", GRAPH + "/key_sha256.txt")
    git(repo, "commit", "-q", "--amend", "--no-edit")  # freeze and key hash share one commit
    _commit_answers(repo)
    with pytest.raises(SystemExit, match="freeze commit and key hash commit"):
        run(repo, "score")


def test_score_needs_the_key_hash_committed(repo):
    _frozen(repo)
    _answered(repo, commit_key=False)
    _commit_answers(repo)
    with pytest.raises(SystemExit, match="Commit the key hash"):
        run(repo, "score")


def test_score_refuses_a_key_hash_edited_after_its_commit(repo):
    _ready(repo)
    sha = repo / GRAPH / "key_sha256.txt"
    committed = sha.read_text()
    sha.write_text("0" * 64 + "\n")  # a wrong hash on disk must not replace the committed one
    with pytest.raises(SystemExit, match="differ from their commit"):
        run(repo, "score")
    sha.write_text(committed)
    assert run(repo, "score") == 0
    git(repo, "commit", "-q", "--allow-empty", "-m", "noop")
    sha.write_text(committed.strip() + "\n\n")
    git(repo, "add", GRAPH + "/key_sha256.txt")
    git(repo, "commit", "-q", "-m", "second key commit")
    with pytest.raises(SystemExit, match="key_sha256.txt must have exactly one commit"):
        run(repo, "score")


def test_score_refuses_a_key_that_does_not_match_the_committed_hash(repo):
    _ready(repo)
    key = repo / "data" / "interim" / "graph_spike_key.v1.json"
    key.write_bytes(key.read_bytes() + b"\n")
    with pytest.raises(SystemExit, match="key differs"):
        run(repo, "score")


def test_score_refuses_answers_edited_after_their_commit(repo):
    _ready(repo)
    ans = repo / GRAPH / "answers.v1.csv"
    ans.write_text(ans.read_text().replace(",no,", ",yes,", 1))
    with pytest.raises(SystemExit, match="differ from their commit"):
        run(repo, "score")
    _commit_answers(repo)  # a second commit on the answers file
    with pytest.raises(SystemExit, match="answers.v1.csv must have exactly one commit"):
        run(repo, "score")


@pytest.mark.parametrize("line", ["", "# I have / have not read the is_a and form_of columns."])
def test_score_needs_the_read_edges_line(repo, line):
    _ready(repo, line=line)
    with pytest.raises(SystemExit, match="I have read"):
        run(repo, "score")


def _result(repo):
    return load_result(repo / "results" / "m3_graph_spike.json")["raw"]


def test_skip_writes_not_run_with_the_reason(repo):
    _frozen(repo)
    with pytest.raises(SystemExit, match="--reason"):
        run(repo, "skip")
    assert run(repo, "skip", "--reason", "pool too small to justify 3 hours") == 0
    raw = _result(repo)
    assert raw["verdict"] == "not_run" and raw["reason"] == "pool too small to justify 3 hours"
    assert raw["pool"]["counts"]["new"]["make_now|is_a"] == 3 and raw["checks"] == {}
    assert load_result(repo / "results" / "m3_graph_spike.json")["metrics"] == []


def test_skip_needs_a_clean_freeze_and_no_sheet(repo):
    assert run(repo, "freeze", "--option", "a") == 0
    with pytest.raises(SystemExit, match="not tracked"):
        run(repo, "skip", "--reason", "x")
    git(repo, "add", GRAPH)
    git(repo, "commit", "-q", "-m", "freeze")
    assert run(repo, "sheet") == 0
    with pytest.raises(SystemExit, match="rating was not skipped"):
        run(repo, "skip", "--reason", "x")


def test_empty_pool_writes_no_sheet(repo, capsys):
    (repo / GRAPH / "pantries.v1.json").write_text(
        json.dumps({**PANTRIES, "pantries": [PANTRIES["pantries"][0] | {"names": ["onion"]}]})
    )
    _frozen(repo)
    capsys.readouterr()
    assert run(repo, "sheet") == 0
    assert "No sheet is written" in capsys.readouterr().out
    assert not (repo / "data" / "interim" / "graph_spike_sheet.v1.csv").exists()
    raw = _result(repo)
    assert raw["verdict"] == "rejected" and raw["reason"].startswith("no_new_recipes")
    assert raw["pool"]["counts"]["new"] == {}
    # skip with an empty pool is also a rejection, whatever the reason says
    assert run(repo, "skip", "--reason", "not needed") == 0
    assert _result(repo)["verdict"] == "rejected"
