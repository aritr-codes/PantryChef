"""Results-file helper (M2). Every published number links to one of these files.

The contract is ``results/schema.v1.json``. ``web/scripts/result.mjs`` writes the same shape.
No third-party validator is used: ``validate`` checks the required keys and types by hand.

``METRICS`` and ``ARMS`` are fixed registries. A caller cannot declare its own role or
dependencies. A metric or arm that is not listed cannot be written (ADR 0005). A metric that
selects a model must not be a function of the features of that model.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
LABELS = ("MEASURED", "ESTIMATE", "HYPOTHESIS")
ROLES = ("selection", "sanity", "product", "latency")
SPLITS = ("dev", "test", "all")
MAX_DIRTY_PATHS = 20


@dataclass(frozen=True)
class MetricSpec:
    role: str
    depends_on: tuple[str, ...]
    justification: str = ""  # required for role "selection"


METRICS: dict[str, MetricSpec] = {
    "recall_at_10": MetricSpec("sanity", ("gold_recipe_lines",)),
    "mrr_at_10": MetricSpec("sanity", ("gold_recipe_lines",)),
    "makeable_at_10": MetricSpec("product", ("lines", "idf")),
    "hit_rate": MetricSpec("product", ("lines", "idf")),
    "visible_rate": MetricSpec("product", ("lines", "idf")),
    "pairwise_win_rate": MetricSpec("selection", (), "hand judgement, uses no model feature"),
    "latency_p50_ms": MetricSpec("latency", ()),
    "latency_p95_ms": MetricSpec("latency", ()),
    "latency_max_ms": MetricSpec("latency", ()),
}
# Arm name -> features the order of that arm uses.
ARMS: dict[str, tuple[str, ...]] = {
    "random": (),
    "overlap": ("have", "total"),
    "idf_flat": ("idf", "have", "total"),
    "shipped": ("idf", "have", "total", "group"),
}


class NotSelectable(ValueError):
    """Raised when a metric may not choose between arms."""


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def git_facts(root: Path, exclude: tuple[Path, ...] = ()) -> tuple[str, bool, list[str]]:
    """Return ``(commit, dirty, dirty_paths)``. Paths in ``exclude`` do not count as dirty.

    Dirty means tracked changes or untracked non-ignored files. Files under ``results/`` never
    count, because they are outputs of the command that writes the result.
    """
    root = Path(root).resolve()
    commit = _git(root, "rev-parse", "HEAD").strip()
    skip = {Path(p).resolve() for p in exclude}
    entries = _git(root, "status", "--porcelain", "-z", "--untracked-files=all").split("\0")
    paths: list[str] = []
    i = 0
    while i < len(entries):
        e = entries[i]
        i += 1
        if len(e) < 4:
            continue
        if e[0] in "RC":
            i += 1  # the next entry is the old name
        p = e[3:]
        if (root / p).resolve() in skip or p.startswith("results/"):
            continue
        paths.append(p)
    return commit, bool(paths), paths[:MAX_DIRTY_PATHS]


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _is_strs(x: Any) -> bool:
    return isinstance(x, list) and all(isinstance(s, str) for s in x)


def _need(obj: Any, keys: tuple[str, ...], where: str) -> None:
    if not isinstance(obj, dict):
        raise ValueError(f"{where}: must be an object")
    for k in keys:
        if k not in obj:
            raise ValueError(f"{where}: missing key {k!r}")


def _check(ok: bool, where: str, what: str) -> None:
    if not ok:
        raise ValueError(f"{where}: {what}")


def _validate_ci(ci: Any, where: str) -> None:
    _need(ci, ("lo", "hi", "level", "method", "n_clusters"), where)
    for k in ("lo", "hi", "level"):
        _check(_is_num(ci[k]), where, f"{k} must be a number")
    _check(isinstance(ci["method"], str), where, "method must be a string")
    _check(_is_int(ci["n_clusters"]), where, "n_clusters must be an integer")


def validate(doc: dict[str, Any]) -> None:
    """Raise ``ValueError`` when ``doc`` breaks the schema. Check metrics against ``METRICS``."""
    _need(
        doc,
        ("schema", "label", "what", "command", "commit", "dirty", "dirty_paths", "config", "seed",
         "corpus_fingerprint", "arms", "metrics", "comparisons", "environment"),
        "doc",
    )  # fmt: skip
    _check(_is_int(doc["schema"]) and doc["schema"] == SCHEMA_VERSION, "schema", "must be 1")
    _check(doc["label"] in LABELS, "label", f"must be one of {LABELS}")
    for k in ("what", "command", "corpus_fingerprint"):
        _check(isinstance(doc[k], str) and doc[k] != "", k, "must be a non-empty string")
    _check(
        isinstance(doc["commit"], str) and re.fullmatch(r"[0-9a-f]{40}", doc["commit"]) is not None,
        "commit",
        "must be 40 lowercase hex characters",
    )
    _check(isinstance(doc["dirty"], bool), "dirty", "must be a boolean")
    _check(
        _is_strs(doc["dirty_paths"]) and len(doc["dirty_paths"]) <= MAX_DIRTY_PATHS,
        "dirty_paths",
        f"must be a list of at most {MAX_DIRTY_PATHS} strings",
    )
    _check(isinstance(doc["config"], dict), "config", "must be an object")
    _check(_is_int(doc["seed"]), "seed", "must be an integer")
    _check(isinstance(doc["environment"], dict), "environment", "must be an object")
    _check(isinstance(doc.get("raw", {}), dict), "raw", "must be an object")
    for k in ("arms", "metrics", "comparisons"):
        _check(isinstance(doc[k], list), k, "must be a list")

    for a in doc["arms"]:
        _need(a, ("name", "features_used"), "arm")
        _check(a["name"] in ARMS, "arm", f"unknown arm {a['name']!r}")
        _check(_is_strs(a["features_used"]), "arm.features_used", "must be a list of strings")
        _check(
            tuple(a["features_used"]) == ARMS[a["name"]],
            "arm.features_used",
            f"features_used of {a['name']!r} must be {list(ARMS[a['name']])}",
        )

    for m in doc["metrics"]:
        _need(m, ("name", "role", "depends_on", "arm", "split", "n", "value"), "metric")
        w = f"metric {m['name']!r}"
        _check(m["name"] in METRICS, w, "not in the METRICS registry")
        spec = METRICS[m["name"]]
        _check(m["role"] in ROLES, w, f"role must be one of {ROLES}")
        _check(m["role"] == spec.role, w, f"role must be {spec.role!r}")
        _check(_is_strs(m["depends_on"]), w, "depends_on must be a list of strings")
        _check(
            tuple(m["depends_on"]) == spec.depends_on,
            w,
            f"depends_on must be {list(spec.depends_on)}",
        )
        _check(m["arm"] is None or m["arm"] in ARMS, w, f"unknown arm {m['arm']!r}")
        _check(m["split"] in SPLITS, w, f"split must be one of {SPLITS}")
        _check(_is_int(m["n"]) and m["n"] >= 0, w, "n must be an integer >= 0")
        _check(_is_num(m["value"]), w, "value must be a number")
        if "ci" in m:
            _validate_ci(m["ci"], w + " ci")
        _check(isinstance(m.get("group", {}), dict), w, "group must be an object")

    for c in doc["comparisons"]:
        _need(c, ("metric", "a", "b", "split", "diff", "ci"), "comparison")
        _check(c["metric"] in METRICS, "comparison", f"metric {c['metric']!r} not in METRICS")
        for k in ("a", "b"):
            _check(c[k] in ARMS, "comparison", f"unknown arm {c[k]!r}")
        _check(c["split"] in SPLITS, "comparison", f"split must be one of {SPLITS}")
        _check(_is_num(c["diff"]), "comparison", "diff must be a number")
        _check(isinstance(c["ci"], dict), "comparison", "ci must be an object")
        _check(isinstance(c.get("group", {}), dict), "comparison", "group must be an object")


def assert_selectable(metric: str, arms: list[str]) -> None:
    """Raise ``NotSelectable`` unless ``metric`` has role ``selection``.

    Also raise when a dependency of the metric is a feature of any arm.
    """
    if metric not in METRICS:
        raise ValueError(f"unknown metric {metric!r}")
    unknown = [a for a in arms if a not in ARMS]
    if unknown:
        raise ValueError(f"unknown arm(s) {unknown}")
    spec = METRICS[metric]
    if spec.role != "selection":
        raise NotSelectable(f"{metric} has role {spec.role!r}; only 'selection' may select")
    for a in arms:
        shared = sorted(set(spec.depends_on) & set(ARMS[a]))
        if shared:
            raise NotSelectable(f"{metric} depends on {shared}, which arm {a!r} uses")


def dump_result(path: Path, doc: dict[str, Any]) -> None:
    """Validate ``doc`` and write it: sorted keys, indent 2, LF newlines, trailing newline."""
    validate(doc)
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_result(path: Path, doc: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Fill commit, dirty, dirty_paths, environment, schema; validate; write sorted JSON."""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    commit, dirty, dirty_paths = git_facts(root, exclude=(Path(path),))
    out = dict(doc)
    out.update(schema=SCHEMA_VERSION, commit=commit, dirty=dirty, dirty_paths=dirty_paths)
    # Only the registries set role, dependencies and features. Callers cannot.
    out["metrics"] = [
        {**m, "role": METRICS[m["name"]].role, "depends_on": list(METRICS[m["name"]].depends_on)}
        if m.get("name") in METRICS
        else m
        for m in doc.get("metrics", [])
    ]
    names = list(doc.get("arms", [])) or [
        {"name": a} for a in sorted({m["arm"] for m in out["metrics"] if m.get("arm")})
    ]
    out["arms"] = [
        {"name": a["name"], "features_used": list(ARMS[a["name"]])} if a["name"] in ARMS else a
        for a in names
    ]
    out["environment"] = {
        **doc.get("environment", {}),
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} ({sys.platform})",
    }
    dump_result(path, out)
    return out


def load_result(path: Path) -> dict[str, Any]:
    """Read a results file and validate it."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(doc)
    return doc
