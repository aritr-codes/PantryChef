"""Bare "pepper" lines in Wikibooks recipes (M3 plan, Task 6 and decision D5).

``draw`` collects the distinct snapshot lines where the resolver sets the bare "pepper" marker
(v2 table, M3 rules), drops every frozen line (test and extra lines, by hash), orders the rest
by sha256 of ``"45:bare_pepper:<line id>"`` (the ``sort_key`` of ``make_parser_gold_sheet``) and
keeps the first 80. It writes a blind sheet (``id,text,label``; no resolver output) and prints
counts only.

``score [FILE]`` reads the labelled lines: the committed ``data/eval/m3_bare_pepper_labels.v1.json``
(default) or a filled CSV sheet. Labels: ``black``, ``other``, ``unclear``. It writes
``results/m3_bare_pepper.json`` with the black share and its Wilson 95% interval, and prints the
D5 decision: ``always`` only when the lower bound is at least 0.85 (75 of 80), else
``staple_cue_or_taste``. It does not edit ``words.v1.json``.

Run from the repo root:
    uv run python scripts/m3_bare_pepper.py draw
    uv run python scripts/m3_bare_pepper.py score
    uv run python scripts/m3_bare_pepper.py score data/interim/m3_bare_pepper_sheet.filled.csv
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
from collections import Counter
from pathlib import Path

from pantrychef.eval.parser_gold import line_hash, load_frozen
from pantrychef.eval.results import write_result
from pantrychef.eval.stats import wilson
from pantrychef.ingredients.resolve import _PEPPER, _body, _spans, resolve_lines
from pantrychef.ingredients.table import TABLE_V2_PATH, IngredientTable, tokens
from scripts.make_parser_gold_sheet import SNAPSHOT, collect_lines, sort_key

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "data/interim/m3_bare_pepper_sheet.csv"
RESULT = ROOT / "results/m3_bare_pepper.json"
LABELS_FILE = ROOT / "data/eval/m3_bare_pepper_labels.v1.json"
# Counts from `draw` at M3 6a (v2 table, 682 rows, commit 0a42f42). Not re-derived on each score.
DRAW_COUNTS = {"pool": 103, "frozen": 2, "drawn": 80}
SEED = 45
N = 80
LABELS = ("black", "other", "unclear")
MIN_LOWER = 0.85  # D5: 75 of 80 black gives a Wilson lower bound of about 0.86
LABELLER = "one model labeller (Opus), blind; no owner adjudication"


def has_bare_pepper(text: str, table: IngredientTable) -> bool:
    """True when some comma chunk of ``text`` holds the bare "pepper" marker."""
    return any(
        i == _PEPPER
        for chunk in _body(text, table.words).split(",")
        for _, _, i in _spans(tokens(chunk), table)
    )


def draw(lines: list[dict], table: IngredientTable, frozen: frozenset[str], n: int = N) -> dict:
    """Return ``{"pool": int, "frozen": int, "rows": [...]}``. Rows hold ``id`` and ``text``."""
    marked = [r for r in lines if has_bare_pepper(r["text"], table)]
    pool = [r for r in marked if line_hash(r["text"]) not in frozen]
    pool.sort(key=lambda r: sort_key(SEED, "bare_pepper", r["id"]))
    rows = [{"id": r["id"], "text": r["text"]} for r in pool[:n]]
    return {"pool": len(pool), "frozen": len(marked) - len(pool), "rows": rows}


def write_sheet(rows: list[dict], path: Path = SHEET) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf8", newline="") as fh:
        out = csv.writer(fh, lineterminator="\n")
        out.writerow(["id", "text", "label"])
        for r in rows:
            out.writerow([r["id"], r["text"], ""])


def read_records(path: Path) -> tuple[list[dict], str]:
    """Return ``(records, labeller)``. JSON holds ``{"labeller", "lines"}``; CSV holds a sheet."""
    if Path(path).suffix == ".json":
        doc = json.loads(Path(path).read_text(encoding="utf8"))
        return list(doc["lines"]), doc.get("labeller", LABELLER)
    with open(path, encoding="utf8", newline="") as fh:
        return list(csv.DictReader(fh)), LABELLER


def read_labels(path: Path) -> dict[str, str]:
    """Return ``{id: label}``. Every row needs a known label."""
    labels: dict[str, str] = {}
    for rec in read_records(path)[0]:
        label = (rec.get("label") or "").strip().lower()
        if label not in LABELS:
            raise ValueError(f"line {rec['id']!r}: label {label!r} is not one of {LABELS}")
        if rec["id"] in labels:
            raise ValueError(f"line {rec['id']!r} appears twice")
        labels[rec["id"]] = label
    if not labels:
        raise ValueError(f"{path} has no labelled lines")
    return labels


def changed_under_always(records: list[dict], table: IngredientTable) -> dict:
    """Count the lines that read differently when ``bare_pepper.when`` is ``always``.

    ``changed_black`` counts those lines whose label is ``black``.
    """
    words = dataclasses.replace(
        table.words, bare_pepper={**table.words.bare_pepper, "when": "always"}
    )
    always = IngredientTable(list(table.rows), words)
    changed = black = 0
    for rec in records:
        a, b = (
            [(ln.options, ln.read) for ln in resolve_lines(rec["text"], t)] for t in (table, always)
        )
        if a != b:
            changed += 1
            black += (rec.get("label") or "").strip().lower() == "black"
    return {"changed": changed, "changed_black": black}


def decide(labels: dict[str, str]) -> dict:
    """Counts, black share, Wilson 95% interval and the D5 decision."""
    counts = Counter(labels.values())
    n, k = len(labels), counts["black"]
    lo, hi = wilson(k, n)
    return {
        "n": n,
        "counts": {lab: counts[lab] for lab in LABELS},
        "black_share": k / n,
        "ci": {"lo": lo, "hi": hi, "level": 0.95, "method": "wilson", "n_clusters": n},
        "decision": "always" if lo >= MIN_LOWER else "staple_cue_or_taste",
    }


def score(
    path: Path = LABELS_FILE, result: Path = RESULT, table: IngredientTable | None = None
) -> dict:
    out = decide(read_labels(path))
    records, labeller = read_records(path)
    table = table or IngredientTable.load(TABLE_V2_PATH)
    changed = changed_under_always(records, table)
    fingerprint = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    write_result(
        result,
        {
            "label": "MEASURED",
            "what": "Share of drawn bare 'pepper' Wikibooks lines labelled black pepper (plan D5). "
            f"Labels: {labeller}. "
            f"Decision: 'always' only if the Wilson lower bound >= {MIN_LOWER}.",
            "command": f"uv run python scripts/m3_bare_pepper.py score {_rel(path)}",
            "config": {
                "labeller": labeller,
                "labels": list(LABELS),
                "seed": SEED,
                "draw": "sha256 order of '45:bare_pepper:<line id>', first 80, frozen lines out",
                "table": "data/ingredients/ingredients.v2.csv",
                "snapshot": SNAPSHOT.name,
                "snapshot_sha256": hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest(),
                "table_sha256": hashlib.sha256(TABLE_V2_PATH.read_bytes()).hexdigest(),
                "min_lower": MIN_LOWER,
                "draw_counts": DRAW_COUNTS,
                "changed_under_always": {
                    "of": out["n"],
                    "lines": changed["changed"],
                    "black": changed["changed_black"],
                    "how": "resolve each labelled line with the table and with bare_pepper.when "
                    "= 'always'; count the lines whose reading differs",
                },
                "counts": out["counts"],
                "decision": out["decision"],
            },
            "seed": SEED,
            "corpus_fingerprint": fingerprint,
            "arms": [],
            "metrics": [
                {
                    "name": "bare_pepper_black_share",
                    "arm": None,
                    "split": "all",
                    "n": out["n"],
                    "value": out["black_share"],
                    "ci": out["ci"],
                }
            ],
            "comparisons": [],
            "environment": {},
        },
        ROOT,
    )
    return out


def _rel(p: str | Path) -> str:
    p = Path(p).resolve()
    return p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else str(p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("draw")
    sc = sub.add_parser("score")
    sc.add_argument("sheet", type=Path, nargs="?", default=LABELS_FILE)
    args = ap.parse_args(argv)

    if args.cmd == "draw":
        table = IngredientTable.load(TABLE_V2_PATH)
        got = draw(collect_lines(), table, load_frozen())
        write_sheet(got["rows"])
        print(f"- Bare-pepper lines (distinct, not frozen): {got['pool']}")
        print(f"- Frozen lines left out: {got['frozen']}")
        short = " (fewer lines than wanted: all taken)" if got["pool"] < N else ""
        print(f"- Drawn: {len(got['rows'])} of {N}{short}")
        print(f"- Sheet: {_rel(SHEET)}")
        return 0

    out = score(args.sheet)
    print(f"- n {out['n']}, counts {out['counts']}")
    print(f"- black share {out['black_share']:.3f}, Wilson 95% [{out['ci']['lo']:.3f}, "
          f"{out['ci']['hi']:.3f}]")  # fmt: skip
    print(f"- Decision (D5): bare_pepper.when = {out['decision']!r}. words.v1.json is unchanged.")
    print(f"- Result: {_rel(RESULT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
