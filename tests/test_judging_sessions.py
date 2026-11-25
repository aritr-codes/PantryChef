"""Sessions: --answered skips done items, and judging_merge joins session CSVs."""

import csv
import json
import re

import pytest

from scripts.judging_merge import COLUMNS, MergeError, answered_ids, merge
from scripts.judging_merge import main as merge_main
from scripts.judging_page import build_page
from scripts.judging_page import main as page_main
from scripts.judging_sheet import TEMPLATE_COLUMNS


def _sheet(n):
    lst = [{"title": f"T{i}", "missing": []} for i in range(5)]
    return {
        "version": 1,
        "items": [
            {"item_id": f"item{k:02d}", "pantry": ["egg"], "left": lst, "right": lst}
            for k in range(1, n + 1)
        ],
    }


def _ids(html):
    m = re.search(r'<script type="application/json" id="sheet">(.*?)</script>', html, re.S)
    return [i["item_id"] for i in json.loads(m.group(1))["items"]]


def _rows(ids, session, guess=False):
    out = []
    for i in ids:
        r = {
            "item_id": i, "choice": "A", "strength": "1", "would_cook_left": "yes",
            "would_cook_right": "no", "seconds": "30", "session": str(session),
        }  # fmt: skip
        if guess:
            r["arm_guess"] = "left"
        out.append(r)
    return out


def _write(path, rows, guess=False):
    cols = TEMPLATE_COLUMNS + (["arm_guess"] if guess else [])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def test_columns_match_template():
    assert COLUMNS == TEMPLATE_COLUMNS


def test_answered_items_are_skipped():
    html = build_page(_sheet(6), 2, "dev", answered={"item01", "item02"})
    assert _ids(html) == ["item03", "item04", "item05", "item06"]


def test_answered_ids_only_complete_rows(tmp_path):
    rows = _rows(["item01", "item02"], 1)
    rows[1]["would_cook_right"] = ""
    rows.append({"item_id": "item03", **dict.fromkeys(TEMPLATE_COLUMNS[1:], "")})
    p = tmp_path / "a.csv"
    _write(p, rows)
    assert answered_ids([p], arm_guess=False) == {"item01"}


def test_three_session_round_trip(tmp_path):
    sp = tmp_path / "sheet.dev.v1.json"
    sp.write_text(json.dumps(_sheet(7)), encoding="utf-8")
    done = []
    plan = [(1, ["item01", "item02", "item03"]), (2, ["item04", "item05"]), (3, ["item06"])]
    for sess, ids in plan:
        out = tmp_path / f"p{sess}.html"
        args = ["--sheet", str(sp), "--session", str(sess), "--out", str(out)]
        for a in done:
            args += ["--answered", str(a)]
        assert page_main(args) == 0
        shown = _ids(out.read_text(encoding="utf-8"))
        assert shown[: len(ids)] == ids  # starts at the first item not answered
        assert not set(shown) & {i for s, g in plan[: sess - 1] for i in g}
        p = tmp_path / f"answers.dev.session{sess}.csv"
        _write(p, _rows(ids, sess))  # what the page exports: this session's items only
        done.append(p)
    final = tmp_path / "answers.dev.v1.csv"
    assert merge(sp, done, final) == 1  # item07 is not answered
    text = final.read_text(encoding="utf-8")
    got = list(csv.DictReader(text.splitlines()))
    assert [r["item_id"] for r in got] == [f"item0{k}" for k in range(1, 7)]
    assert [r["session"] for r in got] == ["1", "1", "1", "2", "2", "3"]
    assert text.splitlines()[0] == ",".join(TEMPLATE_COLUMNS)


def test_page_refuses_when_all_answered(tmp_path):
    sp = tmp_path / "sheet.dev.v1.json"
    sp.write_text(json.dumps(_sheet(2)), encoding="utf-8")
    p = tmp_path / "a.csv"
    _write(p, _rows(["item01", "item02"], 1))
    with pytest.raises(SystemExit):
        page_main(["--sheet", str(sp), "--session", "2", "--answered", str(p)])


def _merge_with(tmp_path, *files, guess=False):
    sp = tmp_path / "sheet.dev.v1.json"
    sp.write_text(json.dumps(_sheet(3)), encoding="utf-8")
    paths = []
    for k, rows in enumerate(files):
        p = tmp_path / f"s{k}.csv"
        _write(p, rows, guess)
        paths.append(p)
    return merge(sp, paths, tmp_path / "o.csv", arm_guess=guess)


def test_merge_refuses_bad_input(tmp_path):
    with pytest.raises(MergeError, match="item01"):
        _merge_with(tmp_path, _rows(["item01"], 1), _rows(["item01"], 2))
    with pytest.raises(MergeError, match="item99"):
        _merge_with(tmp_path, _rows(["item99"], 1))
    bad = _rows(["item01"], 1)
    bad[0]["would_cook_left"] = ""
    with pytest.raises(MergeError, match="item01.*would_cook_left"):
        _merge_with(tmp_path, bad)
    bad = _rows(["item01"], 1)
    bad[0]["strength"] = ""
    with pytest.raises(MergeError, match="strength"):
        _merge_with(tmp_path, bad)
    tie = _rows(["item01"], 1)
    tie[0].update(choice="tie", strength="1")
    with pytest.raises(MergeError, match="strength"):
        _merge_with(tmp_path, tie)
    r = _rows(["item01"], 1, guess=True)
    r[0]["arm_guess"] = ""
    with pytest.raises(MergeError, match="arm_guess"):
        _merge_with(tmp_path, r, guess=True)


def test_merge_accepts_tie_and_blank_rows_and_prints_no_answers(tmp_path, capsys):
    rows = _rows(["item01", "item02", "item03"], 1)
    rows[0].update(choice="tie", strength="")
    rows[2] = {"item_id": "item03", **dict.fromkeys(TEMPLATE_COLUMNS[1:], "")}
    assert _merge_with(tmp_path, rows) == 1
    merge_main(
        [
            "--sheet", str(tmp_path / "sheet.dev.v1.json"),
            "--out", str(tmp_path / "o2.csv"), str(tmp_path / "s0.csv"),
        ]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert out == f"merged into {tmp_path / 'o2.csv'}; 1 items still unanswered" + chr(10)
