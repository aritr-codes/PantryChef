"""The 166 realistic pantry inputs and their dev/test split (M2). Frozen before M3 table work."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ROOT / "data/eval/realistic_inputs.v1.json"
SPLIT = ROOT / "data/eval/realistic_inputs.split.v1.json"


def _script():
    spec = importlib.util.spec_from_file_location(
        "extract_realistic_inputs", ROOT / "scripts/extract_realistic_inputs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_inputs_file_has_166_unique_inputs() -> None:
    doc = json.loads(INPUTS.read_text(encoding="utf8"))
    texts = [r["text"] for r in doc["inputs"]]
    assert doc["n"] == len(texts) == 166
    assert len(set(texts)) == 166


def test_split_is_exact_disjoint_and_complete() -> None:
    texts = [r["text"] for r in json.loads(INPUTS.read_text(encoding="utf8"))["inputs"]]
    split = json.loads(SPLIT.read_text(encoding="utf8"))
    assert set(split["assignment"]) == set(texts)
    counts = Counter(split["assignment"].values())
    assert counts == {"dev": 83, "test": 83}
    assert (split["n_dev"], split["n_test"]) == (83, 83)


def test_split_records_hash_of_inputs_and_matches_the_script() -> None:
    texts = [r["text"] for r in json.loads(INPUTS.read_text(encoding="utf8"))["inputs"]]
    split = json.loads(SPLIT.read_text(encoding="utf8"))
    assert split["inputs_sha256"] == hashlib.sha256("\n".join(texts).encode("utf8")).hexdigest()
    assert split["assignment"] == dict(sorted(_script().split(texts).items()))


def test_every_category_with_two_members_is_in_both_halves() -> None:
    rows = json.loads(INPUTS.read_text(encoding="utf8"))["inputs"]
    assignment = json.loads(SPLIT.read_text(encoding="utf8"))["assignment"]
    halves: dict[str, set[str]] = {}
    sizes: Counter[str] = Counter()
    for r in rows:
        halves.setdefault(r["category"], set()).add(assignment[r["text"]])
        sizes[r["category"]] += 1
    for cat, size in sizes.items():
        if size >= 2:
            assert halves[cat] == {"dev", "test"}, cat


def test_extraction_from_audit_script_matches_committed_file() -> None:
    mod = _script()
    texts = mod.load_inputs()
    committed = [r["text"] for r in json.loads(INPUTS.read_text(encoding="utf8"))["inputs"]]
    assert texts == committed
