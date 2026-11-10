"""M3 fresh-line labelling with tiny invented data. It never reads fresh.v1.json."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from pantrychef.eval.parser_gold import LabelError
from scripts import m3_label_fresh as f

LINES = [
    {"id": "f1", "text": "2 eggs"},
    {"id": "f2", "text": "1 cup flour or butter"},
    {"id": "f3", "text": "salt, to taste"},
    {"id": "f4", "text": "3 kumquats"},
]
A = {"f1": "egg", "f2": "flour|butter", "f3": "salt", "f4": "kumquat"}
B = {"f1": "egg", "f2": "butter|flour", "f3": "salt", "f4": "lime"}  # f4 differs


def _setup(tmp_path: Path) -> f.Sets:
    src = tmp_path / "fresh.json"
    src.write_text(json.dumps({"lines": LINES}), encoding="utf8")
    sets = f.load_fresh(src)
    f.make_sheets(sets, tmp_path)
    for who, answers in (("a", A), ("b", B)):
        with (tmp_path / f"m3_label_{f.NAME}.csv").open(encoding="utf8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            r["names"] = answers[r["id"]]
        with (tmp_path / f"{who}.csv").open("w", encoding="utf8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return sets


def _owner_sheet(tmp_path: Path, sets: f.Sets, n_agreed: int) -> Path:
    n, agree, ids = f.compare(f.NAME, sets, tmp_path / "a.csv", tmp_path / "b.csv", tmp_path)
    assert (n, agree, ids) == (4, 3, ["f4"])
    return f.owner_sheet(sets, tmp_path, n_agreed=n_agreed)


def _fill_owner(path: Path, edits: dict[str, dict[str, str]]) -> None:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r.update(edits.get(r["id"], {}))
    with path.open("w", encoding="utf8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_merge_writes_labels_and_adjudication(tmp_path: Path) -> None:
    sets = _setup(tmp_path)
    sheet = _owner_sheet(tmp_path, sets, n_agreed=2)
    _fill_owner(sheet, {"f4": {"names": "kumquat"}})
    targets = {"labels": tmp_path / "labels.json", "adjudication": tmp_path / "adj.json"}
    f.merge_fresh(sets, sheet, tmp_path, targets, n_agreed=2)
    labels = json.loads(targets["labels"].read_text(encoding="utf8"))["labels"]
    assert set(labels) == {"f1", "f2", "f3", "f4"}
    assert labels["f4"]["groups"] == [["kumquat"]]
    adj = json.loads(targets["adjudication"].read_text(encoding="utf8"))
    assert adj["agreed_check"]["n"] == 2
    assert [r["id"] for r in adj["set"]["disagreements"]] == ["f4"]
    with pytest.raises(SystemExit):  # label files are never overwritten
        f.merge_fresh(sets, sheet, tmp_path, targets, n_agreed=2)


def test_merge_refuses_a_blank_owner_answer(tmp_path: Path) -> None:
    sets = _setup(tmp_path)
    sheet = _owner_sheet(tmp_path, sets, n_agreed=2)
    targets = {"labels": tmp_path / "l.json", "adjudication": tmp_path / "a.json"}
    with pytest.raises(LabelError):
        f.merge_fresh(sets, sheet, tmp_path, targets, n_agreed=2)


def test_merge_stops_when_agreed_lines_are_wrong(tmp_path: Path) -> None:
    sets = _setup(tmp_path)
    sheet = _owner_sheet(tmp_path, sets, n_agreed=3)
    with sheet.open(encoding="utf-8-sig", newline="") as fh:
        agreed = [r["id"] for r in csv.DictReader(fh) if r["kind"] == "agreed"]
    edits = {i: {"names": "x", "error": "1"} for i in agreed}
    edits["f4"] = {"names": "kumquat"}
    _fill_owner(sheet, edits)
    targets = {"labels": tmp_path / "l.json", "adjudication": tmp_path / "a.json"}
    with pytest.raises(SystemExit):
        f.merge_fresh(sets, sheet, tmp_path, targets, n_agreed=3, max_agreed_errors=2)
    assert not targets["labels"].exists()
