"""ADR 0006 graph spike entry point (M3 Task 8).

Design: docs/research/2026-11-m3/graph_spike_design.md.

    uv run python scripts/graph_spike.py pantries
    uv run python scripts/graph_spike.py freeze --option a|b
    uv run python scripts/graph_spike.py sheet
    uv run python scripts/graph_spike.py score

``pantries`` loads the 40 dev pantries, resolves the names and prints the unknown ones.
``freeze`` copies the table, builds the pool, writes ``freeze.v1.json`` and prints the pool counts.
``sheet`` checks the freeze, draws the sample and writes the private sheet and key.
``score`` checks the freeze and git, reads the answers and writes ``results/m3_graph_spike.json``.
The logic lives in ``pantrychef/eval/graph_spike.py``. This file only moves data.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import re
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

from pantrychef.eval import graph_spike as gs
from pantrychef.eval.results import write_result
from pantrychef.ingredients.table import IngredientTable

ROOT = Path(__file__).resolve().parents[1]
MIN_GROUP = gs.THRESHOLDS["T3"]["min_rated"]


def _paths(root: Path) -> SimpleNamespace:
    g = root / gs.GRAPH_DIR
    return SimpleNamespace(
        graph=g,
        table=g / gs.TABLE_NAME,
        pantries=g / gs.PANTRIES_NAME,
        labels=g / gs.LABELS_NAME,
        freeze=g / gs.FREEZE_NAME,
        answers=g / "answers.v1.csv",
        key_sha=g / "key_sha256.txt",
        sheet=root / "data" / "interim" / "graph_spike_sheet.v1.csv",
        key=root / "data" / "interim" / "graph_spike_key.v1.json",
        result=root / "results" / "m3_graph_spike.json",
        live_table=root / "data" / "ingredients" / "ingredients.v2.csv",
    )


def _json_bytes(obj: object) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return done.stdout


def _checked_manifest(root: Path, p: SimpleNamespace) -> dict:
    if not p.freeze.exists():
        raise SystemExit(f"{p.freeze} is missing. Run the freeze command first.")
    changed = gs.check_freeze(p.freeze, root)
    if changed:
        raise SystemExit("freeze check failed. Changed fields: " + ", ".join(changed))
    return json.loads(p.freeze.read_text(encoding="utf-8"))


def _load_context(root: Path, p: SimpleNamespace, manifest: dict):
    """Build the pack from the frozen inputs. Return ``(pack, pantries, unknown, edges)``."""
    edges = [tuple(e) for e in manifest["edges_in_use"]["edges"]]
    with tempfile.TemporaryDirectory() as tmp:
        pack = gs.build_frozen_pack(root, Path(tmp) / "pack")
    pantries, unknown = gs.resolve_pantries(pack, gs.load_pantries(p.pantries))
    return pack, pantries, unknown, edges


def _pool(pack, edges, pantries):
    return gs.build_pool(pack, edges, {pid: v["ids"] for pid, v in pantries.items()})


# ---------------------------------------------------------------------------- pantries


def cmd_pantries(root: Path) -> int:
    p = _paths(root)
    doc = gs.load_pantries(p.pantries)
    table_path = p.table if p.table.exists() else p.live_table
    table = IngredientTable.load(table_path, root / gs.WORDS_REL)
    keys = {" ".join(k): i for k, i in table.keys.items()}
    pantries, unknown = gs.resolve_pantries(SimpleNamespace(keys=keys, words=table.words), doc)
    ids = [x["id"] for x in doc["pantries"]]
    sets = [v["set"] for v in pantries.values()]
    problems = []
    if doc.get("split") != "dev":
        problems.append("split is not dev")
    if len(set(ids)) != len(ids):
        problems.append("pantry ids are not unique")
    print(f"table {table_path.name}: {len(ids)} pantries, {sets.count('pilot')} pilot, "
          f"{sets.count('new')} new")  # fmt: skip
    n_names = sum(len(v["names"]) for v in pantries.values())
    n_bad = sum(len(v) for v in unknown.values())
    print(f"{n_bad} of {n_names} names are unknown")
    for pid, names in unknown.items():
        print(f"  {pid}: {', '.join(names)}")
    for msg in problems:
        print(f"PROBLEM: {msg}")
    return 1 if problems else 0


# ---------------------------------------------------------------------------- freeze


def cmd_freeze(root: Path, option: str) -> int:
    p = _paths(root)
    if p.freeze.exists():
        raise SystemExit(f"{p.freeze} exists. A freeze is one commit and never changes.")
    for need in (p.pantries, p.live_table):
        if not need.exists():
            raise SystemExit(f"{need} is missing")
    if option == "b" and not p.labels.exists():
        raise SystemExit(f"option b needs {p.labels}")
    shutil.copyfile(p.live_table, p.table)
    try:
        base = gs.freeze_manifest(root, gs.PLAN, gs.THRESHOLDS, option)
        pack, pantries, unknown, edges = _load_context(root, p, base)
        pool, decoys = _pool(pack, edges, pantries)
        extras = {
            "pool_counts": gs.pool_counts(pool, decoys),
            "pool_by_edge": gs.pool_by_edge(pool, top=10),
            "edge_source_hits": gs.edge_source_hits(pack, edges, pantries),
            "unknown_names": unknown,
        }
        manifest = gs.freeze_manifest(root, gs.PLAN, gs.THRESHOLDS, option, extras)
    except BaseException:
        p.table.unlink(missing_ok=True)  # no half freeze
        raise
    p.freeze.write_bytes(_json_bytes(manifest))
    used = manifest["edges_in_use"]
    print(f"wrote {p.freeze}")
    print(f"edge option {option}; edges in use {used['count_per_type']}; "
          f"max depth {manifest['max_depth_observed']}")  # fmt: skip
    print("pool counts (new items per group and signature):")
    for name, n in extras["pool_counts"]["new"].items():
        print(f"  {name}: {n}")
    print(f"decoy candidates: {extras['pool_counts']['decoy_candidates']}")
    print("top edges in the pool:")
    for row in extras["pool_by_edge"]:
        print("  {} {} {}: {}".format(*row))
    print(f"edge source hits: {extras['edge_source_hits']['pilot']} pilot, "
          f"{extras['edge_source_hits']['new']} new")  # fmt: skip
    per_group = {g: sum(n for k, n in extras["pool_counts"]["new"].items() if k.startswith(g))
                 for g in gs.SAMPLED_GROUPS}  # fmt: skip
    if not pool:
        print("PRE-CHECK: the pool is empty. The result is Rejected: no new recipes.")
    elif min(per_group.values()) < MIN_GROUP:
        print(
            f"PRE-CHECK: a group has fewer than {MIN_GROUP} new items {per_group}. "
            "T3 will fail, so the verdict will be Rejected. The owner may skip the rating."
        )
    print("Do not change the edges, the option or the labels after you read these counts.")
    return 0


# ---------------------------------------------------------------------------- sheet


def cmd_sheet(root: Path) -> int:
    p = _paths(root)
    manifest = _checked_manifest(root, p)
    seed = manifest["plan"]["seed"]
    pack, pantries, _, edges = _load_context(root, p, manifest)
    pool, decoys = _pool(pack, edges, pantries)
    items = gs.draw(pool, decoys, seed)
    if not items:
        print("The pool is empty. Rejected: traversal adds no new recipe. No sheet is written.")
        return 0
    key = gs.make_key(items, pool, {pid: v["set"] for pid, v in pantries.items()}, seed)
    key_bytes = _json_bytes(key)
    digest = hashlib.sha256(key_bytes).hexdigest()
    if p.key_sha.exists() and p.key_sha.read_text().strip() != digest:
        raise SystemExit(f"key hash differs from {p.key_sha}. The key must not change. Stop.")
    rows = gs.sheet_rows(items, pack, pantries, edges)
    p.sheet.parent.mkdir(parents=True, exist_ok=True)
    with open(p.sheet, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(gs.SHEET_COLUMNS), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    p.key.write_bytes(key_bytes)
    p.key_sha.write_text(digest + "\n", encoding="utf-8")
    gaps = gs.repeat_gaps(items)
    new_n = sum(1 for i in items if i.kind == "new" and not i.repeat_of)
    print(f"{len(items)} items ({new_n} new, {new_n} decoys, {len(gaps)} repeats). "
          f"Key sha256 {digest}")  # fmt: skip
    if gaps and gaps[0] < manifest["plan"]["repeat_min_gap"]:
        print(f"WARNING: the closest repeat is {gaps[0]} places from its original")
    print(f"sheet {p.sheet}; key {p.key}; commit {p.key_sha} before rating")
    return 0


# ---------------------------------------------------------------------------- score


def _check_git(root: Path, p: SimpleNamespace) -> tuple[str, str]:
    """One commit holds the freeze. It must be older than the commit that adds the answers."""
    rel_freeze = p.freeze.relative_to(root).as_posix()
    rel_answers = p.answers.relative_to(root).as_posix()
    commits = _git(root, "log", "--format=%H", "--", rel_freeze).split()
    if len(commits) != 1:
        raise SystemExit(f"{rel_freeze} must have exactly one commit, found {len(commits)}")
    if _git(root, "status", "--porcelain", "--", rel_freeze).strip():
        raise SystemExit(f"{rel_freeze} differs from its commit")
    added = _git(root, "log", "--diff-filter=A", "--format=%H", "--", rel_answers).split()
    if not added:
        raise SystemExit(f"{rel_answers} is not committed. Commit the answers, then score.")
    freeze_commit, answers_commit = commits[0], added[-1]
    older = subprocess.run(
        ["git", "merge-base", "--is-ancestor", freeze_commit, answers_commit], cwd=root
    ).returncode == 0  # fmt: skip
    if freeze_commit == answers_commit or not older:
        raise SystemExit("the freeze commit must be an older ancestor of the answers commit")
    return freeze_commit, answers_commit


def _read_answers(path: Path) -> tuple[list[dict], dict]:
    text = path.read_text(encoding="utf-8-sig")
    comments = [ln.lstrip("#").strip() for ln in text.splitlines() if ln.startswith("#")]
    said = " ".join(comments).lower()
    if "have / have not" in said or not re.search(r"\bhave (not )?read\b", said):
        raise SystemExit(
            "the answers file needs one line that starts with # and says 'I have read' or "
            "'I have not read' the is_a and form_of columns or the edge labels"
        )
    read_edges = "no" if "have not read" in said else "yes"
    body = "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))
    rows = list(csv.DictReader(body.splitlines()))
    secs = []
    for r in rows:
        with contextlib.suppress(ValueError):
            secs.append(float(r.get("seconds") or ""))
    return rows, {
        "read_edges": read_edges,
        "median_seconds": statistics.median(secs) if secs else None,
    }


def cmd_score(root: Path, out: Path | None = None) -> int:
    p = _paths(root)
    manifest = _checked_manifest(root, p)
    freeze_commit, _ = _check_git(root, p)
    key_bytes = p.key.read_bytes()
    if hashlib.sha256(key_bytes).hexdigest() != p.key_sha.read_text().strip():
        raise SystemExit("the key differs from its committed hash")
    key = json.loads(key_bytes)
    answers, rater = _read_answers(p.answers)
    scored = gs.score(key, answers, manifest["thresholds"], manifest["plan"]["seed"],
                      manifest["plan"]["bootstrap_resamples"])  # fmt: skip
    doc = gs.result_doc(manifest, scored, key, rater, freeze_commit, gs.sha256_lf(p.freeze),
                        "uv run python scripts/graph_spike.py score")  # fmt: skip
    path = out or p.result
    write_result(path, doc, root)
    print(f"wrote {path}")
    print(f"checks {scored['checks']}; verdict {scored['verdict']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (tests use a copy)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pantries")
    fz = sub.add_parser("freeze")
    fz.add_argument("--option", choices=("a", "b"), required=True)
    sub.add_parser("sheet")
    sc = sub.add_parser("score")
    sc.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    root = args.root.resolve()
    if args.cmd == "pantries":
        return cmd_pantries(root)
    if args.cmd == "freeze":
        return cmd_freeze(root, args.option)
    if args.cmd == "sheet":
        return cmd_sheet(root)
    return cmd_score(root, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
