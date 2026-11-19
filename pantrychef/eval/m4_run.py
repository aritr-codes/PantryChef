"""M4 wiring library (plan section 10): scoring dev answers, the IDF-rule choice, training items,
the futility rule, the analysis-plan copy and the results documents.

``scripts/m4_rank.py`` is a thin CLI over these functions. Nothing here prints numbers: the owner
stays blind until the test answers are committed (plan 8.1), so the CLI writes numbers to results
files and prints only GO or STOP.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections.abc import Iterable, Sequence
from pathlib import Path

from pantrychef.engine import Pack
from pantrychef.eval import pairwise as pw
from pantrychef.eval import results
from pantrychef.eval.arms import CandidateIndex
from pantrychef.eval.m4_lists import excluded_ids, feature_map, top_lists
from pantrychef.eval.pantries import _group_key
from pantrychef.eval.stats import clopper_pearson, sign_test

JUDGE_MODEL = "judge_model"
SOURCE_HUMAN = "dev_judgments"  # the plan 4.3 rule chose the comparator from hand judgments
SOURCE_MODEL = "default (dev answers are model-judged)"  # Amendment 2: shipped, not chosen
DEV_POOLS = ("pilot", "dev", "reserve")  # pools whose pantries may be judged for dev
DEV_ARMS = ("overlap", "shipped", "idf_flat")
LEVEL = 0.95
CI_METHOD = "clopper-pearson-exact"


# ---------------------------------------------------------------- reading and guards


def read_answers(path: str | Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def is_model_judged(rows: Iterable[dict]) -> bool:
    return any((r.get("judge") or "").strip() == JUDGE_MODEL for r in rows)


def check_judge(
    rows: Sequence[dict], allow: bool, stage: str, flag: str = "--allow-model-judge"
) -> bool:
    """Refuse model-judge rows (``judge`` column = ``judge_model``). Return True when allowed.

    Model answers never enter the test, whatever the flag says. For dev and futility the flag
    ``--allow-model-judge`` lets a dry run through, and the result files say so. ``train`` passes
    ``--allow-model-labels`` instead (Amendment 2): the dry-run flag does not let it train.
    """
    if not is_model_judged(rows):
        return False
    if stage == "test":
        raise SystemExit("model-judge answers never enter the test. Stop.")
    if not allow:
        raise SystemExit(
            f"the {stage} answers are model-judged. Use {flag} "
            + (
                "to train on model labels (Amendment 2)."
                if "labels" in flag
                else "for a dry run only."
            )
        )
    return True


def check_key_hash(key_path: Path, sha_path: Path) -> None:
    """The key on disk must hash to the value committed before judging."""
    if not sha_path.is_file():
        raise SystemExit(f"{sha_path.name} is missing: the key hash must exist before judging")
    if sha256_file(key_path) != sha_path.read_text(encoding="utf-8").strip():
        raise SystemExit(f"the key {key_path.name} differs from its hash {sha_path.name}. Stop.")


def pool_pantry_ids(doc: dict, pools: Sequence[str]) -> set[str]:
    return {r["pantry_id"] for p in pools for r in doc["pools"][p]}


def check_pool(key: dict, doc: dict, pools: Sequence[str], label: str) -> None:
    allowed = pool_pantry_ids(doc, pools)
    bad = sorted({k["pantry_id"] for k in key["items"].values()} - allowed)
    if bad:
        raise SystemExit(f"{len(bad)} pantries of the key are not in the {label} pool: {bad[:3]}")


def check_commit_order(root: Path, key_hash_rel: str, answers_rel: str, allow: bool) -> bool:
    """The key hash is committed before the answers (plan 8.1). Return whether it was checked.

    ``allow`` (``--allow-uncommitted``) skips the check for a dry run. The result files then say
    ``commit_order_checked: false``.
    """
    if allow:
        return False
    problems = pw.key_order_problems(root, key_hash_rel=key_hash_rel, answers_rel=answers_rel)
    if problems:
        raise SystemExit("commit order: " + "; ".join(problems) + ". Stop.")
    return True


def check_key_flags(key: dict, label: str) -> None:
    """An M4 key records neutral order and gold-out as true. Refuse a key that does not."""
    for flag, word in (("neutral_order", "neutral order"), ("gold_out", "gold-out")):
        if key.get(flag) is not True:
            raise SystemExit(f"the {label} key does not use {word} ({flag} is not true). Stop.")


# ---------------------------------------------------------------- pair statistics


def pair_stats(a: str, b: str, aw: int, bw: int, ties: int) -> dict:
    """W, L, T of arm ``a`` against arm ``b`` with net preference, CP interval and exact p."""
    d, n = aw + bw, aw + bw + ties
    return {
        "a": a,
        "b": b,
        "a_wins": aw,
        "b_wins": bw,
        "ties": ties,
        "n": n,
        "win_rate_a": aw / d if d else None,
        "net_preference": (aw - bw) / n if n else None,
        "win_rate_ties_as_half": (aw + 0.5 * ties) / n if n else None,
        "cp": list(clopper_pearson(aw, d)) if d else None,
        "p_exact": sign_test(aw, d),
    }


def merge_scored(scored: Sequence[dict]) -> dict:
    """Add up the outputs of ``judging_score.score`` of several sheets (pilot and dev, D7).

    Returns ``pairs`` (pair name to ``pair_stats``), ``would_cook`` (arm to ``[rate, n]``) and
    ``n_base``.
    """
    counts: dict[str, list] = {}
    cook: dict[str, list[float]] = {}
    for sc in scored:
        for name, p in sc["pairs"].items():
            c = counts.setdefault(name, [p["a"], p["b"], 0, 0, 0])
            c[2] += p["a_wins"]
            c[3] += p["b_wins"]
            c[4] += p["ties"]
            for arm in (p["a"], p["b"]):
                if arm in sc["would_cook"]:
                    cook.setdefault(arm, [0.0, 0])
                    cook[arm][0] += sc["would_cook"][arm] * p["n"]
                    cook[arm][1] += p["n"]
    return {
        "pairs": {name: pair_stats(*c) for name, c in counts.items()},
        "would_cook": {a: [y / n, n] for a, (y, n) in cook.items() if n},
        "n_base": sum(sc["n_base"] for sc in scored),
    }


def _wl(pairs: dict, x: str, y: str) -> tuple[int, int, int]:
    """Wins of x, wins of y, ties for the pair of x and y, whichever way the pair is named."""
    if (p := pairs.get(f"{x}_vs_{y}")) is not None:
        return p["a_wins"], p["b_wins"], p["ties"]
    if (p := pairs.get(f"{y}_vs_{x}")) is not None:
        return p["b_wins"], p["a_wins"], p["ties"]
    return 0, 0, 0


def _lower(w: int, lose: int) -> float:
    return clopper_pearson(w, w + lose)[0] if w + lose else 0.0


def _wlt(w: int, lose: int, t: int) -> dict:
    d = w + lose
    return {
        "W": w,
        "L": lose,
        "T": t,
        "cp": list(clopper_pearson(w, d)) if d else None,
        "cp_lo": _lower(w, lose),
    }


def choose_rule(pairs: dict, model_judged: bool = False) -> dict:
    """The pre-registered IDF-rule choice (plan 4.3). Ties drop out of W and L.

    Model-judged answers cannot choose the rule (Amendment 2): the rule is then ``shipped``, the
    counts are still reported and ``source`` says why.

    ``idf_flat`` is the rule only when the CP 95% lower bound of ``W / (W + L)`` of ``idf_flat``
    against ``shipped`` is above 0.5. Otherwise it is ``shipped``. If ``overlap`` beats the
    chosen rule by the same test, the result records it. The rule does not change (ADR 0005).
    """
    results.assert_selectable("pairwise_win_rate", ["idf_flat", "shipped", "overlap"])
    w, lose, t = _wl(pairs, "idf_flat", "shipped")
    rule = "idf_flat" if _lower(w, lose) > 0.5 and not model_judged else "shipped"
    ow, ol, ot = _wl(pairs, "overlap", rule)
    return {
        "rule": rule,
        "source": SOURCE_MODEL if model_judged else SOURCE_HUMAN,
        "idf_flat_vs_shipped": _wlt(w, lose, t),
        "overlap_vs_rule": {"rule": rule, **_wlt(ow, ol, ot)},
        "overlap_beats_rule": _lower(ow, ol) > 0.5,
    }


def futility_verdict(w: int, lose: int) -> dict:
    """Plan 7.5, check 2: stop when the model wins no more than the rule (``W <= L``)."""
    return {"W": w, "L": lose, "stop": w <= lose, "rule": "stop when W <= L"}


# ---------------------------------------------------------------- results documents


def _ci(lo: float, hi: float, n: int) -> dict:
    return {"lo": lo, "hi": hi, "level": LEVEL, "method": CI_METHOD, "n_clusters": n}


def dev_docs(
    merged: dict,
    rule: dict,
    *,
    names: Sequence[str],
    pack_sha: str,
    corpus_fingerprint: str,
    model_judged: bool,
    command: str,
    commit_order_checked: bool,
    gold_out: bool = True,
    neutral_order: bool = True,
) -> dict[str, dict]:
    """Results documents for ``dev-score``: ``m4_dev_pairs`` and one per judged arm.

    ``model_judged`` (a dry run) switches the metric to ``pilot_pairwise_win_rate`` (role sanity)
    and drops would-cook, so nothing in the file can select.
    """
    win = "pilot_pairwise_win_rate" if model_judged else "pairwise_win_rate"
    who = "model-judged (dry run, never selects)" if model_judged else "one person"
    config = {
        "sheets": list(names),
        "gold_out": gold_out,
        "neutral_order": neutral_order,
        "commit_order_checked": commit_order_checked,
        "sampler": "popularity",
        "d": 3,
        "max_missing": 2,
        "pack_core_sha256": pack_sha,
        "model_judged": model_judged,
        "judge": who,
        "pairs": merged["pairs"],
        "comparator": rule["rule"],
        "comparator_source": rule["source"],
        "idf_rule_selection": rule["idf_flat_vs_shipped"],
        "overlap_vs_rule": rule["overlap_vs_rule"],
        "overlap_beats_rule": rule["overlap_beats_rule"],
        "rule": "plan 4.3: idf_flat only if the CP 95% lower bound of W/(W+L) beats 0.5",
    }
    base = {
        "label": "MEASURED",
        "command": command,
        "seed": 42,
        "corpus_fingerprint": corpus_fingerprint,
        "environment": {},
    }

    def metric(arm: str, other: str, w: int, lose: int, t: int) -> dict | None:
        d = w + lose
        if not d:
            return None
        lo, hi = clopper_pearson(w, d)
        return {
            "name": win,
            "arm": arm,
            "split": "dev",
            "n": d,
            "value": w / d,
            "ci": _ci(lo, hi, d),
            "group": {"versus": other, "ties": t},
        }

    pair_metrics, comparisons = [], []
    for p in merged["pairs"].values():
        m = metric(p["a"], p["b"], p["a_wins"], p["b_wins"], p["ties"])
        if m:
            pair_metrics.append(m)
            comparisons.append(
                {
                    "metric": win,
                    "a": p["a"],
                    "b": p["b"],
                    "split": "dev",
                    "diff": m["value"] - 0.5,
                    "ci": _ci(m["ci"]["lo"] - 0.5, m["ci"]["hi"] - 0.5, m["n"]),
                }
            )
    docs = {
        "m4_dev_pairs": {
            **base,
            "what": f"Dev pairs, {who}: win counts of the three systems on the dev pantries "
            f"(sheets {', '.join(names)}), and the IDF-rule choice of plan 4.3.",
            "config": config,
            "arms": [{"name": a} for a in DEV_ARMS],
            "metrics": pair_metrics,
            "comparisons": comparisons,
        }
    }
    for arm in DEV_ARMS:
        metrics = []
        for p in merged["pairs"].values():
            if arm == p["a"]:
                m = metric(arm, p["b"], p["a_wins"], p["b_wins"], p["ties"])
            elif arm == p["b"]:
                m = metric(arm, p["a"], p["b_wins"], p["a_wins"], p["ties"])
            else:
                continue
            if m:
                metrics.append(m)
        if arm in merged["would_cook"] and not model_judged:
            rate, n = merged["would_cook"][arm]
            metrics.append(
                {"name": "would_cook_rate", "arm": arm, "split": "dev", "n": n, "value": rate}
            )
        docs[f"m4_arm_{arm}"] = {
            **base,
            "what": f"Arm {arm} on dev, {who}: win rate against each other system, ties out.",
            "config": {
                k: v
                for k, v in config.items()
                if k
                not in (
                    "pairs",
                    "idf_rule_selection",
                    "overlap_vs_rule",
                    "overlap_beats_rule",
                    "comparator",
                    "comparator_source",
                    "rule",
                )
            },  # fmt: skip
            "arms": [{"name": arm}],
            "metrics": metrics,
            "comparisons": [],
        }
    return docs


def train_what_prefix(model_judged: bool, training_labels: str) -> str:
    """Opening words of ``what`` for a training result. Real model labels are not a dry run."""
    if training_labels == "model_judged":
        return (
            "Model-labelled training (Amendment 2): labels are model-judged; "
            "the human futility check and test decide. "
        )
    return "Dry run, model-judged. " if model_judged else ""


def cv_doc(
    out: dict,
    *,
    pack_sha: str,
    corpus_fingerprint: str,
    comparator: str,
    command: str,
    n_items: int,
    commit_order_checked: bool,
    model_judged: bool = False,
    training_labels: str = "human",
) -> dict:
    """``results/m4_cv.json`` (plan 7.4). ESTIMATE: held-out log-loss of the whole procedure."""
    results.assert_selectable("cv_pairwise_logloss", ["rank_linear"])
    cv = out["cv"]
    n = cv["n_decided"]
    group = {
        "measure": "nested_cv_outer",
        "f1_logloss": cv["f1_logloss"],
        "f1_accuracy": cv["f1_accuracy"],
        "chance_logloss": cv["chance_logloss"],
    }
    return {
        "label": "ESTIMATE",
        "what": train_what_prefix(model_judged, training_labels)
        + "Nested grouped cross-validation on dev: held-out log-loss and accuracy of the "
        "whole procedure (feature set and C chosen inside each fold, one-SE rule). It is not a "
        "test result.",
        "command": command,
        "config": {
            "check1": out["check1"],
            "choice": out["choice"],
            "cv": cv,
            "comparator": comparator,
            "pack_core_sha256": pack_sha,
            "n_items": n_items,
            "model_judged": model_judged,
            "commit_order_checked": commit_order_checked,
            "training_labels": training_labels,
            "weights_written": out["weights_written"],
            "train_table_sha256": out["train_table_sha256"],
        },
        "seed": 42,
        "corpus_fingerprint": corpus_fingerprint,
        "arms": [{"name": "rank_linear"}],
        "metrics": [
            {
                "name": "cv_pairwise_logloss",
                "arm": "rank_linear",
                "split": "dev",
                "n": n,
                "value": cv["outer_logloss"],
                "group": group,
            },
            {
                "name": "cv_pairwise_accuracy",
                "arm": "rank_linear",
                "split": "dev",
                "n": n,
                "value": cv["outer_accuracy"],
                "group": group,
            },
        ],  # fmt: skip
        "comparisons": [],
        "environment": {},
    }


# ---------------------------------------------------------------- training items


def training_items(
    pack: Pack, doc: dict, sheets: Sequence[tuple[str, dict, Sequence[dict]]]
) -> list[pw.PairItem]:
    """One ``PairItem`` per first showing of a dev item. ``sheets`` are ``(name, key, rows)``.

    A list is built exactly as for the sheet: the shared candidate set, gold-out when the key
    says so, the arm's top 5 (``m4_lists.top_lists``). Ties give ``y = None``. Repeats and
    probes are not items.
    """
    index = CandidateIndex(pack, set(pack.default_staples))
    group_of = {r.recipe_id: _group_key(r) for r in pack.recipes}
    pools = {r["pantry_id"]: r for rows in doc["pools"].values() for r in rows}
    cache: dict[str, dict] = {}
    items = []
    for name, key, rows in sheets:
        said = {r["item_id"]: r["choice"].strip() for r in rows}
        for iid, k in key["items"].items():
            if k["repeat_of"] or k.get("probe"):
                continue
            if iid not in said:
                raise SystemExit(f"no answer for {iid} in sheet {name}")
            rec = pools[k["pantry_id"]]
            gone = excluded_ids(group_of, rec["gold_id"], rec["title_group"])
            tops = top_lists(
                index,
                (k["left"], k["right"]),
                rec["pantry"],
                gone if key["gold_out"] else set(),
                {},
            )
            fm = cache.setdefault(rec["pantry_id"], feature_map(pack, rec["pantry"]))
            vec = {a: [fm[c.recipe_id] for c in t] for a, t in tops.items()}
            outcome = {"A": "A", "B": "B", "tie": "tie"}[said[iid]]
            items.append(
                pw.make_item(
                    k["pantry_id"],
                    f"{name}:{iid}",
                    k["left"],
                    k["right"],
                    vec[k["left"]],
                    vec[k["right"]],
                    outcome,
                )  # fmt: skip
            )
    return items


# ---------------------------------------------------------------- the analysis plan


def section_6_1(text: str) -> str:
    """Section 6.1 of the plan, for ``analysis_plan.v1.md``.

    The first fenced block of the section when it has one, else the section verbatim (from its
    heading to the next heading). LF line ends, one trailing newline.
    """
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(r"#{2,4} 6\.1\b", ln)), None)
    if start is None:
        raise SystemExit("the plan has no section 6.1")
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"#{1,4} ", lines[i])), len(lines)
    )
    block = lines[start:end]
    fences = [i for i, ln in enumerate(block) if ln.startswith("```")]
    if len(fences) >= 2:
        block = block[fences[0] + 1 : fences[1]]
    while block and not block[-1].strip():
        block.pop()
    return "\n".join(block) + "\n"


# ---------------------------------------------------------------- the timing pilot (protocol)


def pilot_checks(scored: dict, model_judged: bool) -> dict:
    """The four protocol checks of the timing pilot (``docs/JUDGING_PROTOCOL.md``).

    1 self-consistency: at least 3 of 4 repeats give the same outcome (a quarter of any other
    number of repeats may differ). 2 discrimination: tie rate at most 0.6. 3 cost: median time
    under 90 s. A model cannot time itself, so a model-judged pilot fails check 3. 4 power: the
    exact power table for the observed tie rate exists (``config.analysis.power`` of the file).
    """
    reps, same = scored["repeats_total"], scored["repeats_same"]
    secs = scored["median_seconds"]
    checks = {
        "check1_self_consistency": reps > 0 and same >= math.ceil(0.75 * reps),
        "check2_discrimination": scored["tie_rate"] <= 0.6,
        "check3_cost": (not model_judged) and secs is not None and secs < 90,
        "check4_power": bool(scored["power"]),
    }
    checks["overall"] = all(checks.values())
    return checks


# The only parts of the scored pilot that go to the file the owner may open. Everything else
# (pairs, would-cook, strength, probes, sessions) names an arm or counts a win, and the pilot
# answers join dev (D7). Plan 8.1.
PILOT_ANALYSIS_KEYS = (
    "n_base",
    "tie_rate",
    "repeats_same",
    "repeats_total",
    "median_seconds",
    "power",
)


def pilot_doc(
    key: dict,
    scored: dict,
    checks: dict,
    *,
    pack_sha: str,
    corpus_fingerprint: str,
    model_judged: bool,
    command: str,
    commit_order_checked: bool,
) -> dict:
    """``results/m4_timing_pilot.json``: the four checks, timing, tie rate, repeat agreement and the
    power table. No arm and no per-pair count (the owner may open this file)."""
    n = scored["n_base"]
    metrics = [
        {"name": "pairwise_tie_rate", "arm": None, "split": "pilot", "n": n,
         "value": scored["tie_rate"]},
    ]  # fmt: skip
    if scored["repeats_total"]:
        metrics.append(
            {
                "name": "judge_repeat_agreement", "arm": None, "split": "pilot",
                "n": scored["repeats_total"],
                "value": scored["repeats_same"] / scored["repeats_total"],
            }
        )  # fmt: skip
    if scored["median_seconds"] is not None:
        metrics.append(
            {"name": "judge_median_seconds", "arm": None, "split": "pilot", "n": n,
             "value": scored["median_seconds"]}
        )  # fmt: skip
    return {
        "label": "MEASURED",
        "what": ("Dry run, model-judged. " if model_judged else "")
        + "Timing pilot of the judging protocol: the four checks, the tie rate and the exact "
        "power table for the observed tie rate.",
        "command": command,
        "config": {
            "checks": checks,
            "pool": key.get("pool"),
            "sheet": key.get("name"),
            "pack_core_sha256": pack_sha,
            "model_judged": model_judged,
            "commit_order_checked": commit_order_checked,
            "analysis": {k: scored[k] for k in PILOT_ANALYSIS_KEYS},
        },
        "seed": 42,
        "corpus_fingerprint": corpus_fingerprint,
        "arms": [],  # no arm: the pilot answers join dev, so the owner must not see per-arm data
        "metrics": metrics,
        "comparisons": [],
        "environment": {},
    }


# ---------------------------------------------------------------- the freeze gates (RI1)


def _json(path: Path):
    """The parsed file, or None when it is missing or is not JSON."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def freeze_gates(
    root: Path,
    *,
    ui_rel: str,
    weights_rel: str,
    table_rel: str,
    dev_pairs_rel: str,
    cv_rel: str,
    futility_rel: str,
) -> list[str]:
    """What must hold before the freeze (plan 7.5, 8.1). Return the problems, empty for none.

    The UI decision is yes. Futility check 1 passed (``results/m4_cv.json``) and check 2 said GO
    (``results/m4_futility.json``), and the futility file is never model-judged. The weights, the
    table and the three results agree: one comparator, one table hash, the same weights file.

    A model-judged training table is allowed only when every part says so (Amendment 2): the
    weights, the table and the cv file say ``training_labels: model_judged``, the dev pairs and
    the cv file are model-judged, and the comparator is ``shipped``. Otherwise a model-judged
    file stops the freeze.
    """
    root = Path(root)
    problems: list[str] = []
    ui = _json(root / ui_rel)
    approved = None if ui is None else ui.get("approved")
    if isinstance(approved, str):
        approved = {"yes": True, "no": False}.get(approved.strip().lower())
    if ui is None:
        problems.append(f"{ui_rel} is missing or is not JSON")
    elif approved is not True:
        problems.append("the UI decision is not yes: the freeze stops")
    docs = {rel: _json(root / rel) for rel in (weights_rel, dev_pairs_rel, cv_rel, futility_rel)}
    problems += [f"{rel} is missing or is not JSON" for rel, doc in docs.items() if doc is None]
    if None in docs.values():
        return problems
    weights, pairs, cv, fut = (docs[r] for r in (weights_rel, dev_pairs_rel, cv_rel, futility_rel))
    labels = weights["trained_on"].get("training_labels", "human")
    problems += _label_chain_problems(
        labels, weights, pairs, cv, fut, root / table_rel, dev_pairs_rel, cv_rel, futility_rel
    )
    if not cv["config"].get("check1", {}).get("pass"):
        problems.append("futility check 1 did not pass (results/m4_cv.json)")
    futility = fut["config"].get("futility", {})
    if futility.get("stop") is not False:
        problems.append("futility check 2 did not say GO (results/m4_futility.json)")
    names = {
        pairs["config"]["comparator"],
        weights["comparator"],
        fut["config"].get("comparator"),
        futility.get("comparator"),
    }
    if labels == "model_judged" and names != {"shipped"}:
        problems.append("model-judged training labels need the comparator shipped (Amendment 2)")
    if len(names) != 1:
        problems.append(
            "the comparator differs between the dev pairs, the weights and the futility result: "
            + ", ".join(sorted(map(str, names)))
        )
    if fut["config"].get("weights_sha256") != sha256_file(root / weights_rel):
        problems.append("the futility check ran with other weights than the ones on disk")
    table = root / table_rel
    table_sha = sha256_file(table) if table.is_file() else None
    if weights["trained_on"].get("train_table_sha256") != table_sha:
        problems.append("the weights name another training table than the file on disk")
    if cv["config"].get("train_table_sha256") != table_sha:
        problems.append("results/m4_cv.json names another training table than the file on disk")
    return problems


def _label_chain_problems(labels, weights, pairs, cv, fut, table_path, dev_rel, cv_rel, fut_rel):
    """One label source in the weights, the table, the cv file and the dev pairs."""
    problems: list[str] = []
    if labels not in ("human", "model_judged"):
        return [f"the weights name an unknown training label source: {labels!r}"]
    if fut["config"].get("model_judged"):
        problems.append(f"{fut_rel} is model-judged: the futility check stays human")
    model = labels == "model_judged"
    for rel, doc in ((dev_rel, pairs), (cv_rel, cv)):
        flag = bool(doc["config"].get("model_judged"))
        if flag and not model:
            problems.append(f"{rel} is model-judged but the weights say human training labels")
        elif model and not flag:
            problems.append(
                f"the training labels disagree: the weights say model_judged, {rel} does not"
            )
    table = _json(table_path) or {}
    cv_labels = cv["config"].get("training_labels", "human")
    sources = (
        ("the table", table.get("training_labels", "human")),
        ("results/m4_cv.json", cv_labels),
    )
    for who, got in sources:
        if got != labels:
            problems.append(
                f"the training labels disagree: the weights say {labels}, {who} says {got}"
            )
    if model and not str(pairs["config"].get("comparator_source", "")).startswith("default"):
        problems.append(f"{dev_rel} did not take the default comparator for model-judged answers")
    return problems


def freeze_facts(root: Path, *, weights_rel: str, dev_pairs_rel: str) -> dict:
    """The label source and the comparator source, for ``freeze.v1.json`` (Amendment 2)."""
    root = Path(root)
    weights, pairs = _json(root / weights_rel) or {}, _json(root / dev_pairs_rel) or {}
    return {
        "training_labels": weights.get("trained_on", {}).get("training_labels", "human"),
        "comparator_source": pairs.get("config", {}).get("comparator_source", SOURCE_HUMAN),
    }
