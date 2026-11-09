"""M3 label-set tool with tiny invented data. It never reads the held-out files."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from pantrychef.eval.parser_gold import LabelError
from scripts import m3_label_sets as m

SETS = {
    "test150": [("t1", "2 eggs"), ("t2", "1 cup flour or butter"), ("t3", "salt, to taste")],
    "extra100": [("e1", "1 tbsp sugar"), ("e2", "3 kumquats")],
    "inputs166": [("in000", "evoo"), ("in001", "scallions")],
}


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_rows(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _fill(work: Path, name: str, who: str, answers: dict[str, tuple[str, ...]]) -> None:
    """Copy a blind sheet and fill ``names`` (and the flag columns when the sheet has them)."""
    rows = _rows(work / f"m3_label_{name}.csv")
    for r in rows:
        names, *flags = answers[r["id"]]
        r["names"] = names
        for col, v in zip(("optional", "not_an_ingredient"), flags, strict=False):
            r[col] = v
    _write_rows(work / f"{who}_{name}.csv", rows)


def test_make_sheets_are_blind(tmp_path: Path) -> None:
    m.make_sheets(SETS, tmp_path)
    rows = _rows(tmp_path / "m3_label_test150.csv")
    assert list(rows[0]) == ["id", "text", "names", "optional", "not_an_ingredient"]
    assert [r["id"] for r in rows] == ["t1", "t2", "t3"]
    assert all(not r["names"] and not r["optional"] for r in rows)
    assert list(_rows(tmp_path / "m3_label_inputs166.csv")[0]) == ["id", "text", "names"]
    with pytest.raises(SystemExit):  # a second run would overwrite filled sheets
        m.make_sheets(SETS, tmp_path)


def _two_labellers(work: Path) -> None:
    m.make_sheets(SETS, work)
    _fill(
        work, "test150", "a",
        {"t1": ("egg", "", ""), "t2": ("flour|butter", "", ""), "t3": ("salt", "1", "")},
    )  # fmt: skip
    _fill(
        work, "test150", "b",
        {"t1": ("egg", "", ""), "t2": ("butter|flour", "", ""), "t3": ("salt", "", "")},
    )  # fmt: skip
    _fill(work, "extra100", "a", {"e1": ("sugar", "", ""), "e2": ("kumquat", "", "")})
    _fill(work, "extra100", "b", {"e1": ("sugar", "", ""), "e2": ("lime", "", "")})
    _fill(work, "inputs166", "a", {"in000": ("olive oil",), "in001": ("spring onion",)})
    _fill(work, "inputs166", "b", {"in000": ("olive oil",), "in001": ("green onion",)})


def test_compare_ignores_order_and_flags_real_differences(tmp_path: Path, capsys) -> None:
    _two_labellers(tmp_path)
    capsys.readouterr()
    got = m.compare(
        "test150", SETS, tmp_path / "a_test150.csv", tmp_path / "b_test150.csv", tmp_path
    )
    # t2 differs only by alternative order, so it agrees. t3 differs by the optional flag.
    assert got == (3, 2, ["t3"])
    out = json.loads((tmp_path / "m3_disagreements_test150.json").read_text(encoding="utf8"))
    assert out["ids"] == ["t3"]
    assert capsys.readouterr().out == ""  # the function itself prints nothing


def test_compare_accepts_json_labels(tmp_path: Path) -> None:
    _two_labellers(tmp_path)
    plain = {"optional": False, "not_an_ingredient": False}
    old = {
        "t1": {"groups": [["egg"]], **plain},
        "t2": {"groups": [["flour", "butter"]], **plain},
        "t3": {"groups": [["salt"]], "optional": True, "not_an_ingredient": False},
    }
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"labels": old}), encoding="utf8")
    assert m.compare("test150", SETS, tmp_path / "a_test150.csv", p, tmp_path)[1] == 3


def _run_to_owner_sheet(work: Path) -> Path:
    _two_labellers(work)
    for name in SETS:
        m.compare(name, SETS, work / f"a_{name}.csv", work / f"b_{name}.csv", work)
    return m.owner_sheet(SETS, work, n_agreed=1)


def test_owner_sheet_has_disagreements_and_seeded_agreed(tmp_path: Path) -> None:
    path = _run_to_owner_sheet(tmp_path)
    rows = _rows(path)
    kinds = sorted(r["kind"] for r in rows)
    assert kinds == ["agreed", "disagree", "disagree", "disagree"]  # t3, e2, in001 + 1 agreed
    dis = next(r for r in rows if r["id"] == "e2")
    assert dis["text"] == "3 kumquats"
    assert "kumquat" in dis["label_a"] and "lime" in dis["label_b"]
    agreed = next(r for r in rows if r["kind"] == "agreed")
    assert agreed["label_b"] == "" and agreed["set"] in ("test150", "extra100")
    again = m.owner_sheet(SETS, tmp_path, n_agreed=1)  # the seed fixes the sample
    assert sorted(r["id"] for r in _rows(again)) == sorted(r["id"] for r in rows)


def _targets(tmp_path: Path) -> dict[str, Path]:
    gold = tmp_path / "gold"
    gold.mkdir(exist_ok=True)
    return {
        "test": gold / "labels.test.v2.json",
        "extra": gold / "labels.extra.v1.json",
        "adjudication": gold / "adjudication.m3.v1.json",
        "inputs": tmp_path / "realistic_inputs.labels.v1.json",
    }


def _answer(path: Path, final: dict[str, tuple[str, str, str, str]]) -> str:
    """Fill the owner sheet. Return the id of the agreed line."""
    rows = _rows(path)
    for r in rows:
        if r["id"] in final:
            r["names"], r["optional"], r["not_an_ingredient"], r["error"] = final[r["id"]]
    _write_rows(path, rows)
    return next(r["id"] for r in rows if r["kind"] == "agreed")


def _final(agreed_id: str, agreed_error: str) -> dict[str, tuple[str, str, str, str]]:
    return {
        "t3": ("salt", "1", "", ""),
        "e2": ("kumquat", "", "", ""),
        "in001": ("scallion|green onion", "", "", ""),
        agreed_id: ("wrong thing" if agreed_error == "1" else "", "", "", agreed_error),
    }


def test_merge_writes_new_files_and_refuses_overwrite(tmp_path: Path) -> None:
    path = _run_to_owner_sheet(tmp_path)
    agreed_id = next(r["id"] for r in _rows(path) if r["kind"] == "agreed")
    _answer(path, _final(agreed_id, "0"))
    t = _targets(tmp_path)
    m.merge(SETS, path, tmp_path, t, n_agreed=1)
    test = json.loads(t["test"].read_text(encoding="utf8"))
    assert test["labels"]["t3"] == {
        "groups": [["salt"]],
        "optional": True,
        "not_an_ingredient": False,
    }
    assert test["labels"]["t2"]["groups"] == [["flour", "butter"]]  # agreed: labeller A
    assert set(json.loads(t["extra"].read_text(encoding="utf8"))["labels"]) == {"e1", "e2"}
    inputs = json.loads(t["inputs"].read_text(encoding="utf8"))["labels"]
    assert inputs["scallions"]["groups"] == [["scallion", "green onion"]]  # keyed by input text
    adj = json.loads(t["adjudication"].read_text(encoding="utf8"))
    assert adj["agreed_check"]["n"] == 1 and adj["agreed_check"]["errors"] == 0
    rec = adj["sets"]["extra100"]["disagreements"][0]
    assert {"id", "text", "a", "b", "final"} <= set(rec)
    with pytest.raises(SystemExit):  # never overwrite
        m.merge(SETS, path, tmp_path, t, n_agreed=1)


def test_merge_stops_on_too_many_agreed_errors(tmp_path: Path) -> None:
    path = _run_to_owner_sheet(tmp_path)
    agreed_id = next(r["id"] for r in _rows(path) if r["kind"] == "agreed")
    _answer(path, _final(agreed_id, "1"))
    t = _targets(tmp_path)
    with pytest.raises(SystemExit, match="stop"):
        m.merge(SETS, path, tmp_path, t, n_agreed=1, max_agreed_errors=0)
    assert not any(p.exists() for p in t.values())
    m.merge(
        SETS, path, tmp_path, t, n_agreed=1, max_agreed_errors=1
    )  # one error is within this limit
    assert all(p.exists() for p in t.values())


def test_merge_needs_every_disagreement_answered(tmp_path: Path) -> None:
    path = _run_to_owner_sheet(tmp_path)
    t = _targets(tmp_path)
    with pytest.raises(LabelError):
        m.merge(SETS, path, tmp_path, t, n_agreed=1)
    assert not any(p.exists() for p in t.values())


def _filled_sheet(tmp_path: Path, agreed_error: str = "0") -> tuple[Path, str]:
    path = _run_to_owner_sheet(tmp_path)
    agreed_id = _answer(path, _final(next_agreed(path), agreed_error))
    return path, agreed_id


def next_agreed(path: Path) -> str:
    return next(r["id"] for r in _rows(path) if r["kind"] == "agreed")


def test_merge_rejects_names_on_an_agreed_row_without_error_flag(tmp_path: Path) -> None:
    path, agreed_id = _filled_sheet(tmp_path)
    rows = _rows(path)
    for r in rows:
        if r["id"] == agreed_id:
            r["names"] = "something"  # error stays 0: the owner forgot the flag
    _write_rows(path, rows)
    t = _targets(tmp_path)
    with pytest.raises(LabelError):
        m.merge(SETS, path, tmp_path, t, n_agreed=1)
    assert not any(p.exists() for p in t.values())


def test_merge_needs_exactly_n_agreed_rows(tmp_path: Path) -> None:
    path, _ = _filled_sheet(tmp_path)
    t = _targets(tmp_path)
    with pytest.raises(LabelError, match="agreed"):
        m.merge(SETS, path, tmp_path, t, n_agreed=2)
    rows = [r for r in _rows(path) if r["kind"] != "agreed"]  # the owner deleted the agreed row
    _write_rows(path, rows)
    with pytest.raises(LabelError, match="agreed"):
        m.merge(SETS, path, tmp_path, t, n_agreed=1)
    assert not any(p.exists() for p in t.values())


def test_merge_rejects_duplicate_rows(tmp_path: Path) -> None:
    path, _ = _filled_sheet(tmp_path)
    rows = _rows(path)
    _write_rows(path, [*rows, rows[0]])
    with pytest.raises(LabelError, match="duplicate"):
        m.merge(SETS, path, tmp_path, _targets(tmp_path), n_agreed=1)


def test_disagreement_file_records_absolute_paths_and_hashes(tmp_path: Path) -> None:
    import hashlib

    _two_labellers(tmp_path)
    m.compare("test150", SETS, tmp_path / "a_test150.csv", tmp_path / "b_test150.csv", tmp_path)
    d = json.loads((tmp_path / "m3_disagreements_test150.json").read_text(encoding="utf8"))
    for side, name in (("a", "a_test150.csv"), ("b", "b_test150.csv")):
        assert Path(d[side]["path"]).is_absolute()
        want = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        assert d[side]["sha256"] == want


def test_owner_sheet_refuses_a_changed_labeller_file(tmp_path: Path) -> None:
    _two_labellers(tmp_path)
    for name in SETS:
        m.compare(name, SETS, tmp_path / f"a_{name}.csv", tmp_path / f"b_{name}.csv", tmp_path)
    a = tmp_path / "a_extra100.csv"
    a.write_text(a.read_text(encoding="utf8") + " ", encoding="utf8")
    with pytest.raises(LabelError, match="changed"):
        m.owner_sheet(SETS, tmp_path, n_agreed=1)


def test_merge_refuses_a_changed_labeller_file(tmp_path: Path) -> None:
    path, _ = _filled_sheet(tmp_path)
    b = tmp_path / "b_inputs166.csv"
    b.write_text(b.read_text(encoding="utf8") + " ", encoding="utf8")
    t = _targets(tmp_path)
    with pytest.raises(LabelError, match="changed"):
        m.merge(SETS, path, tmp_path, t, n_agreed=1)
    assert not any(p.exists() for p in t.values())
