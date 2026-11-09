"""ADR 0006 graph spike entry point (M3 Task 8).

Design: docs/research/2026-11-m3/graph_spike_design.md.

    uv run python scripts/graph_spike.py pantries
    uv run python scripts/graph_spike.py freeze --option a|b
    uv run python scripts/graph_spike.py sheet
    uv run python scripts/graph_spike.py score
    uv run python scripts/graph_spike.py skip --reason TEXT

``pantries`` loads the 40 dev pantries, resolves the names and prints the unknown ones.
``freeze`` copies the table, builds the pool, writes ``freeze.v1.json`` and prints the pool counts.
``sheet`` checks the freeze, draws the sample and writes the private sheet and key.
``score`` checks the freeze and git, reads the answers and writes ``results/m3_graph_spike.json``.
``skip`` writes the same file with verdict ``not_run`` (owner skip) or ``rejected`` (empty pool).
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
    t1 = gs.THRESHOLDS["T1"]
    print("T1 ceiling (new items in the pool and the pantries they come from, per edge type):")
    for etype, c in extras["pool_counts"]["edge_types"].items():
        print(f"  {etype}: {c['new']} new items from {c['pantries']} pantries")
        if c["new"] < t1["min_correct"] or c["pantries"] < t1["min_pantries"]:
            print(
                f"PRE-CHECK: T1 cannot pass for {etype}. It needs at least {t1['min_correct']} "
                f"correct items from at least {t1['min_pantries']} pantries. "
                f"The pool has {c['new']} items from {c['pantries']} pantries."
            )
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
    freeze_commit = _check_freeze_git(root, p)
    seed = manifest["plan"]["seed"]
    pack, pantries, _, edges = _load_context(root, p, manifest)
    pool, decoys = _pool(pack, edges, pantries)
    items = gs.draw(pool, decoys, seed)
    if not items:
        print("The pool is empty. Rejected: traversal adds no new recipe. No sheet is written.")
        _write_unrated(root, p, manifest, freeze_commit, "rejected", NO_NEW, None, "sheet")
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


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _commits(root: Path, rel: str) -> list[str]:
    return _git(root, "log", "--format=%H", "--", rel).split()


def _one_clean_commit(root: Path, rel: str, extra: tuple[str, ...] = ()) -> str:
    """The file has exactly one commit and neither it nor the ``extra`` files differ from HEAD."""
    commits = _commits(root, rel)
    if len(commits) != 1:
        raise SystemExit(f"{rel} must have exactly one commit, found {len(commits)}")
    dirty = _git(root, "status", "--porcelain", "--", rel, *extra).strip()
    if dirty:
        raise SystemExit(f"these files differ from their commit or are not committed: {dirty}")
    return commits[0]


def _older(root: Path, older: str, newer: str, what: str) -> None:
    ok = subprocess.run(
        ["git", "merge-base", "--is-ancestor", older, newer], cwd=root, capture_output=True
    ).returncode == 0  # fmt: skip
    if older == newer or not ok:
        raise SystemExit(f"{what}: the first commit must be an older ancestor of the second")


def _check_freeze_git(root: Path, p: SimpleNamespace) -> str:
    """One commit holds the freeze, and the frozen files match it. Return that commit."""
    inputs = [p.table, p.pantries] + ([p.labels] if p.labels.exists() else [])
    return _one_clean_commit(root, _rel(root, p.freeze), tuple(_rel(root, f) for f in inputs))


def _check_key_git(root: Path, p: SimpleNamespace, freeze_commit: str) -> tuple[str, str]:
    """The key hash is committed once, after the freeze. Return ``(commit, committed hash)``."""
    rel = _rel(root, p.key_sha)
    if not _commits(root, rel):
        raise SystemExit(f"{rel} is not committed. Commit the key hash before rating.")
    commit = _one_clean_commit(root, rel)
    _older(root, freeze_commit, commit, "freeze commit and key hash commit")
    return commit, _git(root, "show", f"{commit}:{rel}").strip()


def _check_answers_git(root: Path, p: SimpleNamespace, key_commit: str) -> str:
    """The answers file has one commit, newer than the key hash commit."""
    rel = _rel(root, p.answers)
    if not _commits(root, rel):
        raise SystemExit(f"{rel} is not committed. Commit the answers, then score.")
    commit = _one_clean_commit(root, rel)
    _older(root, key_commit, commit, "key hash commit and answers commit")
    return commit


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


NO_NEW = "no_new_recipes: traversal adds no new recipe beyond collapse and synonyms"


def _write_unrated(
    root: Path,
    p: SimpleNamespace,
    manifest: dict,
    freeze_commit: str,
    verdict: str,
    reason: str,
    out: Path | None,
    cmd: str,
) -> None:
    doc = gs.unrated_result_doc(
        manifest, verdict, reason, freeze_commit, gs.sha256_lf(p.freeze),
        f"uv run python scripts/graph_spike.py {cmd}",
    )  # fmt: skip
    path = out or p.result
    write_result(path, doc, root)
    print(f"wrote {path}; verdict {verdict}: {reason}")


def cmd_skip(root: Path, reason: str, out: Path | None = None) -> int:
    """The owner skips the rating after the pre-check. An empty pool is a rejection instead."""
    p = _paths(root)
    manifest = _checked_manifest(root, p)
    freeze_commit = _check_freeze_git(root, p)
    if p.key_sha.exists():
        raise SystemExit(f"{p.key_sha} exists. A sheet was made, so the rating was not skipped.")
    if not manifest["pool_counts"]["new"]:
        _write_unrated(root, p, manifest, freeze_commit, "rejected", NO_NEW, out, "skip")
    elif not reason.strip():
        raise SystemExit("skip needs --reason")
    else:
        _write_unrated(root, p, manifest, freeze_commit, "not_run", reason.strip(), out, "skip")
    return 0


def cmd_score(root: Path, out: Path | None = None) -> int:
    p = _paths(root)
    manifest = _checked_manifest(root, p)
    freeze_commit = _check_freeze_git(root, p)
    key_commit, committed_hash = _check_key_git(root, p, freeze_commit)
    _check_answers_git(root, p, key_commit)
    key_bytes = p.key.read_bytes()
    if hashlib.sha256(key_bytes).hexdigest() != committed_hash:
        raise SystemExit("the key differs from the hash in the key hash commit")
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
    sk = sub.add_parser("skip", help="record that the owner skipped the rating (verdict not_run)")
    sk.add_argument("--reason", default="")
    sk.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    root = args.root.resolve()
    if args.cmd == "pantries":
        return cmd_pantries(root)
    if args.cmd == "freeze":
        return cmd_freeze(root, args.option)
    if args.cmd == "sheet":
        return cmd_sheet(root)
    if args.cmd == "skip":
        return cmd_skip(root, args.reason, args.out)
    return cmd_score(root, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
