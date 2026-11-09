"""Write ``results/m3_pack_v2.json`` from a built pack (M3 Task 7).

Build the pack first on a clean tree, then run this command on the same commit:

    uv run python scripts/build_pack.py --out build/pack
    uv run python scripts/m3_pack_result.py --pack build/pack

It re-reads the allow-listed inputs (hash checked), measures coverage with
``pantrychef.pack.build.coverage`` (the one definition), and checks the result against the
pack files. It stops without writing when a gate fails. It never changes a gate.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from pantrychef.eval.results import git_facts, write_result
from pantrychef.ingredients.table import IngredientTable
from pantrychef.pack.allowlist import load_allowlist, read_verified
from pantrychef.pack.build import PACK_FORMAT, coverage
from pantrychef.sources.wikibooks import parse_page

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "pantrychef" / "pack" / "allowlist.json"
RESULT = ROOT / "results" / "m3_pack_v2.json"
GATES = {"min_recipes": 2500, "min_recipes_fully_read": 0.60, "max_core_bytes": 3 * 1024 * 1024}


def failed_gates(recipes: int, fully_read: float, core_bytes: int) -> list[str]:
    """Return one message per failed gate. The gate values are fixed above."""
    bad = []
    if recipes < GATES["min_recipes"]:
        bad.append(f"recipes {recipes} < {GATES['min_recipes']}")
    if fully_read < GATES["min_recipes_fully_read"]:
        bad.append(f"recipes_fully_read {fully_read:.4f} < {GATES['min_recipes_fully_read']}")
    if core_bytes > GATES["max_core_bytes"]:
        bad.append(f"core {core_bytes} bytes > {GATES['max_core_bytes']}")
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pack", default="build/pack", type=Path)
    args = ap.parse_args(argv)
    pack = args.pack if args.pack.is_absolute() else ROOT / args.pack

    manifest = json.loads((pack / "manifest.v2.json").read_text(encoding="utf8"))
    commit = git_facts(ROOT)[0]
    if manifest["commit"] != commit:
        raise SystemExit(f"stale build: manifest commit {manifest['commit']}, HEAD {commit}")
    core_file = next(f for f in manifest["files"] if f["name"] == "core.v2.json.gz")
    core_bytes = (pack / core_file["name"]).read_bytes()
    if hashlib.sha256(core_bytes).hexdigest() != core_file["sha256"]:
        raise SystemExit("core file differs from the manifest")

    inputs, raw = load_allowlist(ALLOWLIST, ROOT)
    data = read_verified(inputs)  # checks every pinned hash
    table = IngredientTable.from_text(data["table"].decode("utf8"), data["words"].decode("utf8"))
    with gzip.open(inputs["snapshot"].path, "rt", encoding="utf8") as fh:
        records = [json.loads(line) for line in fh]
    on = raw["inputs"]["snapshot"]["retrieved_on"]
    cov = coverage([r for rec in records if (r := parse_page(rec, on))], table)

    core = json.loads(gzip.decompress(core_bytes))
    n = len(core["recipes"])
    packed_full = sum(all(ln["r"] for ln in r["lines"] if not ln["opt"]) for r in core["recipes"])
    same = (n, packed_full) == (cov["kept_recipes"], cov["fully_read"])
    if not same or core["format"] != PACK_FORMAT:
        raise SystemExit("coverage() and the pack core disagree")
    pack_lines = [ln for r in core["recipes"] for ln in r["lines"]]

    bad = failed_gates(n, cov["recipes_fully_read"], len(core_bytes))
    frac = cov["recipes_fully_read"]
    print(f"recipes {n}, recipes_fully_read {frac:.4f}, core {len(core_bytes)} bytes")
    if bad:
        print("GATE FAILED, nothing written:", "; ".join(bad))
        return 1

    text_file = next(f for f in manifest["files"] if f["name"] == "text.v2.json.gz")
    write_result(
        RESULT,
        {
            "label": "MEASURED",
            "what": "Pack v2 (format 2, table v2, word file) built from the Wikibooks snapshot. "
            "recipes_fully_read = kept recipes with every required line read / kept recipes, by "
            "pantrychef.pack.build.coverage. It is in-sample by design: it measures the cost of "
            "reading the pack, not quality.",
            "command": "uv run python scripts/build_pack.py --out build/pack && "
            "uv run python scripts/m3_pack_result.py --pack build/pack",
            "config": {
                "pack_format": PACK_FORMAT,
                "version": manifest["version"],
                "gates": GATES,
                "gates_passed": True,
                "recipes": n,
                "pages": manifest["counts"]["pages"],
                "dropped_no_required_line": manifest["counts"]["dropped_no_required_line"],
                "recipes_fully_read_count": cov["fully_read"],
                "core_bytes": len(core_bytes),
                "core_sha256": core_file["sha256"],
                "text_bytes": text_file["size"],
                "table_rows": len(table.rows),
                "table": raw["inputs"]["table"]["path"],
                "table_sha256": inputs["table"].sha256,
                "words_sha256": inputs["words"].sha256,
                "required_lines": cov["required_lines"],
                "lines_read": cov["lines_read"],
                "lines_read_share": cov["lines_read"] / cov["required_lines"],
                "pack_lines": len(pack_lines),
                "pack_unread_lines": sum(1 for ln in pack_lines if not ln["r"] and not ln["opt"]),
                "build_commit": manifest["commit"],
                "build_dirty": manifest["dirty"],
            },
            "seed": 0,
            "corpus_fingerprint": inputs["snapshot"].sha256,
            "arms": [],
            "metrics": [
                {
                    "name": "recipes_fully_read",
                    "arm": None,
                    "split": "all",
                    "n": n,
                    "value": cov["recipes_fully_read"],
                }
            ],
            "comparisons": [],
            "environment": {},
        },
        ROOT,
    )
    print(f"wrote {RESULT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
