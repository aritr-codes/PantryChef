"""Pinned ordering of the shipped rule (M4, plan 11.2). A change to the order fails here.

``tests/golden/rank_pinned.json`` holds the first 5 recipe ids of the shipped order for 5 fixture
pantries (run in CI) and for 5 real-pack pantries (run locally, skipped when ``build/pack`` is
absent). A person re-pins the file, in the same change as the order change.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from pantrychef.engine import AnswerRequest, Pack, answer, load_pack

ROOT = Path(__file__).resolve().parents[1]
PINNED = json.loads((ROOT / "tests/golden/rank_pinned.json").read_text(encoding="utf-8"))
REAL_CORE = (
    Path(os.environ.get("PANTRYCHEF_REAL_PACK") or ROOT / "build" / "pack") / "core.v2.json.gz"
)
GROUPS = ("make_now", "one_away", "two_away")


def ranked(pack: Pack, pantry: list[str]):
    """The shipped order: the three groups in turn, each already sorted by the engine."""
    req = AnswerRequest(pantry=pantry, staples=sorted(pack.default_staples), limit=1000)
    got = answer(pack, req)
    return [(g, r) for g in GROUPS for r in got.groups[g].items]


def check_order_rule(rows) -> None:
    """The rule itself, not the ids: missing lines first, then score, total and id."""
    keys = [(len(r.missing), -r.score, r.total, r.recipe_id) for _, r in rows]
    assert keys == sorted(keys)
    assert [g for g, _ in rows] == sorted((g for g, _ in rows), key=GROUPS.index)


@pytest.mark.parametrize("case", PINNED["fixture"]["pantries"], ids=lambda c: c["name"][:40])
def test_fixture_pantry_keeps_its_pinned_top5(case):
    pack = load_pack(ROOT / "tests" / "fixtures" / "pack")
    rows = ranked(pack, case["pantry"])
    check_order_rule(rows)
    assert [r.recipe_id for _, r in rows][:5] == case["top5"]


def test_fixture_pins_hold_a_tie_that_falls_to_the_id():
    pack = load_pack(ROOT / "tests" / "fixtures" / "pack")
    rows = ranked(pack, PINNED["fixture"]["pantries"][0]["pantry"])
    tied = [r for _, r in rows if r.recipe_id in ("fx-036", "fx-037")]
    assert len(tied) == 2 and tied[0].score == tied[1].score and tied[0].total == tied[1].total
    assert [r.recipe_id for r in tied] == ["fx-036", "fx-037"]


def test_pinned_file_has_five_fixture_pantries():
    assert len(PINNED["fixture"]["pantries"]) == 5


@pytest.mark.skipif(not REAL_CORE.exists(), reason="build/pack is absent (git ignores the pack)")
@pytest.mark.parametrize(
    "case", PINNED["real_pack"]["pantries"], ids=lambda c: ",".join(c["names"])
)
def test_real_pack_pantry_keeps_its_pinned_top5(case):
    sha = hashlib.sha256(REAL_CORE.read_bytes()).hexdigest()
    assert sha == PINNED["real_pack"]["core_sha256"], "the pack changed: re-pin on purpose"
    rows = ranked(load_pack(REAL_CORE.parent), case["pantry"])
    check_order_rule(rows)
    assert [r.recipe_id for _, r in rows][:5] == case["top5"]
