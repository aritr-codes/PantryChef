"""Gates of the pack v2 result (M3 Task 7). The gate values are fixed by the plan."""

from __future__ import annotations

from scripts.m3_pack_result import GATES, failed_gates


def test_gate_values_are_the_plan_values():
    assert GATES == {
        "min_recipes": 2500,
        "min_recipes_fully_read": 0.60,
        "max_core_bytes": 3_145_728,
    }


def test_passing_numbers_pass_and_each_failure_is_named():
    assert failed_gates(2500, 0.60, 3_145_728) == []
    assert len(failed_gates(2499, 0.60, 1)) == 1
    assert len(failed_gates(3000, 0.5999, 1)) == 1
    assert len(failed_gates(3000, 0.9, 3_145_729)) == 1
    assert len(failed_gates(0, 0.0, 10**9)) == 3


def test_a_failed_gate_exits_1_and_writes_no_file(tmp_path, monkeypatch, capsys):
    """Build a tiny pack from the fixture pages. Make the recipe gate impossible."""
    import json

    import scripts.m3_pack_result as mod
    from pantrychef.pack.build import build_pack
    from tests.test_pack import PAGES, ROOT, _allowlist, _snapshot

    snap = tmp_path / "snap.jsonl.gz"
    _snapshot(snap, json.loads(PAGES.read_text(encoding="utf8")))
    al = _allowlist(tmp_path, snap)
    commit = mod.git_facts(mod.ROOT)[0]
    build_pack(al, tmp_path / "pack", repo_root=ROOT, commit=commit, dirty=False)
    monkeypatch.setattr(mod, "ALLOWLIST", al)
    monkeypatch.setattr(mod, "GATES", {**GATES, "min_recipes": 10**6})
    monkeypatch.setattr(mod, "RESULT", tmp_path / "m3_pack_v2.json")
    assert mod.main(["--pack", str(tmp_path / "pack")]) == 1
    assert "GATE FAILED" in capsys.readouterr().out
    assert not (tmp_path / "m3_pack_v2.json").exists()
