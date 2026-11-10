"""M3 acceptance run 2: the fresh held-out parser lines. It runs ONCE, on a clean tree.

    uv run python scripts/m3_acceptance_fresh.py

Acceptance run 1 (``scripts/m3_acceptance.py``) failed ``mention_accuracy`` on the random stratum,
so its test lines are spent. Run 2 scores the 200 fresh lines of ``fresh.v1.json``, drawn and
frozen before the table and resolver changed (``scripts/make_m3_fresh_lines.py``), against a new
blind gold-to-id map (plan D9) that the owner has checked. It is a SECOND attempt at the same
targets.

It gates ``mention_accuracy`` and ``parser_precision`` on the fresh lines (every fresh line is in
the random stratum) and copies the pack counts from ``results/m3_pack_v2.json``. It does not score
the typed inputs again, because their test half is spent. Run 1 measured ``input_accuracy`` on the
872-row table, and the result file says so. Every target is the one of run 1 (``TARGETS`` of
``scripts/m3_acceptance.py``). The script never softens one. If a target fails, it prints
STOP AND REPORT and exits 0. It refuses (exit 1, nothing written) on a dirty tree, an existing
result file, a missing, unchecked or incomplete map, or a line count other than 200. Refusals print
counts only, never a gold name or a line id.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from pantrychef.eval.parser_gold import FROZEN_FRESH, Label, line_hash, score
from pantrychef.eval.results import git_facts, write_result
from pantrychef.ingredients.table import DEFAULT_WORDS_PATH, TABLE_V2_PATH, IngredientTable
from scripts.m3_acceptance import (
    IGNORED,
    SEED,
    TARGETS,
    Refuse,
    _eg,
    _gold_names,
    _json,
    _labels,
    _row,
    _sha,
    check_map,
    dirty_paths,
    read_map,
    status,
)

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "data/eval/parser_gold"
EXPECTED_LINES = 200


@dataclass(frozen=True)
class Config:
    root: Path = ROOT
    fresh: Path = GOLD / "fresh.v1.json"
    frozen: Path = FROZEN_FRESH
    labels: Path = GOLD / "labels.fresh.v1.json"
    id_map: Path = ROOT / "data/eval/m3_fresh_gold_id_map.v1.json"
    table: Path = TABLE_V2_PATH
    words: Path = DEFAULT_WORDS_PATH
    pack_result: Path = ROOT / "results/m3_pack_v2.json"
    out: Path = ROOT / "results/m3_acceptance_fresh.json"
    expected_lines: int | None = EXPECTED_LINES
    command: str = "uv run python scripts/m3_acceptance_fresh.py"


def _target(name: str, metric: dict, k: int | None) -> dict:
    t = {
        "name": name, "metric": metric["name"], "value": metric["value"], "n": metric["n"],
        "k": k, "target": TARGETS[name], "status": status(metric["value"], TARGETS[name]),
    }  # fmt: skip
    ci = metric.get("ci")
    t.update(wilson_lo=ci["lo"] if ci else None, wilson_hi=ci["hi"] if ci else None)
    return t


def run(cfg: Config) -> int:
    try:
        return _run(cfg)
    except Refuse as e:
        print(f"REFUSED, nothing written: {e}")
        return 1


def _run(cfg: Config) -> int:
    root = cfg.root
    if cfg.out.exists():
        raise Refuse(f"{cfg.out.name} exists; one run only, do not rescore")
    dirty = dirty_paths(root)
    if not dirty and git_facts(root, exclude=(cfg.out,))[1]:
        dirty = ["(results.git_facts reports a dirty tree)"]
    if dirty:
        raise Refuse(f"the git tree is dirty ({len(dirty)} paths), for example {dirty[:5]}")

    table = IngredientTable.load(cfg.table, cfg.words)
    fresh = _json(cfg.fresh, "fresh lines")
    lines = fresh["lines"]
    if cfg.expected_lines is not None and len(lines) != cfg.expected_lines:
        raise Refuse(f"unexpected line count: {len(lines)}")
    if any(r.get("stratum") != "random" for r in lines):
        raise Refuse("a fresh line is not in the random stratum")
    if len({r["id"] for r in lines}) != len(lines):
        raise Refuse("the fresh line ids are not unique")
    sealed = set(_json(cfg.frozen, "frozen fresh hashes")["hashes"])
    if {line_hash(r["text"]) for r in lines} != sealed:
        raise Refuse("the fresh lines do not match the sealed hashes")
    labels: dict[str, Label] = _labels(cfg.labels, "fresh labels")
    missing = sorted(r["id"] for r in lines if r["id"] not in labels)
    if missing:
        raise Refuse(f"{len(missing)} lines have no label{_eg(missing, True)}")
    labels = {r["id"]: labels[r["id"]] for r in lines}
    doc = _json(cfg.id_map, "fresh id map")
    if not (isinstance(doc, dict) and doc.get("owner_checked") is True):
        raise Refuse("the fresh id map is not marked owner_checked")
    pmap = read_map(cfg.id_map, "fresh id map")
    check_map(pmap, _gold_names(labels), set(table.by_id), "fresh id map", quiet=True)

    pack = _json(cfg.pack_result, "pack result")
    try:
        pc = pack["config"]
        recipes, fully = int(pc["recipes"]), int(pc["recipes_fully_read_count"])
        pack_frac = next(m["value"] for m in pack["metrics"] if m["name"] == "recipes_fully_read")
    except (KeyError, StopIteration, TypeError, ValueError) as e:
        raise Refuse(f"pack result is malformed: {type(e).__name__}: {e}") from e
    if recipes < 1 or abs(fully / recipes - pack_frac) > 1e-9:
        raise Refuse("pack result: recipes_fully_read does not match its counts")
    if pack.get("dirty") or pc.get("build_dirty"):
        raise Refuse("the pack result was built from a dirty tree")
    for key, path in (("table_sha256", cfg.table), ("words_sha256", cfg.words)):
        if pc.get(key) != _sha(path):
            raise Refuse(f"pack result {key} does not match {path.name}: rebuild the pack result")

    parser = score(lines, labels, table, pmap)
    if parser["gold_groups"] == 0:
        raise Refuse("no gold groups in the fresh lines")
    group = {"stratum": "random"}
    # The result schema knows splits dev, test and all. The fresh lines are held-out test lines.
    m_men = _row(
        "mention_accuracy", parser["mention_correct"], parser["gold_groups"], "test", group
    )
    m_pre = _row("parser_precision", parser["pred_correct"], parser["pred_groups"], "test", group)
    m_pack = _row("recipes_fully_read", fully, recipes, "all")
    targets = [
        _target("mention_accuracy_random", m_men, parser["mention_correct"]),
        _target("parser_precision_random", m_pre, parser["pred_correct"]),
        _target("recipes_fully_read", m_pack, fully),
        {
            "name": "recipes", "metric": None, "value": recipes, "n": recipes, "k": None,
            "target": TARGETS["recipes"], "status": status(recipes, TARGETS["recipes"]),
            "wilson_lo": None, "wilson_hi": None,
        },
    ]  # fmt: skip
    failed = [t["name"] for t in targets if t["status"] != "PASS"]

    def rel(p: Path) -> str:
        p, r = Path(p).resolve(), root.resolve()
        return p.relative_to(r).as_posix() if p.is_relative_to(r) else str(p)

    files = [cfg.fresh, cfg.labels, cfg.id_map, cfg.table, cfg.words, cfg.pack_result]
    config = {
        "split": "fresh",
        "attempt": 2,
        "note": "Second attempt at the M3 targets. Run 1 is results/m3_acceptance.json. "
        "input_accuracy is not scored again: its test half is spent. Run 1 measured it on the "
        "872-row table.",
        "tables": {"v2_rows": len(table.rows)},
        "gold_to_id": "frozen blind id map (D9), owner checked",
        "ignored_untracked": list(IGNORED),
        "files_sha256": {rel(p): _sha(p) for p in files},
        "parser": {"random": parser},
        "pack": {
            "recipes": recipes,
            "recipes_fully_read_count": fully,
            "recipes_fully_read": pack_frac,
            "core_bytes": pc.get("core_bytes"),
        },
        "targets": targets,
        "all_targets_met": not failed,
        "stop_and_report": bool(failed),
        "failed": failed,
    }
    write_result(
        cfg.out,
        {
            "label": "MEASURED",
            "what": "M3 acceptance run 2 on the 200 fresh held-out lines (all random stratum), "
            "scored against the frozen blind id map. Pack counts are copied from "
            "results/m3_pack_v2.json. Second attempt at the run 1 targets.",
            "command": cfg.command,
            "config": config,
            "seed": SEED,
            "corpus_fingerprint": fresh["snapshot_sha256"],
            "arms": [],
            "metrics": [m_men, m_pre, m_pack],
            "comparisons": [],
            "environment": {},
        },
        root,
    )
    for t in targets:
        print(f"{t['status']}  {t['name']}: {t['value']:.4g} (target {t['target']}, n {t['n']})")
    print(f"wrote {cfg.out}")
    if failed:
        print(f"STOP AND REPORT: targets failed: {failed}. Do not lower a target or score again.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.parse_args(argv)
    return run(Config())


if __name__ == "__main__":
    raise SystemExit(main())
