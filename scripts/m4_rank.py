"""M4 search ranking (plan 2026-11-18, section 10). A thin CLI over ``pantrychef.eval.m4_run``.

    uv run python scripts/m4_rank.py pantries [--pack build/pack]
    uv run python scripts/m4_rank.py variants [--pack build/pack]
    uv run python scripts/m4_rank.py pilot-score [--name pilot] [--allow-model-judge]
    uv run python scripts/m4_rank.py dev-score [--name pilot dev] [--allow-model-judge]
    uv run python scripts/m4_rank.py train [--name pilot dev] [--allow-model-labels]
    uv run python scripts/m4_rank.py futility [--name futility] [--allow-model-judge]
    uv run python scripts/m4_rank.py freeze [--dry-run] [--n-test 100]
    uv run python scripts/m4_rank.py score [--name test]

``--root`` moves every input and output to another folder with the same layout (a dry run).
``--allow-uncommitted`` skips the commit-order check of dev, pilot and futility answers (dry runs
only). The result files then say ``commit_order_checked: false``.

After dev-score, train, futility and freeze the script prints only GO or STOP and the paths it
wrote. After pilot-score it prints the four protocol checks as PASS or FAIL and the overall
verdict. The numbers go to the results files. The owner stays blind until the test answers are
committed (plan 8.1). Exit code: 0 for GO or PASS, 3 for STOP or FAIL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from pantrychef.engine import load_pack
from pantrychef.eval import m4_run, results
from pantrychef.eval import pairwise as pw
from pantrychef.eval.arms import CandidateIndex
from pantrychef.eval.m4_lists import model_orderer, select_pantries
from pantrychef.eval.m4_pools import (
    VARIANTS,
    build_pools,
    canonical,
    check_no_leak,
    pack_core_sha256,
    pilot_exclusions,
    top5_agreement,
    usable_pantries,
)
from pantrychef.eval.pantries import _group_key
from pantrychef.rank import load_model
from scripts import judging_score as js
from scripts import judging_sheet as sheet

ROOT = Path(__file__).resolve().parent.parent
GO, STOP = 0, 3
PANTRIES = "data/eval/m4/pantries.v1.json"
SPIKE = "data/eval/graph_spike/pantries.v1.json"
WEIGHTS = "web/src/rank_model.v1.json"
TABLE = "data/eval/m4/train_table.v1.json"
PLAN_COPY = "data/eval/m4/analysis_plan.v1.md"
UI_DECISION = "data/eval/m4/ui_decision.v1.json"
PLAN = "docs/plans/2026-11-18-m4-search-ranking.md"  # section 6.1 is copied from here
DEV_PAIRS = "results/m4_dev_pairs.json"
CV = "results/m4_cv.json"
FUTILITY = "results/m4_futility.json"
ARM_MODEL = "results/m4_arm_rank_linear.json"
PILOT = "results/m4_timing_pilot.json"


def _key(root: Path, name: str) -> Path:
    return root / f"data/interim/judging_key.m4-{name}.v1.json"


def _key_sha(root: Path, name: str) -> Path:
    return root / f"data/eval/m4/key_sha256.{name}.txt"


def _answers(root: Path, name: str) -> Path:
    return root / f"data/eval/m4/answers.{name}.v1.csv"


def _need(path: Path, hint: str) -> Path:
    if not path.is_file():
        raise SystemExit(f"{path.name} is missing: {hint}")
    return path


def _verdict(go: bool, wrote: list[str]) -> int:
    """Print GO or STOP and the paths written, nothing else."""
    print("GO" if go else "STOP")
    for rel in wrote:
        print(f"wrote {rel}")
    return GO if go else STOP


def _write(root: Path, rel: str, doc: dict) -> str:
    results.write_result(root / rel, doc)  # git facts come from the repo, not from ``--root``
    return rel


def _command(args: argparse.Namespace) -> str:
    return "uv run python scripts/m4_rank.py " + " ".join(sys.argv[1:] or [args.command])


def _pantries(root: Path) -> dict:
    return json.loads(_need(root / PANTRIES, "run the draw first").read_text(encoding="utf-8"))


def _fingerprint(args: argparse.Namespace) -> str:
    """The one corpus fingerprint of every M4 result file: the pack's own."""
    return load_pack(args.pack).info.corpus_fingerprint


def _dev_pairs(root: Path, allow: bool, flag: str = "--allow-model-judge") -> dict:
    """The ``config`` of results/m4_dev_pairs.json (the comparator and the judge flag)."""
    path = _need(root / DEV_PAIRS, "run dev-score first")
    cfg = json.loads(path.read_text(encoding="utf-8"))["config"]
    if cfg.get("model_judged") and not allow:
        raise SystemExit(f"{path.name} is model-judged. Use {flag}.")
    return cfg


def _ordered(root: Path, name: str, args: argparse.Namespace) -> bool:
    """RI3: the key hash was committed before the answers. Return whether it was checked."""
    return m4_run.check_commit_order(
        root,
        _key_sha(root, name).relative_to(root).as_posix(),
        _answers(root, name).relative_to(root).as_posix(),
        args.allow_uncommitted,
    )


def _load_sheets(
    root: Path,
    names: list[str],
    doc: dict,
    args: argparse.Namespace,
    flag: str = "--allow-model-judge",
):
    """For each dev sheet: check the key hash, the flags, the pools and the commit order, then
    read the answers. Return the sheets, whether the answers are model-judged, and whether the
    commit order was checked.

    ``flag`` is the flag that lets model-judged answers through: ``--allow-model-judge`` for
    dev-score, ``--allow-model-labels`` for train (Amendment 2). All sheets must have the same
    label source: human pilot rows never mix with model rows in one table.
    """
    allow = getattr(args, flag.lstrip("-").replace("-", "_"))
    out, judged, checked, seen = [], False, True, set()
    for name in names:
        key_path = _need(_key(root, name), "build the sheet first")
        m4_run.check_key_hash(key_path, _key_sha(root, name))
        key = json.loads(key_path.read_text(encoding="utf-8"))
        m4_run.check_key_flags(key, name)
        m4_run.check_pool(key, doc, m4_run.DEV_POOLS, "dev")
        rows = m4_run.read_answers(_need(_answers(root, name), "no answers yet"))
        here = m4_run.check_judge(rows, allow, "dev", flag)
        seen.add(here)
        judged |= here
        checked &= _ordered(root, name, args)
        out.append((name, key, rows))
    if len(seen) > 1:
        raise SystemExit(
            "the sheets mix human and model-judged answers: use one label source. Stop."
        )
    return out, judged, checked


# ---------------------------------------------------------------- draw and variants


def cmd_pantries(args: argparse.Namespace) -> int:
    root = args.root
    pack = load_pack(args.pack)
    doc, stats = build_pools(pack, pack_core_sha256(args.pack), root / SPIKE)
    if stats["duplicates"]:  # RI9: refuse before any file is written
        raise SystemExit(f"the draw has pantries with the same content, nothing written: {stats}")
    out = root / "data/eval/m4"
    out.mkdir(parents=True, exist_ok=True)
    (out / "pantries.v1.json").write_bytes(canonical(doc))
    digest = hashlib.sha256(canonical(doc["pools"]["test"])).hexdigest()
    (out / "test_pantries_sha256.txt").write_text(digest + "\n", encoding="utf-8", newline="\n")
    print(f"{stats}\ntest pool sha256 {digest}", file=sys.stderr)
    return 0


def cmd_variants(args: argparse.Namespace) -> int:
    root = args.root
    pack = load_pack(args.pack)
    golds, groups = pilot_exclusions(root / SPIKE, pack)
    items = usable_pantries(pack, "dev", golds, groups)
    agree = top5_agreement(pack, items)
    metrics = [
        {
            "name": "top5_agreement",
            "arm": v,
            "split": "dev",
            "n": a["n"],
            "value": a[key],
            "group": {"measure": key, "versus": "shipped"},
        }
        for v, a in agree.items()
        for key in ("identical", "mean_shared")
    ]
    doc = {
        "label": "MEASURED",
        "what": "Top-5 agreement of six label-free IDF variants against shipped on all usable "
        "dev pantries (gold-out). identical = same ordered top 5. mean_shared = mean share of "
        "the 5 ids in common. No variant is judged or selected.",
        "command": "uv run python scripts/m4_rank.py variants",
        "config": {
            "gold_out": True,
            "sampler": "popularity",
            "d": 3,
            "draw": 0,
            "max_missing": 2,
            "pack_core_sha256": pack_core_sha256(args.pack),
            "usable_dev": len(items),
        },
        "seed": 42,
        "corpus_fingerprint": pack.info.corpus_fingerprint,
        "arms": [{"name": v, "features_used": list(results.ARMS[v])} for v in VARIANTS],
        "metrics": metrics,
        "comparisons": [],
    }
    results.write_result(root / "results/m4_idf_variants.json", doc)
    for v, a in agree.items():
        print(f"{v:18s} identical {a['identical']:.3f}  mean_shared {a['mean_shared']:.3f}")
    print(f"n = {len(items)}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------- pilot, dev-score and train


def cmd_pilot_score(args: argparse.Namespace) -> int:
    """Score the timing pilot. Print the four protocol checks and the verdict, no number."""
    root, name = args.root, (args.name or ["pilot"])[0]
    doc = _pantries(root)
    key_path = _need(_key(root, name), "build the pilot sheet first")
    m4_run.check_key_hash(key_path, _key_sha(root, name))
    key = json.loads(key_path.read_text(encoding="utf-8"))
    m4_run.check_key_flags(key, name)
    m4_run.check_pool(key, doc, ("pilot", "reserve"), "pilot")
    rows = m4_run.read_answers(_need(_answers(root, name), "no answers yet"))
    judged = m4_run.check_judge(rows, args.allow_model_judge, "pilot")
    checked = _ordered(root, name, args)
    scored = js.score(key, rows)
    checks = m4_run.pilot_checks(scored, judged)
    out = m4_run.pilot_doc(
        key,
        scored,
        checks,
        pack_sha=doc["pack_core_sha256"],
        corpus_fingerprint=_fingerprint(args),
        model_judged=judged,
        command=_command(args),
        commit_order_checked=checked,
    )
    _write(root, PILOT, out)
    word = {True: "PASS", False: "FAIL"}
    print(f"check 1 self-consistency: {word[checks['check1_self_consistency']]}")
    print(f"check 2 discrimination: {word[checks['check2_discrimination']]}")
    print(f"check 3 cost: {word[checks['check3_cost']]}")
    print(f"check 4 power: {word[checks['check4_power']]}")
    print(f"pilot: {word[checks['overall']]}")
    return GO if checks["overall"] else STOP


def cmd_dev_score(args: argparse.Namespace) -> int:
    root, names = args.root, args.name or ["dev"]
    doc = _pantries(root)
    sheets, judged, checked = _load_sheets(root, names, doc, args)
    merged = m4_run.merge_scored([js.score(key, rows) for _, key, rows in sheets])
    docs = m4_run.dev_docs(
        merged,
        m4_run.choose_rule(merged["pairs"], model_judged=judged),
        names=names,
        pack_sha=doc["pack_core_sha256"],
        corpus_fingerprint=_fingerprint(args),
        model_judged=judged,
        command=_command(args),
        commit_order_checked=checked,
        gold_out=all(k["gold_out"] for _, k, _ in sheets),  # from the keys, not assumed
        neutral_order=all(k["neutral_order"] for _, k, _ in sheets),
    )
    return _verdict(True, [_write(root, f"results/{stem}.json", d) for stem, d in docs.items()])


def cmd_train(args: argparse.Namespace) -> int:
    root, names = args.root, args.name or ["dev"]
    doc = _pantries(root)
    pairs = _dev_pairs(root, args.allow_model_labels, "--allow-model-labels")
    comparator = pairs["comparator"]
    sheet.check_pack_hash(Path(args.pack), doc["pack_core_sha256"])
    pack = load_pack(args.pack)
    sheets, judged, checked = _load_sheets(root, names, doc, args, "--allow-model-labels")
    labels = "model_judged" if judged else "human"
    if judged != pairs["model_judged"]:
        raise SystemExit("the answers and results/m4_dev_pairs.json disagree on the judge. Stop.")
    items = m4_run.training_items(pack, doc, sheets)
    bad = check_no_leak(
        doc,
        [{"pantry_id": i.pantry_id} for i in items],
        {"pantries_sha256": pw.pantries_sha256(i.pantry_id for i in items)},
        set(doc.get("excluded", {}).get("gold_ids", [])),
    )
    if bad:
        raise SystemExit("leak check failed, nothing written: " + "; ".join(bad))
    out = pw.run_train(
        items,
        weights_path=root / WEIGHTS,
        table_path=root / TABLE,
        comparator=comparator,
        commit=results.git_facts(ROOT)[0],
        training_labels=labels,
    )
    wrote = [TABLE]
    if out["weights_written"]:  # the weights name the table: check the bytes on disk (RF6c)
        trained_on = json.loads((root / WEIGHTS).read_text(encoding="utf-8"))["trained_on"]
        bad = check_no_leak(
            doc,
            [{"pantry_id": i.pantry_id} for i in items],
            trained_on,
            set(doc.get("excluded", {}).get("gold_ids", [])),
            table_sha256=m4_run.sha256_file(root / TABLE),
        )
        if bad:
            (root / WEIGHTS).unlink()
            raise SystemExit("leak check failed after training, weights removed: " + "; ".join(bad))
    pack_sha, cmd, fp = doc["pack_core_sha256"], _command(args), _fingerprint(args)
    cv = m4_run.cv_doc(
        out,
        pack_sha=pack_sha,
        corpus_fingerprint=fp,
        comparator=comparator,
        command=cmd,
        n_items=len(items),
        commit_order_checked=checked,
        model_judged=judged,
        training_labels=labels,
    )
    wrote.append(_write(root, CV, cv))
    if out["weights_written"]:
        wrote.append(WEIGHTS)
        weights = json.loads((root / WEIGHTS).read_text(encoding="utf-8"))
        arm = {
            "label": "HYPOTHESIS",
            "what": ("Dry run, model-judged. " if judged else "")
            + "The linear ranking model rank_linear: its configuration. It has no "
            "judgments yet. The futility check and the test come later.",
            "command": cmd,
            "config": {
                "features": weights["features"],
                "feature_set": weights["feature_set"],
                "C": weights["C"],
                "comparator": comparator,
                "weights_sha256": m4_run.sha256_file(root / WEIGHTS),
                "trained_on": weights["trained_on"],
                "pack_core_sha256": pack_sha,
                "model_judged": judged,
                "training_labels": labels,
                "commit_order_checked": checked,
            },
            "seed": 42,
            "corpus_fingerprint": fp,
            "arms": [{"name": "rank_linear"}],
            "metrics": [],
            "comparisons": [],
            "environment": {},
        }
        wrote.append(_write(root, ARM_MODEL, arm))
    else:  # RI1: check 1 failed, so an older weights file and its arm file are stale: remove them
        for rel in (WEIGHTS, ARM_MODEL):
            (root / rel).unlink(missing_ok=True)
    return _verdict(out["weights_written"], wrote)


# ---------------------------------------------------------------- futility


def cmd_futility(args: argparse.Namespace) -> int:
    root = args.root
    name = (args.name or ["futility"])[0]
    doc = _pantries(root)
    weights = _need(root / WEIGHTS, "run train first")
    weights_doc = json.loads(weights.read_text(encoding="utf-8"))
    labelled = weights_doc.get("trained_on", {}).get("training_labels") == "model_judged"
    comparator = _dev_pairs(root, args.allow_model_judge or labelled)["comparator"]
    if weights_doc.get("comparator") != comparator:
        raise SystemExit("the weights and results/m4_dev_pairs.json name different comparators.")
    key_path = _need(_key(root, name), "build the futility sheet first")
    m4_run.check_key_hash(key_path, _key_sha(root, name))
    key = json.loads(key_path.read_text(encoding="utf-8"))
    m4_run.check_key_flags(key, name)
    m4_run.check_pool(key, doc, ("futility",), "futility")
    if key.get("model_sha256") != m4_run.sha256_file(weights):
        raise SystemExit("the weights changed after the futility sheet was built. Stop.")
    arms = {a for k in key["items"].values() for a in (k["left"], k["right"])}
    if arms != {"rank_linear", comparator}:
        raise SystemExit(f"the futility sheet must compare rank_linear with {comparator}")
    rows = m4_run.read_answers(_need(_answers(root, name), "no answers yet"))
    if root.resolve() == ROOT.resolve() and m4_run.is_model_judged(rows):
        raise SystemExit(
            "model-judged futility answers are refused on the repo root: the futility check "
            "stays human (Amendment 2). Stop."
        )
    judged = m4_run.check_judge(rows, args.allow_model_judge, "futility")
    checked = _ordered(root, name, args)
    scored = js.score(key, rows, model_arm="rank_linear")
    p = scored["primary"]
    verdict = m4_run.futility_verdict(p["W"], p["L"])
    out = js.result_doc(
        key, scored, _command(args), split="futility", corpus_fingerprint=_fingerprint(args)
    )
    out["what"] = (
        "Futility check 2 (plan 7.5): the model against the IDF rule on the 20 dev spares. "
        "It can stop the test. It never proves a gain and never changes the weights."
    )
    out["config"]["futility"] = {**verdict, "T": p["T"], "n": p["n"], "comparator": comparator}
    out["config"]["model_judged"] = judged
    out["config"]["commit_order_checked"] = checked
    out["config"]["weights_sha256"] = m4_run.sha256_file(weights)
    if judged:
        out["what"] = "Dry run, model-judged. " + out["what"]
        out["metrics"] = [
            {**m, "name": "pilot_pairwise_win_rate"} if m["name"] == "pairwise_win_rate" else m
            for m in out["metrics"]
            if m["name"] != "would_cook_rate"
        ]
        for c in out["comparisons"]:
            c["metric"] = "pilot_pairwise_win_rate"
    wrote = [_write(root, FUTILITY, out)]
    return _verdict(not verdict["stop"], wrote)


# ---------------------------------------------------------------- freeze and score


def _pack_core(args: argparse.Namespace) -> Path:
    return Path(args.pack) / "core.v2.json.gz"


def _freeze_problems(args: argparse.Namespace, kw: dict) -> list[str]:
    root = args.root
    problems = pw.freeze_blockers(root, **kw)
    gates = m4_run.freeze_gates(
        root,
        ui_rel=UI_DECISION,
        weights_rel=WEIGHTS,
        table_rel=TABLE,
        dev_pairs_rel=DEV_PAIRS,
        cv_rel=CV,
        futility_rel=FUTILITY,
    )
    problems += gates
    if not gates:  # the weights and the table are valid JSON now, so the leak check can read them
        doc = _pantries(root)
        table = json.loads((root / TABLE).read_text(encoding="utf-8"))
        trained_on = json.loads((root / WEIGHTS).read_text(encoding="utf-8"))["trained_on"]
        problems += check_no_leak(
            doc,
            table["rows"],
            trained_on,
            set(doc.get("excluded", {}).get("gold_ids", [])),
            table_sha256=m4_run.sha256_file(root / TABLE),
        )
    return problems


def cmd_freeze(args: argparse.Namespace) -> int:
    root = args.root
    doc = _pantries(root)
    kw = {
        "pack_core": _pack_core(args),
        "pinned_pack_sha256": doc["pack_core_sha256"],
        "generated": (PLAN_COPY,),
    }
    problems = _freeze_problems(args, kw)
    if args.dry_run:
        print(f"would freeze {len(pw.FREEZE_FILES)} files:")
        for rel in pw.FREEZE_FILES:
            print(f"  {rel}" + (" (written by freeze)" if rel == PLAN_COPY else ""))
        for p in problems:
            print(f"blocker: {p}")
        print("GO" if not problems else "STOP")
        return GO if not problems else STOP
    if problems:
        raise SystemExit("freeze refused: " + "; ".join(problems))
    text = m4_run.section_6_1(_need(root / PLAN, "the plan file").read_text(encoding="utf-8"))
    (root / PLAN_COPY).write_bytes(text.encode("utf-8"))
    freeze = pw.build_freeze(
        root,
        comparator=_dev_pairs(root, True)["comparator"],  # the gates checked the label chain
        n_test=args.n_test,
        seed=42,
        extra=m4_run.freeze_facts(root, weights_rel=WEIGHTS, dev_pairs_rel=DEV_PAIRS),
        **kw,
    )
    pw.write_freeze(root / pw.FREEZE_REL, freeze)
    return _verdict(True, [PLAN_COPY, pw.FREEZE_REL])


def _selection_problems(root: Path, args: argparse.Namespace, key: dict, freeze: dict) -> list[str]:
    """RF7: rebuild the test selection from the frozen inputs and compare it with the key."""
    pack = load_pack(args.pack)
    doc = _pantries(root)
    arms = ("rank_linear", freeze["comparator"])
    index = CandidateIndex(pack, set(pack.default_staples))
    group_of = {r.recipe_id: _group_key(r) for r in pack.recipes}
    orderers = {"rank_linear": model_orderer(pack, load_model(root / WEIGHTS))}
    base, skipped, _ = select_pantries(
        index, group_of, doc["pools"]["test"], arms, orderers,
        take=freeze["n_test"], skip_identical=True,
    )  # fmt: skip
    want = [r["pantry_id"] for r in base]
    got = {k["pantry_id"] for k in key["items"].values() if not k.get("probe")}
    problems = []
    if set(want) != got:
        problems.append("the key does not hold the frozen selection of test pantries")
    if key.get("skipped") != skipped:
        problems.append("the key's skipped pantries differ from the frozen selection")
    if key.get("pool") != "test" or key.get("pack_core_sha256") != freeze["pack_core_sha256"]:
        problems.append("the key is not a test key of the frozen pack")
    for flag in ("neutral_order", "gold_out"):
        if key.get(flag) is not True:
            problems.append(f"the key does not use {flag.replace('_', ' ')}")
    return problems


def cmd_score(args: argparse.Namespace) -> int:
    root, name = args.root, (args.name or ["test"])[0]
    key_path, answers = _key(root, name), _answers(root, name)
    freeze_path = root / pw.FREEZE_REL
    problems = pw.check_freeze(
        root,
        pack_core=_pack_core(args),
        key_path=key_path,
        key_hash_rel=_key_sha(root, name).relative_to(root).as_posix(),
        answers_rel=answers.relative_to(root).as_posix(),
    )
    freeze = json.loads(freeze_path.read_text(encoding="utf-8")) if freeze_path.is_file() else None
    key = json.loads(key_path.read_text(encoding="utf-8")) if key_path.is_file() else None
    rows = m4_run.read_answers(answers) if answers.is_file() else None
    if freeze and key and rows is not None:
        base = [k for k in key["items"].values() if not k["repeat_of"] and not k.get("probe")]
        want = {"rank_linear", freeze["comparator"]}
        if key.get("model_sha256") != freeze["files"].get(WEIGHTS):
            problems.append("the key was built with other weights than the frozen ones")
        if {a for k in base for a in (k["left"], k["right"])} != want:
            problems.append(f"the test sheet must compare rank_linear with {freeze['comparator']}")
        if len(base) != freeze["n_test"]:
            problems.append(f"the key has {len(base)} items, the freeze says {freeze['n_test']}")
        if rows and "arm_guess" not in rows[0]:
            problems.append("the answers have no arm_guess column")
        if not problems:  # the selection needs the frozen weights and pool to be sound
            problems += _selection_problems(root, args, key, freeze)
    if problems:
        print("STOP")
        for p in problems:
            print(f"refused: {p}")
        return STOP
    m4_run.check_judge(rows, False, "test")
    scored = js.score(key, rows, model_arm="rank_linear")
    dev = args.dev_name
    if _key(root, dev).is_file() and _answers(root, dev).is_file():
        scored["probe_agreement"] = js.probe_agreement(
            key,
            rows,
            json.loads(_key(root, dev).read_text(encoding="utf-8")),
            m4_run.read_answers(_answers(root, dev)),
        )
    out = js.result_doc(
        key, scored, _command(args), split="test", corpus_fingerprint=_fingerprint(args)
    )
    out["config"]["freeze_commit"] = results.commits(root, pw.FREEZE_REL)[0]
    out["config"]["comparator"] = freeze["comparator"]
    rel = _write(root, "results/m4_test.json", out)
    return _verdict(scored["primary"]["cp_lo_above_half"], [rel])


COMMANDS = {
    "pantries": cmd_pantries,
    "variants": cmd_variants,
    "pilot-score": cmd_pilot_score,
    "dev-score": cmd_dev_score,
    "train": cmd_train,
    "futility": cmd_futility,
    "freeze": cmd_freeze,
    "score": cmd_score,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("--pack", default="build/pack")
    ap.add_argument("--root", help="folder with the repo layout for inputs and outputs (dry runs)")
    ap.add_argument("--name", nargs="+", help="sheet name(s); default pilot, dev, futility or test")
    ap.add_argument("--dev-name", default="dev", help="score: the dev sheet for the drift probes")
    ap.add_argument("--allow-model-judge", action="store_true", help="dry runs only")
    ap.add_argument(
        "--allow-model-labels",
        action="store_true",
        help="train: use model-judged dev answers as labels (Amendment 2). Not the dry-run flag",
    )
    ap.add_argument(
        "--allow-uncommitted",
        action="store_true",
        help="dry runs only: skip the commit-order check of pilot, dev and futility answers",
    )
    ap.add_argument("--dry-run", action="store_true", help="freeze: print, write nothing")
    ap.add_argument("--n-test", type=int, default=100, help="freeze: test pantries")
    args = ap.parse_args(argv)
    args.root = Path(args.root) if args.root else ROOT
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
