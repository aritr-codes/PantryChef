"""Pairwise model for M4: pair features, Bradley-Terry fit, nested grouped CV, writers, freeze.

Plan sections 7.3 to 7.6 and steps 8, 12 and 15. A thin CLI calls ``run_train``,
``build_freeze`` and ``check_freeze``. Nothing here reads a pack or a sheet.

Model. A list is 5 recipes. Its feature is the mean of the 5 per-recipe feature vectors
(``pantrychef.rank.FEATURES``). The pair feature is ``z = mean(A) - mean(B)``. The model is
``P(A preferred) = sigmoid(w . z)``: logistic regression with no intercept and L2.
Each decided item enters twice, as ``(z, y)`` and ``(-z, 1 - y)``, so the fit is symmetric.
Ties (``y is None``) are dropped from the fit but stay in the training table.

Standardisation scales only (``sd`` = root mean square of the mirrored columns). Centring would
break the antisymmetry, and the mirrored mean is exactly 0 anyway, so ``mean`` is stored as 0.
Raw weights are ``w_std / sd``, so the browser needs no standardisation.

The one-standard-error rule (plan 7.4) is in ``one_se_pick``. Folds are by pantry (a pantry is
a group). They come from a seeded hash of the pantry id, so they do not depend on item order.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pantrychef.eval import results
from pantrychef.rank import FEATURES, linear_score

DEFAULT_SETS: dict[str, tuple[str, ...]] = {
    "F1": ("score", "missing"),
    "F2": ("score", "missing", "total_c", "short"),
    "F3": FEATURES,
}
DEFAULT_CS = (0.01, 0.03, 0.1, 0.3, 1.0)
CR = chr(13).encode()  # a carriage return in a frozen file would change its hash
_LICENCE_BY_LABELS = {
    "human": "MIT (derived from the owner's judgments and pack-v2 numbers)",
    "model_judged": (
        "MIT (derived from labels made by an LLM annotation pass, run offline once and "
        "reviewed by the owner, and from pack-v2 numbers; no LLM runs at run time)"
    ),
}


def licence_for(training_labels: str) -> str:
    """The weights file licence and provenance text. It follows the label source."""
    return _LICENCE_BY_LABELS[training_labels]


WEIGHTS_REL = "web/src/rank_model.v1.json"
PANTRIES_REL = "data/eval/m4/pantries.v1.json"
# Plan step 12 lists the first 16. The last 7 are the modules the three scripts import that
# build or score a list, read the pack or resolve names (checked by an import-closure test).
FREEZE_FILES = (
    WEIGHTS_REL,
    "data/eval/m4/train_table.v1.json",
    "data/eval/m4/analysis_plan.v1.md",
    PANTRIES_REL,
    "data/eval/m4/test_pantries_sha256.txt",
    "data/eval/m4/ui_decision.v1.json",
    "pantrychef/rank.py",
    "pantrychef/engine.py",
    "pantrychef/eval/pairwise.py",
    "pantrychef/eval/stats.py",
    "pantrychef/eval/arms.py",
    "pantrychef/eval/pantries.py",
    "pantrychef/eval/results.py",
    "scripts/judging_sheet.py",
    "scripts/judging_score.py",
    "scripts/m4_rank.py",
    "pantrychef/eval/m4_lists.py",
    "pantrychef/eval/m4_run.py",
    "pantrychef/eval/m4_pools.py",
    "pantrychef/ingredients/names.py",
    "pantrychef/ingredients/normalize.py",
    "pantrychef/ingredients/table.py",
    "pantrychef/ingredients/units.py",
)
TEST_POOL_FILE = "data/eval/m4/test_pantries_sha256.txt"
FREEZE_REL = "data/eval/m4/freeze.v1.json"


# ------------------------------------------------------------------ items and features


@dataclass(frozen=True)
class PairItem:
    pantry_id: str
    item_id: str
    arm_a: str
    arm_b: str
    y: int | None  # 1 = A preferred, 0 = B preferred, None = tie
    z: tuple[float, ...]  # mean(A) - mean(B), FEATURES order


def list_mean(vectors: Sequence[Sequence[float]]) -> tuple[float, ...]:
    """Mean of the per-recipe feature vectors of one list (sums in list order)."""
    n = len(vectors)
    return tuple(sum(v[k] for v in vectors) / n for k in range(len(FEATURES)))


def pair_z(
    vecs_a: Sequence[Sequence[float]], vecs_b: Sequence[Sequence[float]]
) -> tuple[float, ...]:
    return tuple(a - b for a, b in zip(list_mean(vecs_a), list_mean(vecs_b), strict=True))


def make_item(pantry_id, item_id, arm_a, arm_b, vecs_a, vecs_b, outcome: str) -> PairItem:
    """``outcome`` is ``"A"``, ``"B"`` or ``"tie"`` (the arm that won, by the key, not the side)."""
    y = {"A": 1, "B": 0, "tie": None}.get(outcome, "bad")
    if y == "bad":
        raise ValueError(f"outcome must be 'A', 'B' or 'tie', got {outcome!r}")
    return PairItem(pantry_id, item_id, arm_a, arm_b, y, pair_z(vecs_a, vecs_b))


def pair_score(weights: Sequence[float], z: Sequence[float]) -> float:
    return linear_score(z, weights)


def mirrored(items: Iterable[PairItem]) -> tuple[np.ndarray, np.ndarray]:
    """Decided items as rows ``(z, y)`` then ``(-z, 1 - y)``. Ties are dropped."""
    xs: list[tuple[float, ...]] = []
    ys: list[int] = []
    for it in items:
        if it.y is None:
            continue
        xs.append(it.z)
        ys.append(it.y)
        xs.append(tuple(-v for v in it.z))
        ys.append(1 - it.y)
    return np.array(xs, dtype=float).reshape(-1, len(FEATURES)), np.array(ys, dtype=int)


# ------------------------------------------------------------------ fit


@dataclass(frozen=True)
class Fit:
    weights: tuple[float, ...]  # raw: apply to z as it is
    std_weights: tuple[float, ...]
    mean: tuple[float, ...]
    sd: tuple[float, ...]


def fit_weights(items: Sequence[PairItem], feature_names: Sequence[str], C: float) -> Fit:
    """L2 logistic fit on the mirrored decided items, using only ``feature_names``."""
    from sklearn.linear_model import LogisticRegression

    cols = [FEATURES.index(f) for f in feature_names]
    x, y = mirrored(items)
    if len(y) == 0:
        raise ValueError("no decided items to fit")
    sd = np.sqrt((x**2).mean(axis=0))
    sd[sd == 0] = 1.0
    xs = x[:, cols] / sd[cols]
    clf = LogisticRegression(C=C, fit_intercept=False, tol=1e-10, max_iter=2000)
    clf.fit(xs, y)
    std = np.zeros(len(FEATURES))
    std[cols] = clf.coef_[0]
    raw = std / sd
    return Fit(tuple(raw.tolist()), tuple(std.tolist()), (0.0,) * len(FEATURES), tuple(sd.tolist()))


def _logloss_acc(weights: Sequence[float], items: Sequence[PairItem]) -> tuple[float, float]:
    """Mean log-loss and accuracy (a zero score counts half) over the decided items."""
    loss = acc = 0.0
    n = 0
    for it in items:
        if it.y is None:
            continue
        s = pair_score(weights, it.z)
        sign = 1.0 if it.y else -1.0
        loss += float(np.logaddexp(0.0, -sign * s))
        acc += 0.5 if s == 0 else float((s > 0) == bool(it.y))
        n += 1
    return loss / n, acc / n


# ------------------------------------------------------------------ folds, one-SE, nested CV


def grouped_folds(pantry_ids: Iterable[str], k: int, seed: int) -> list[list[str]]:
    """Split the distinct pantry ids into ``k`` folds. Deterministic, sizes differ by at most 1."""
    ids = sorted(set(pantry_ids), key=lambda p: hashlib.sha256(f"{seed}:{p}".encode()).hexdigest())
    if len(ids) < k:
        raise ValueError(f"{len(ids)} pantries cannot fill {k} folds")
    return [sorted(ids[i::k]) for i in range(k)]


@dataclass(frozen=True)
class Cell:
    feature_set: str
    C: float
    mean: float  # mean held-out log-loss over folds
    se: float  # standard error across folds


def one_se_pick(cells: Sequence[Cell], sets: dict[str, Sequence[str]]) -> tuple[str, float]:
    """Smallest feature set, then smallest C, whose mean is within one SE of the best mean.

    The SE is the standard error of the best cell.
    """
    best = min(cells, key=lambda c: (c.mean, len(sets[c.feature_set]), c.C))
    limit = best.mean + best.se
    ok = [c for c in cells if c.mean <= limit]
    pick = min(ok, key=lambda c: (len(sets[c.feature_set]), c.C, c.mean))
    return pick.feature_set, pick.C


def _by_pantry(items: Sequence[PairItem], pantries: Iterable[str]) -> list[PairItem]:
    keep = set(pantries)
    return [i for i in items if i.pantry_id in keep]


def inner_select(
    items: Sequence[PairItem], sets: dict, Cs: Sequence[float], k: int, seed: int
) -> tuple[str, float, list[Cell]]:
    """Grid search over feature set and C by grouped k-fold log-loss, then the one-SE rule."""
    folds = grouped_folds((i.pantry_id for i in items), k, seed)
    cells = []
    for name, feats in sets.items():
        for C in Cs:
            losses = []
            for fold in folds:
                held = _by_pantry(items, fold)
                train = [i for i in items if i.pantry_id not in set(fold)]
                losses.append(_logloss_acc(fit_weights(train, feats, C).weights, held)[0])
            se = float(np.std(losses, ddof=1) / math.sqrt(len(losses))) if len(losses) > 1 else 0.0
            cells.append(Cell(name, C, float(np.mean(losses)), se))
    name, C = one_se_pick(cells, sets)
    return name, C, cells


def nested_cv(
    items: Sequence[PairItem],
    sets: dict | None = None,
    Cs: Sequence[float] = DEFAULT_CS,
    outer_k: int = 5,
    inner_k: int = 4,
    seed: int = 42,
) -> dict:
    """Outer grouped k-fold around the whole selection procedure. Ties are ignored.

    Returns pooled held-out log-loss and accuracy of the procedure, the same for ``F1`` alone
    (its own best C), and the fold membership of every outer fold.
    """
    sets = sets or DEFAULT_SETS
    decided = [i for i in items if i.y is not None]
    folds = grouped_folds((i.pantry_id for i in decided), outer_k, seed)
    f1_name = next(iter(sets))  # the first set is the smallest
    pooled: list[tuple[PairItem, float]] = []
    f1_pooled: list[tuple[PairItem, float]] = []
    outer = []
    for held_ids in folds:
        held_set = set(held_ids)
        train = [i for i in decided if i.pantry_id not in held_set]
        held = _by_pantry(decided, held_ids)
        train_ids = sorted({i.pantry_id for i in train})
        assert not set(train_ids) & held_set, "a pantry crosses a fold"
        name, C, _ = inner_select(train, sets, Cs, inner_k, seed + 1)
        w = fit_weights(train, sets[name], C).weights
        _, C1, _ = inner_select(train, {f1_name: sets[f1_name]}, Cs, inner_k, seed + 1)
        w1 = fit_weights(train, sets[f1_name], C1).weights
        pooled += [(i, pair_score(w, i.z)) for i in held]
        f1_pooled += [(i, pair_score(w1, i.z)) for i in held]
        loss, acc = _logloss_acc(w, held)
        outer.append(
            {
                "test_pantries": sorted(held_set),
                "train_pantries": train_ids,
                "choice": {"feature_set": name, "C": C},
                "logloss": loss,
                "accuracy": acc,
            }
        )

    def pooled_stats(rows):
        loss = sum(float(np.logaddexp(0.0, -(1.0 if i.y else -1.0) * s)) for i, s in rows)
        acc = sum(0.5 if s == 0 else float((s > 0) == bool(i.y)) for i, s in rows)
        return loss / len(rows), acc / len(rows)

    ll, ac = pooled_stats(pooled)
    ll1, ac1 = pooled_stats(f1_pooled)
    return {
        "outer": outer,
        "n_decided": len(decided),
        "outer_logloss": ll,
        "outer_accuracy": ac,
        "f1_logloss": ll1,
        "f1_accuracy": ac1,
        "chance_logloss": math.log(2),
        "chance_accuracy": 0.5,
    }


def check_futility_1(outer_logloss: float) -> dict:
    """Check 1 (plan 7.5): the outer log-loss must be below chance, ``ln 2``."""
    return {"pass": outer_logloss < math.log(2), "outer_logloss": outer_logloss}


# ------------------------------------------------------------------ writers


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, data: object) -> str:
    """Write canonical JSON with LF endings. Return the sha256 of the bytes written."""
    blob = (json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf8")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(blob)
    return hashlib.sha256(blob).hexdigest()


def pantries_sha256(pantry_ids: Iterable[str]) -> str:
    """sha256 of the sorted distinct pantry ids joined by ``\\n`` (no trailing newline)."""
    return hashlib.sha256("\n".join(sorted(set(pantry_ids))).encode("utf8")).hexdigest()


def write_training_table(
    path: str | Path, items: Sequence[PairItem], training_labels: str = "human"
) -> str:
    """Write ``train_table.v1.json`` (no recipe text). Ties are rows with ``y = null``.

    ``training_labels`` (``human`` or ``model_judged``) says who made the labels (Amendment 2).
    """
    rows = [
        {
            "pantry_id": i.pantry_id,
            "item_id": i.item_id,
            "arm_a": i.arm_a,
            "arm_b": i.arm_b,
            "y": i.y,
            "z": list(i.z),
        }
        for i in items
    ]
    return _write_json(
        Path(path),
        {
            "version": 1,
            "features": list(FEATURES),
            "training_labels": training_labels,
            "rows": rows,
        },
    )


def read_training_table(path: str | Path) -> list[PairItem]:
    data = json.loads(Path(path).read_text(encoding="utf8"))
    if data["features"] != list(FEATURES):
        raise ValueError("training table features differ from pantrychef.rank.FEATURES")
    return [
        PairItem(r["pantry_id"], r["item_id"], r["arm_a"], r["arm_b"], r["y"], tuple(r["z"]))
        for r in data["rows"]
    ]


def read_weights(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf8"))


def run_train(
    items: Sequence[PairItem],
    *,
    weights_path: str | Path,
    table_path: str | Path,
    comparator: str,
    commit: str,
    dirty: bool = True,
    training_labels: str = "human",
    sets: dict | None = None,
    Cs: Sequence[float] = DEFAULT_CS,
    outer_k: int = 5,
    inner_k: int = 4,
    seed: int = 42,
) -> dict:
    """Plan step 8: nested CV, check 1, final fit, training table, weights file.

    ``items`` are all dev items (ties have ``y = None``). The table is always written. The
    weights file is written only when check 1 passes. Returns ``cv`` (for results/m4_cv.json),
    ``check1``, ``choice`` (feature set, C, grid cells) and the written hashes.
    """
    sets = sets or DEFAULT_SETS
    cv = nested_cv(items, sets, Cs, outer_k, inner_k, seed)
    check1 = check_futility_1(cv["outer_logloss"])
    table_sha = write_training_table(table_path, items, training_labels)
    decided = [i for i in items if i.y is not None]
    name, C, cells = inner_select(decided, sets, Cs, inner_k, seed + 1)
    fit = fit_weights(decided, sets[name], C)
    out = {
        "cv": cv,
        "check1": check1,
        "choice": {"feature_set": name, "C": C, "cells": [c.__dict__ for c in cells]},
        "train_table_sha256": table_sha,
        "weights_written": False,
    }
    if check1["pass"]:
        payload = {
            "version": 1,
            "features": list(FEATURES),
            "weights": list(fit.weights),
            "feature_set": name,
            "C": C,
            "standardisation": {"mean": list(fit.mean), "sd": list(fit.sd)},
            "trained_on": {
                "pantries_sha256": pantries_sha256(i.pantry_id for i in items),
                "train_table_sha256": table_sha,
                "training_labels": training_labels,
                "n_pantries": len({i.pantry_id for i in items}),
                "n_items": len(items),
                "n_decided": len(decided),
            },
            "cv": {"outer_logloss": cv["outer_logloss"], "outer_accuracy": cv["outer_accuracy"]},
            "comparator": comparator,
            "commit": commit,
            "dirty": dirty,  # recorded, never refused: the freeze needs a clean tree anyway
            "licence": licence_for(training_labels),
        }
        _write_json(Path(weights_path), payload)
        out["weights_written"] = True
    return out


# ------------------------------------------------------------------ freeze (plan steps 12 and 15)


class GitError(RuntimeError):
    pass


class FreezeError(RuntimeError):
    pass


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if done.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def _tracked(git: Callable, root: Path, rel: str) -> bool:
    try:
        git(root, "ls-files", "--error-unmatch", "--", rel)
    except GitError:
        return False
    return True


def _dirty(git: Callable, root: Path) -> str:
    # untracked files are ignored: only a changed tracked file can break a freeze
    return git(root, "status", "--porcelain", "--untracked-files=no").strip()


def freeze_blockers(
    root: str | Path,
    *,
    pack_core: str | Path,
    pinned_pack_sha256: str,
    files: Sequence[str] = FREEZE_FILES,
    generated: Sequence[str] = (),
    git: Callable = _git,
) -> list[str]:
    """What stops a freeze now: a dirty tree, a missing or untracked file, a wrong pack.

    ``generated`` files are written by the freeze command itself (``analysis_plan.v1.md``). They
    may be new, so they are not checked here. Outside a git repository the tree counts as dirty.
    """
    root = Path(root)
    problems = []
    try:
        if dirty := _dirty(git, root):
            problems.append(f"the tree is not clean: {dirty}")
    except GitError as e:
        problems.append(f"not a usable git repository: {e}")
    for rel in files:
        if rel in generated:
            continue
        if not (root / rel).is_file():
            problems.append(f"{rel} is missing")
        elif not _tracked(git, root, rel):
            problems.append(f"{rel} is not tracked by git")
    problems += [
        f"{rel} contains a carriage return (CRLF): the freeze hashes LF bytes"
        for rel in files
        if rel not in generated and (root / rel).is_file() and CR in (root / rel).read_bytes()
    ]
    pack_core = Path(pack_core)
    pack_sha = _sha256_file(pack_core) if pack_core.is_file() else None
    if pack_sha != pinned_pack_sha256:
        problems.append(f"pack core hash {pack_sha} differs from the pinned {pinned_pack_sha256}")
    return problems


def build_freeze(
    root: str | Path,
    *,
    pack_core: str | Path,
    pinned_pack_sha256: str,
    comparator: str,
    n_test: int,
    seed: int,
    files: Sequence[str] = FREEZE_FILES,
    test_pool_file: str = TEST_POOL_FILE,
    generated: Sequence[str] = (),
    git: Callable = _git,
    extra: dict | None = None,
) -> dict:
    """Plan step 12. Refuse unless the tree is clean, every file is tracked and the pack matches.

    ``generated`` lists files that the freeze command writes itself (``analysis_plan.v1.md``).
    They must exist but may be new: they enter git in the same freeze commit.

    Returns the dict for ``freeze.v1.json``: the sha256 of every file, of the pack core, the
    test-pool hash (the value stored in ``test_pantries_sha256.txt``), comparator, ``n_test``,
    seed and the HEAD commit. Hashes cover the bytes as they sit in the working tree.
    """
    root = Path(root)
    problems = freeze_blockers(
        root,
        pack_core=pack_core,
        pinned_pack_sha256=pinned_pack_sha256,
        files=files,
        generated=generated,
        git=git,
    )
    problems += [f"{rel} is missing" for rel in generated if not (root / rel).is_file()]
    if problems:
        raise FreezeError("; ".join(problems))
    return {
        "version": 1,
        "files": {rel: _sha256_file(root / rel) for rel in files},
        "pack_core_sha256": _sha256_file(Path(pack_core)),
        "test_pool_sha256": (root / test_pool_file).read_text(encoding="utf8").strip(),
        "comparator": comparator,
        "n_test": n_test,
        "seed": seed,
        "commit": git(root, "rev-parse", "HEAD").strip(),
        **(extra or {}),
    }


def write_freeze(path: str | Path, freeze: dict) -> str:
    return _write_json(Path(path), freeze)


def freeze_problems(
    root: str | Path,
    *,
    pack_core: str | Path,
    freeze_rel: str = FREEZE_REL,
    git: Callable = _git,
) -> list[str]:
    """Problems with the frozen files themselves: the freeze file is missing, a frozen file or
    the pack core changed, or a tracked file differs from HEAD. Empty means they match.

    The test-sheet builder uses this alone (plan 8.3). ``check_freeze`` adds the commit order.
    """
    root = Path(root)
    path = root / freeze_rel
    if not path.is_file():
        return [f"no freeze file at {freeze_rel}"]
    freeze = json.loads(path.read_text(encoding="utf8"))
    problems: list[str] = []
    for rel, want in freeze["files"].items():
        p = root / rel
        got = _sha256_file(p) if p.is_file() else None
        if got != want:
            problems.append(f"frozen file {rel} changed since the freeze")
        elif p.is_file() and CR in p.read_bytes():
            problems.append(f"frozen file {rel} contains a carriage return (CRLF)")
    pack_core = Path(pack_core)
    if not pack_core.is_file() or _sha256_file(pack_core) != freeze["pack_core_sha256"]:
        problems.append("pack core differs from the frozen pack hash")
    if dirty := _dirty(git, root):
        problems.append(f"the tree is not clean, files differ from HEAD: {dirty}")
    return problems


def key_order_problems(
    root: str | Path,
    *,
    key_hash_rel: str,
    answers_rel: str,
    commits: Callable[[Path, str], list[str]] = results.commits,
    is_ancestor: Callable[[Path, str, str], bool] = results.is_ancestor,
) -> list[str]:
    """The key hash is committed once, strictly before the answers are committed once (plan 8.1).

    Used for the pilot, dev and futility sheets. An empty list means the order holds. Outside a
    git repository the answer is a problem, not a crash.
    """
    root = Path(root)
    try:
        found = {rel: commits(root, rel) for rel in (key_hash_rel, answers_rel)}
    except Exception as e:  # not a git repo, or git is missing
        return [f"cannot read the git history of the key hash and the answers: {e}"]
    problems = []
    for rel, shas in found.items():
        if len(shas) != 1:
            problems.append(f"{rel} must have exactly one commit, found {len(shas)}")
    if problems:
        return problems
    older, newer = found[key_hash_rel][0], found[answers_rel][0]
    if older == newer:
        problems.append(f"{key_hash_rel} and {answers_rel} must be in different commits")
    elif not is_ancestor(root, older, newer):
        problems.append(f"commit order: {key_hash_rel} must be committed before {answers_rel}")
    return problems


def check_freeze(
    root: str | Path,
    *,
    pack_core: str | Path,
    key_path: str | Path,
    key_hash_rel: str,
    answers_rel: str,
    freeze_rel: str = FREEZE_REL,
    git: Callable = _git,
    commits: Callable[[Path, str], list[str]] = results.commits,
    is_ancestor: Callable[[Path, str, str], bool] = results.is_ancestor,
) -> list[str]:
    """Plan step 15. Return the list of problems. An empty list means the freeze holds.

    Checks: every frozen file and the pack core match their hashes; the tree is clean; the
    freeze, the key-hash file and the answers are tracked and each has exactly one commit, in
    that order; the key on disk hashes to the committed key-hash value.

    ``commits(root, rel)`` (newest first) and ``is_ancestor(root, older, newer)`` come from
    ``pantrychef.eval.results``. Tests inject fakes.
    """
    root = Path(root)
    problems = freeze_problems(root, pack_core=pack_core, freeze_rel=freeze_rel, git=git)
    shas: list[str] = []
    for rel in (freeze_rel, key_hash_rel, answers_rel):
        if not _tracked(git, root, rel):
            problems.append(f"{rel} is not tracked by git")
        found = commits(root, rel)
        if len(found) != 1:
            problems.append(f"{rel} must have exactly one commit, found {len(found)}")
        else:
            shas.append(found[0])
    if len(shas) == 3:
        for (older, a), (newer, b) in (
            ((shas[0], freeze_rel), (shas[1], key_hash_rel)),
            ((shas[1], key_hash_rel), (shas[2], answers_rel)),
        ):
            if older == newer:  # git says a commit is its own ancestor, so test this first
                problems.append(f"{a} and {b} must be in different commits (distinct, in order)")
            elif not is_ancestor(root, older, newer):
                problems.append(f"commit order: {a} must be committed before {b}")

    hash_file, key_file = root / key_hash_rel, Path(key_path)
    for p in (hash_file, key_file):
        if not p.is_file():
            problems.append(f"{p.name} is missing")
    if (
        hash_file.is_file()
        and key_file.is_file()
        and _sha256_file(key_file) != hash_file.read_text(encoding="utf8").strip()
    ):
        problems.append("the key on disk does not match its committed hash")
    return problems
