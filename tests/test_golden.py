"""The committed golden file must match what the reference engine writes now."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "answer_cases.json"


def _make_golden():
    spec = importlib.util.spec_from_file_location(
        "make_golden", ROOT / "scripts" / "make_golden.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_golden_file_is_current():
    expected = _make_golden().render()
    assert GOLDEN.read_bytes().decode("utf8") == expected, (
        "tests/golden/answer_cases.json is stale. Run `uv run python scripts/make_golden.py` "
        "and commit it, in the same change as the engine change."
    )


def test_golden_covers_enough_cases_and_every_group():
    data = json.loads(GOLDEN.read_text(encoding="utf8"))
    assert len(data["cases"]) >= 200
    seen = dict.fromkeys(("make_now", "one_away", "two_away"), 0)
    blockers = unlocks = 0
    for c in data["cases"]:
        for k, g in c["answer"]["groups"].items():
            seen[k] += g["count"] > 0
        blockers += bool(c["answer"]["blockers"])
        unlocks += bool(c["answer"]["unlocks"])
    assert all(v >= 10 for v in seen.values()), seen
    assert blockers >= 1 and unlocks >= 10
