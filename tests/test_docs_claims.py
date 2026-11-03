"""Retracted headline words stay out of the new evaluation text (plan section 10, ADR 0005)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORDS = re.compile(r"flagship|7\.7", re.I)
RETRACTION = re.compile(r"retract|retire|unsupported|stale|false|replaces|no longer", re.I)
NEW_SECTIONS = ("## M2 evaluation baseline", "## M2 leaderboard (Wikibooks pack)")


def test_product_docs_use_the_words_only_to_retract_them() -> None:
    for name in ("README.md", "docs/PROJECT_STATE.md", "docs/DEVELOPMENT_PLAN.md"):
        for n, line in enumerate((ROOT / name).read_text(encoding="utf8").splitlines(), 1):
            if WORDS.search(line):
                assert RETRACTION.search(line), f"{name}:{n} uses a retracted word: {line[:80]}"


def test_evaluation_md_keeps_the_words_in_the_historical_block() -> None:
    text = (ROOT / "docs/EVALUATION.md").read_text(encoding="utf8")
    in_new = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            in_new = line.startswith(NEW_SECTIONS)
        if in_new:
            assert not WORDS.search(line), f"docs/EVALUATION.md:{n} (new section): {line[:80]}"
