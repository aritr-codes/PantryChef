"""M3 frozen sets. These tests read the held-out files but print and assert counts only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pantrychef.eval.parser_gold import line_hash, load_frozen

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "data/eval/parser_gold"
SNAPSHOT = ROOT / "data/raw/wikibooks/snapshot.2026-11-03.jsonl.gz"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf8"))


def _key(text: str) -> str:
    return text.casefold().strip()


def test_extra_lines_are_random_and_disjoint_from_sheet() -> None:
    extra = _read(GOLD / "extra.v1.json")
    sheet = _read(GOLD / "sheet.v1.json")
    texts = [_key(r["text"]) for r in extra["lines"]]
    sheet_texts = {_key(r["text"]) for r in sheet["lines"]}
    assert extra["seed"] == 43
    assert extra["n"] == len(texts) == 100
    assert len(set(texts)) == 100
    shared = len(set(texts) & sheet_texts)  # a count, so a failure never prints a line
    assert shared == 0
    ids = {r["id"] for r in extra["lines"]} & {r["id"] for r in sheet["lines"]}
    assert len(ids) == 0


@pytest.mark.skipif(not SNAPSHOT.exists(), reason="Wikibooks snapshot is not in this checkout")
def test_extra_redraw_equals_committed_file() -> None:
    from scripts.make_m3_extra_lines import draw_extra
    from scripts.make_parser_gold_sheet import collect_lines

    sheet = _read(GOLD / "sheet.v1.json")["lines"]
    again = draw_extra(collect_lines(), sheet)
    same = again == _read(GOLD / "extra.v1.json")["lines"]
    assert same


def test_frozen_lines_cover_test_and_extra() -> None:
    sheet = _read(GOLD / "sheet.v1.json")["lines"]
    extra = _read(GOLD / "extra.v1.json")["lines"]
    want = {line_hash(r["text"]) for r in sheet if r["split"] == "test"}
    assert len(want) == 150
    want |= {line_hash(r["text"]) for r in extra}
    assert len(want) == 250
    frozen = load_frozen()
    assert len(frozen) == 250
    assert frozen == want
    dev = {line_hash(r["text"]) for r in sheet if r["split"] == "dev"}
    assert len(dev & frozen) == 0
