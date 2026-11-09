"""The M3 acceptance run (plan Task 9). It runs ONCE, on the held-out test data, on a clean tree.

    uv run python scripts/m3_acceptance.py

It scores, against the frozen blind id maps (plan D9):

1. Parser lines, the test half of the gold sheet plus the extra lines: ``mention_accuracy`` and
   ``parser_precision`` on the ``random`` stratum (the D2 gate), and on ``hard`` and ``rare``
   separately. Table: v2.
2. The test typed inputs: ``input_accuracy`` for M1 and for M3, paired per input: exact McNemar
   and a paired bootstrap interval of the accuracy difference. M1 is the shipped M1 resolver:
   one exact lookup (``resolve_names`` on ``main``) in the v1 table keys, built and looked up
   with the OLD tokens, ``canonicalize(fold(x)).split()``. It does not use the new singulariser.
   M3 is ``resolve_name`` on the v2 table with the current ``tokens``.
3. The pack counts, copied from ``results/m3_pack_v2.json``. The pack is not rebuilt.

It writes ``results/m3_acceptance.json``. Every target is fixed in ``TARGETS`` below. The script
never softens one. If a target fails, the result says ``stop_and_report`` and the owner decides.
Do not tune and score again.

It refuses (exit 1, nothing written) when the tree is dirty (by ``git status`` and by
``results.git_facts``), when the result file exists ("do not rescore"), when an id map is missing
or incomplete, when the pack result is dirty or was built from other table or word files, or when
an input is malformed. Refusals of the real run print counts only, never a gold name, line id or
input text.

``--dry-run-on dev --out PATH`` runs the same code on the DEV halves (dev parser lines, dev
labels, ``dev_id_map.v1.json``, dev typed inputs scored through the table keys) and writes to PATH.
It never reads test or extra data and never writes ``results/m3_acceptance.json``. A dry run
only WARNS about a dirty tree and about a pack result that does not match the files, because the
tree is dirty during development.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pantrychef.eval.parser_gold import Label, read_labels_json, score
from pantrychef.eval.realistic import score_inputs
from pantrychef.eval.results import git_facts, write_result
from pantrychef.eval.stats import mcnemar_exact, paired_cluster_bootstrap, wilson
from pantrychef.ingredients.names import resolve_name
from pantrychef.ingredients.normalize import canonicalize
from pantrychef.ingredients.table import (
    DEFAULT_WORDS_PATH,
    TABLE_V1_PATH,
    TABLE_V2_PATH,
    IngredientTable,
    fold,
    tokens,
)

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "data/eval/parser_gold"
EVAL = ROOT / "data/eval"
RESULT = ROOT / "results/m3_acceptance.json"
STRATA = ("random", "hard", "rare")
SEED = 46
RESAMPLES = 10_000
# Fixed targets (plan sections 3 and 8, D2 and D3). Nothing below this line may lower one.
TARGETS = {
    "mention_accuracy_random": 0.90,
    "parser_precision_random": 0.90,
    "input_accuracy_m3": 0.90,
    "recipes_fully_read": 0.60,
    "recipes": 2500,
}
EXPECTED = {"test_lines": 150, "test_random": 50, "extra_lines": 100, "test_inputs": 83}
# Untracked files that never change a result. Anything else untracked or modified is dirty.
IGNORED = (
    ".claude",
    ".codegraph",
    "CODEX_HANDOFF.md",
    "TestRun.md",
    "scratch_codex_audit_prompt.md",
    "temp_pytest",
    "data/interim",
)


class Refuse(Exception):
    """A guard stopped the run. Nothing was written."""


@dataclass(frozen=True)
class Config:
    root: Path
    split: str  # "test" (the real run) or "dev" (the dry run)
    sheet: Path
    extra: Path | None
    parser_labels: tuple[Path, ...]
    parser_map: Path | None
    input_split: Path
    input_labels: Path
    input_map: Path | None  # None: gold names map through the v2 table keys (dev only)
    table_v1: Path
    table_v2: Path
    words: Path
    pack_result: Path
    out: Path
    command: str
    strict: bool  # the real run: clean tree and one run only
    expected: dict[str, int] | None  # set sizes of the real run


def real_config() -> Config:
    return Config(
        root=ROOT,
        split="test",
        sheet=GOLD / "sheet.v1.json",
        extra=GOLD / "extra.v1.json",
        parser_labels=(GOLD / "labels.test.v2.json", GOLD / "labels.extra.v1.json"),
        parser_map=EVAL / "m3_gold_id_map.v1.json",
        input_split=EVAL / "realistic_inputs.split.v1.json",
        input_labels=EVAL / "realistic_inputs.labels.v1.json",
        input_map=EVAL / "m3_input_gold_id_map.v1.json",
        table_v1=TABLE_V1_PATH,
        table_v2=TABLE_V2_PATH,
        words=DEFAULT_WORDS_PATH,
        pack_result=ROOT / "results/m3_pack_v2.json",
        out=RESULT,
        command="uv run python scripts/m3_acceptance.py",
        strict=True,
        expected=EXPECTED,
    )


def dev_config(out: Path) -> Config:
    return Config(
        root=ROOT,
        split="dev",
        sheet=GOLD / "sheet.v1.json",
        extra=None,
        parser_labels=(GOLD / "labels.dev.v1.json",),
        parser_map=GOLD / "dev_id_map.v1.json",
        input_split=EVAL / "realistic_inputs.split.v1.json",
        input_labels=EVAL / "realistic_inputs.labels.v1.json",
        input_map=None,
        table_v1=TABLE_V1_PATH,
        table_v2=TABLE_V2_PATH,
        words=DEFAULT_WORDS_PATH,
        pack_result=ROOT / "results/m3_pack_v2.json",
        out=out,
        command=f"uv run python scripts/m3_acceptance.py --dry-run-on dev --out {out}",
        strict=False,
        expected=None,
    )


# ---- guards -----------------------------------------------------------------------------


def dirty_paths(root: Path) -> list[str]:
    """Modified, staged or untracked paths, except the known scratch paths in ``IGNORED``."""
    spec = [f":(exclude){p}" for p in IGNORED]
    out = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", ".", *spec],
        cwd=root, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout  # fmt: skip
    return [ln[3:] for ln in out.splitlines()]


def _json(path: Path | None, what: str):
    if path is None or not Path(path).is_file():
        raise Refuse(f"{what} is missing: {path}")
    try:
        return json.loads(Path(path).read_text(encoding="utf8"))
    except ValueError as e:
        raise Refuse(f"{what} is not valid JSON: {path} ({e})") from e


def _labels(path: Path, what: str) -> dict[str, Label]:
    _json(path, what)
    try:
        return read_labels_json(path)
    except (KeyError, TypeError, ValueError) as e:
        raise Refuse(f"{what} is malformed: {path} ({type(e).__name__}: {e})") from e


def read_map(path: Path | None, what: str) -> dict[str, str | None]:
    """Read a gold-name-to-id map: ``{"version", "mapper", "map"}``, or a flat dev map."""
    doc = _json(path, what)
    m = doc.get("map") if isinstance(doc, dict) and "version" in doc else doc
    if not isinstance(m, dict) or not all(v is None or isinstance(v, str) for v in m.values()):
        raise Refuse(f"{what} has no usable map: {path}")
    return m


def check_map(
    m: dict[str, str | None], names: set[str], ids: set[str], what: str, *, quiet: bool = False
) -> None:
    """Refuse when the map is not usable for ``names``. Names are compared by ``tokens``.

    Bad: an id that is not a table id, two keys with equal tokens and different ids (the scorer
    would keep one silently), or a gold name with no entry. ``quiet`` prints counts only.
    """
    bad = sorted({v for v in m.values() if v is not None and v not in ids})
    if bad:
        raise Refuse(f"{what} maps ids that are not in the v2 table: {bad}")
    seen: dict[tuple[str, ...], str | None] = {}
    clash = sorted({k for k, v in m.items() if seen.setdefault(tokens(k), v) != v})
    if clash:
        raise Refuse(
            f"{what} has {len(clash)} keys that clash with an equal key{_eg(clash, quiet)}"
        )
    have = {tokens(k) for k in m}
    missing = sorted(n for n in names if tokens(n) not in have)
    if missing:
        raise Refuse(f"{what} has no entry for {len(missing)} gold names{_eg(missing, quiet)}")


def _eg(items: list, quiet: bool) -> str:
    """``, for example [...]``, or nothing when ``quiet`` (the real run prints no held-out text)."""
    return "" if quiet else f", for example {items[:5]}"


def old_tokens(text: str) -> tuple[str, ...]:
    """The M1 tokens, as on ``main``: ``canonicalize(fold(x)).split()``. No new singulariser."""
    return tuple(canonicalize(fold(text)).split())


def m1_resolver(table: IngredientTable):
    """The shipped M1 typed-name resolver: one exact key lookup (``resolve_names`` on ``main``).

    Keys come from the names and synonyms of ``table`` with the OLD tokens, first owner wins.
    """
    keys: dict[str, str] = {}
    for r in table.rows:
        for text in (r.name, *r.synonyms):
            if key := " ".join(old_tokens(text)):
                keys.setdefault(key, r.id)

    def resolve(text: str) -> list[str]:
        hit = keys.get(" ".join(old_tokens(text)))
        return [hit] if hit else []

    return resolve


def _gold_names(labels: dict[str, Label]) -> set[str]:
    return {a for lab in labels.values() for g in lab.groups for a in g}


# ---- scoring ----------------------------------------------------------------------------


def status(value: float, target: float) -> str:
    return "PASS" if value >= target else "FAIL"


def paired(m1: list[int], m3: list[int], *, seed: int = SEED, resamples: int = RESAMPLES) -> dict:
    """Paired comparison of per-input correctness (1 or 0): counts, exact McNemar, bootstrap."""
    n = len(m1)
    b = sum(1 for x, y in zip(m1, m3, strict=True) if y and not x)  # only M3 right
    c = sum(1 for x, y in zip(m1, m3, strict=True) if x and not y)  # only M1 right
    iv = paired_cluster_bootstrap(
        [float(y) for y in m3], [float(x) for x in m1], [str(i) for i in range(n)],
        resamples=resamples, seed=seed,
    )  # fmt: skip
    return {
        "m3_only_correct": b,
        "m1_only_correct": c,
        "mcnemar_p": mcnemar_exact(b, c),
        "diff": (b - c) / n,
        "bootstrap": {
            "lo": iv.lo, "hi": iv.hi, "level": iv.level, "method": iv.method,
            "seed": seed, "resamples": resamples, "n_clusters": iv.n_clusters,
        },
    }  # fmt: skip


def _row(name: str, k: int, n: int, split: str, group: dict | None = None) -> dict:
    """A metric record with a Wilson 95% interval (none when n is 0)."""
    m = {"name": name, "arm": None, "split": split, "n": n, "value": k / n if n else 0.0}
    if group:
        m["group"] = group
    if n:
        lo, hi = wilson(k, n)
        m["ci"] = {"lo": lo, "hi": hi, "level": 0.95, "method": "wilson", "n_clusters": n}
    return m


def _target(name: str, metric: dict, k: int | None) -> dict:
    t = {
        "name": name, "metric": metric["name"], "value": metric["value"], "n": metric["n"],
        "k": k, "target": TARGETS[name], "status": status(metric["value"], TARGETS[name]),
    }  # fmt: skip
    ci = metric.get("ci")
    t.update(wilson_lo=ci["lo"] if ci else None, wilson_hi=ci["hi"] if ci else None)
    return t


def _sha(path: Path | None) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None


def run(cfg: Config) -> int:
    try:
        return _run(cfg)
    except Refuse as e:
        print(f"REFUSED, nothing written: {e}")
        return 1


def _problem(cfg: Config, msg: str) -> None:
    """Refuse in the real run. In a dry run print a warning and go on."""
    if cfg.strict:
        raise Refuse(msg)
    print(f"WARNING (dry run, would refuse in the real run): {msg}")


def _run(cfg: Config) -> int:
    root = cfg.root
    if cfg.split != "test" and cfg.out.resolve() == RESULT.resolve():
        raise Refuse("a dry run never writes results/m3_acceptance.json")
    if cfg.strict and cfg.out.exists():
        raise Refuse(f"{cfg.out.name} exists; one run only, do not rescore")
    dirty = dirty_paths(root)
    if cfg.strict and not dirty and git_facts(root, exclude=(cfg.out,))[1]:
        dirty = ["(results.git_facts reports a dirty tree)"]
    if dirty:
        _problem(cfg, f"the git tree is dirty ({len(dirty)} paths), for example {dirty[:5]}")

    t1 = IngredientTable.load(cfg.table_v1, cfg.words)
    t2 = IngredientTable.load(cfg.table_v2, cfg.words)
    ids = set(t2.by_id)

    # Parser lines and labels.
    sheet = _json(cfg.sheet, "gold sheet")
    lines = [r for r in sheet["lines"] if r["split"] == cfg.split]
    n_extra, n_random = 0, sum(r["stratum"] == "random" for r in lines)
    if cfg.extra is not None:
        extra = _json(cfg.extra, "extra lines")["lines"]
        n_extra = len(extra)
        lines += extra
        if cfg.expected and any(r["stratum"] != "random" for r in extra):
            raise Refuse("an extra line is not in the random stratum")
    labels: dict[str, Label] = {}
    for p in cfg.parser_labels:
        part = _labels(p, "parser labels")
        if labels.keys() & part.keys():
            raise Refuse(f"line ids repeat across label files: {p.name}")
        labels |= part
    if cfg.expected and (len(lines) - n_extra, n_random, n_extra) != (
        cfg.expected["test_lines"],
        cfg.expected["test_random"],
        cfg.expected["extra_lines"],
    ):
        raise Refuse(
            f"unexpected line counts: {len(lines) - n_extra} sheet ({n_random} random), "
            f"{n_extra} extra"
        )
    unlabelled = sorted(r["id"] for r in lines if r["id"] not in labels)
    if unlabelled:
        raise Refuse(f"{len(unlabelled)} lines have no label{_eg(unlabelled, cfg.strict)}")
    if any(r["stratum"] not in STRATA for r in lines):
        raise Refuse("a line has an unknown stratum")
    labels = {r["id"]: labels[r["id"]] for r in lines}
    pmap = None
    if cfg.parser_map is not None:
        pmap = read_map(cfg.parser_map, "parser id map")
        check_map(pmap, _gold_names(labels), ids, "parser id map", quiet=cfg.strict)

    # Typed inputs.
    assignment = _json(cfg.input_split, "input split")["assignment"]
    inputs = sorted(t for t, s in assignment.items() if s == cfg.split)
    if cfg.expected and len(inputs) != cfg.expected["test_inputs"]:
        raise Refuse(f"unexpected input count: {len(inputs)}")
    in_labels = _labels(cfg.input_labels, "input labels")
    no_label = [t for t in inputs if t not in in_labels]
    if no_label:
        raise Refuse(f"{len(no_label)} inputs have no label{_eg(no_label, cfg.strict)}")
    in_labels = {t: in_labels[t] for t in inputs}
    imap = None
    if cfg.input_map is not None:
        imap = read_map(cfg.input_map, "input id map")
        check_map(imap, _gold_names(in_labels), ids, "input id map", quiet=cfg.strict)

    # Pack counts, copied from the pack result.
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
        _problem(cfg, "the pack result was built from a dirty tree")
    for key, path in (("table_sha256", cfg.table_v2), ("words_sha256", cfg.words)):
        if pc.get(key) != _sha(path):
            _problem(cfg, f"pack result {key} does not match {path.name}: rebuild the pack result")

    # Score parser lines per stratum.
    parser = {s: score([r for r in lines if r["stratum"] == s], labels, t2, pmap) for s in STRATA}
    if parser["random"]["gold_groups"] == 0:
        raise Refuse("no gold groups in the random stratum: the D2 gate has no data")

    # Score typed inputs, M1 and M3, paired.
    keys = {" ".join(k): i for k, i in t2.keys.items()}

    resolve_m1 = m1_resolver(t1)  # the shipped M1 resolver: old tokens, one exact lookup

    def resolve_m3(text: str) -> list[str]:
        return list(resolve_name(text, keys, t2.words).ids)

    def one(resolve, text: str) -> int:  # both arms score against the one v2 table and map
        return score_inputs([text], in_labels, resolve, t2, imap)["correct"]

    f1, f3 = [one(resolve_m1, t) for t in inputs], [one(resolve_m3, t) for t in inputs]
    n_in = len(inputs)
    inp = (
        {
            "n": n_in,
            "m1": {
                "n": n_in,
                "correct": sum(f1),
                "input_accuracy": sum(f1) / n_in if n_in else 0.0,
            },
            "m3": {
                "n": n_in,
                "correct": sum(f3),
                "input_accuracy": sum(f3) / n_in if n_in else 0.0,
            },
            **paired(f1, f3),
        }
        if n_in
        else None
    )
    if inp is None:
        raise Refuse("no typed inputs in this split")

    # Metrics and targets.
    sp = cfg.split
    metrics = []
    for s in STRATA:
        p = parser[s]
        if p["gold_groups"]:
            metrics.append(
                _row("mention_accuracy", p["mention_correct"], p["gold_groups"], sp, {"stratum": s})
            )
            metrics.append(
                _row("parser_precision", p["pred_correct"], p["pred_groups"], sp, {"stratum": s})
            )
    m_men = next(
        m for m in metrics if m["name"] == "mention_accuracy" and m["group"]["stratum"] == "random"
    )
    m_pre = next(
        m for m in metrics if m["name"] == "parser_precision" and m["group"]["stratum"] == "random"
    )
    m_m1 = _row("input_accuracy", inp["m1"]["correct"], n_in, sp, {"resolver": "m1"})
    m_m3 = _row("input_accuracy", inp["m3"]["correct"], n_in, sp, {"resolver": "m3"})
    m_pack = _row("recipes_fully_read", fully, recipes, "all")
    metrics += [m_m1, m_m3, m_pack]
    targets = [
        _target("mention_accuracy_random", m_men, parser["random"]["mention_correct"]),
        _target("parser_precision_random", m_pre, parser["random"]["pred_correct"]),
        _target("input_accuracy_m3", m_m3, inp["m3"]["correct"]),
        _target("recipes_fully_read", m_pack, fully),
        {
            "name": "recipes", "metric": None, "value": recipes, "n": recipes, "k": None,
            "target": TARGETS["recipes"], "status": status(recipes, TARGETS["recipes"]),
            "wilson_lo": None, "wilson_hi": None,
        },
    ]  # fmt: skip
    failed = [t["name"] for t in targets if t["status"] != "PASS"]

    def rel(p: Path) -> str:
        p = Path(p).resolve()
        return (
            p.relative_to(root.resolve()).as_posix() if p.is_relative_to(root.resolve()) else str(p)
        )

    files = [cfg.sheet, cfg.extra, *cfg.parser_labels, cfg.parser_map, cfg.input_split]
    files += [cfg.input_labels, cfg.input_map, cfg.table_v1, cfg.table_v2, cfg.words]
    files += [cfg.pack_result]
    config = {
        "split": sp,
        "dry_run": not cfg.strict,
        "tables": {"v1_rows": len(t1.rows), "v2_rows": len(t2.rows)},
        "resolvers": {
            "m1": "shipped M1 resolver: one exact key lookup in the v1 table, old tokens "
            "canonicalize(fold(x)).split(), as resolve_names on main",
            "m3": "pantrychef.ingredients.names.resolve_name on the v2 table, current tokens",
        },
        "gold_to_id": "frozen blind id map (D9)" if cfg.strict else "dev id map / table keys",
        "ignored_untracked": list(IGNORED),
        "files_sha256": {rel(p): _sha(p) for p in files if p is not None},
        "parser": parser,
        "inputs": inp,
        "pack": {
            "recipes": recipes,
            "recipes_fully_read_count": fully,
            "recipes_fully_read": pack_frac,
            "core_bytes": pc.get("core_bytes"),
        },  # fmt: skip
        "targets": targets,
        "all_targets_met": not failed,
        "stop_and_report": bool(failed),
        "failed": failed,
    }
    write_result(
        cfg.out,
        {
            "label": "MEASURED",
            "what": "M3 acceptance. Parser lines (random stratum is the D2 gate; hard and rare "
            "are reported apart) and typed inputs (M1 against M3, paired), scored against the "
            "frozen blind id maps. Pack counts are copied from results/m3_pack_v2.json. "
            + ("" if cfg.strict else "DRY RUN on the dev halves: not an acceptance number."),
            "command": cfg.command,
            "config": config,
            "seed": SEED,
            "corpus_fingerprint": sheet["snapshot_sha256"],
            "arms": [],
            "metrics": metrics,
            "comparisons": [],
            "environment": {},
        },
        root,
    )
    for t in targets:
        print(f"{t['status']}  {t['name']}: {t['value']:.4g} (target {t['target']}, n {t['n']})")
    print(
        f"M1 {inp['m1']['correct']}/{n_in}, M3 {inp['m3']['correct']}/{n_in}, "
        f"McNemar p {inp['mcnemar_p']:.4g}, diff {inp['diff']:+.4f} "
        f"[{inp['bootstrap']['lo']:+.4f}, {inp['bootstrap']['hi']:+.4f}]"
    )
    print(f"wrote {cfg.out}")
    if failed:
        print(f"STOP AND REPORT: targets failed: {failed}. Do not lower a target or score again.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run-on", choices=["dev"], default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    if (args.dry_run_on is None) != (args.out is None):
        ap.error("--dry-run-on dev and --out go together; the real run takes neither")
    return run(real_config() if args.dry_run_on is None else dev_config(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
