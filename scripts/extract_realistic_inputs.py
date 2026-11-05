"""One-off: extract the 166 realistic pantry inputs and split them into dev and test (M2).

The inputs live inline in the audit script ``docs/research/2026-10-stage1/evidence/b_parser.py``.
That script loads ``data/processed/vocab.json`` when imported, so this script reads it as text and
evaluates only the literal list ``T``. The old acceptance sets use the RecipeNLG vocabulary. They
are NOT carried over. Only the input strings are kept.

Run from the repo root:  uv run python scripts/extract_realistic_inputs.py
Writes data/eval/realistic_inputs.v1.json and data/eval/realistic_inputs.split.v1.json.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs/research/2026-10-stage1/evidence/b_parser.py"
OUT_INPUTS = ROOT / "data/eval/realistic_inputs.v1.json"
OUT_SPLIT = ROOT / "data/eval/realistic_inputs.split.v1.json"
SEED = 42

ABBREVIATION = {"evoo", "s&p", "pb", "oj", "mayo", "tabasco", "sriracha", "worcestershire"}
TYPO = {"tomatos", "tomatoe", "potatos", "brocoli", "zuchini", "parmesean", "tumeric"}
UK_US = {
    "scallions", "aubergine", "courgette", "coriander leaves", "rocket", "capsicum",
    "caster sugar", "plain flour", "self-raising flour", "bicarbonate of soda",
    "double cream", "single cream", "spring onions", "swede", "prawns", "minced beef",
    "cornflour", "beetroot", "chips", "mince", "icing sugar", "yoghurt", "chilli flakes",
    "coriander",
}  # fmt: skip


def load_inputs(source: Path = SOURCE) -> list[str]:
    tree = ast.parse(source.read_text(encoding="utf8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "T" for t in node.targets
        ):
            pairs = ast.literal_eval(node.value)
            return [text for text, _accept in pairs]
    raise ValueError("list T not found")


def category(text: str) -> str:
    low = text.lower()
    if low in TYPO:
        return "typo"
    if low in ABBREVIATION:
        return "abbreviation"
    if low in UK_US:
        return "uk_us_synonym"
    if low[:1].isdigit() or low.startswith("a pinch"):
        return "with_quantity"
    if "/" in low or "&" in low:
        return "slash_or_symbol"
    if len(low.split()) >= 2:
        return "multiword"
    if low.endswith("s"):
        return "plural"
    return "plain"


def split(inputs: list[str], seed: int = SEED) -> dict[str, str]:
    """Return text -> dev|test. Sort by sha256 inside each category, then alternate dev, test."""
    by_cat: dict[str, list[str]] = {}
    for text in inputs:
        by_cat.setdefault(category(text), []).append(text)
    out: dict[str, str] = {}
    flip = 0  # carry the parity across categories so odd categories balance out
    for cat in sorted(by_cat):
        ordered = sorted(
            by_cat[cat], key=lambda t: hashlib.sha256(f"{seed}:{t}".encode()).hexdigest()
        )
        for text in ordered:
            out[text] = "dev" if flip % 2 == 0 else "test"
            flip += 1
    return out


def main() -> None:
    inputs = load_inputs()
    if len(inputs) != len(set(inputs)):
        raise SystemExit("duplicate inputs")
    assignment = split(inputs)
    digest = hashlib.sha256("\n".join(inputs).encode("utf8")).hexdigest()
    rows = [{"text": t, "category": category(t)} for t in inputs]
    OUT_INPUTS.write_text(
        json.dumps({"version": 1, "n": len(rows), "inputs": rows}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf8",
        newline="\n",
    )
    doc = {
        "version": 1,
        "seed": SEED,
        "method": (
            "sort by sha256(seed:text) inside each category, "
            "alternate dev/test, parity carried across categories"
        ),
        "inputs_sha256": digest,
        "n_dev": sum(v == "dev" for v in assignment.values()),
        "n_test": sum(v == "test" for v in assignment.values()),
        "caveat": (
            "Frozen before M3 table work. The M1 table (data/ingredients/ingredients.csv) "
            "was written after the audit and already holds synonyms such as evoo, "
            "so it may have seen these inputs. Test is a fair check of M3 growth, "
            "not of M1. Test labels stay unread until M3 acceptance."
        ),
        "assignment": dict(sorted(assignment.items())),
    }
    OUT_SPLIT.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf8", newline="\n"
    )
    print(len(rows), doc["n_dev"], doc["n_test"], digest)


if __name__ == "__main__":
    main()
