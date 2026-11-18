"""Score a judging answers CSV against the private key. See docs/JUDGING_PROTOCOL.md.

    uv run python scripts/judging_score.py --answers FILE.csv --key KEY.json --out scored.json

It prints no result: the numbers go to ``--out``. The M4 stages are scored by
``scripts/m4_rank.py`` (dev-score, pilot-score, futility, score).

CSV columns: item_id, choice (A = left list, B = right list, or tie),
would_cook_left (yes|no), would_cook_right (yes|no), seconds. Optional columns: strength (1 or 2,
blank on a tie), session (any label) and arm_guess (left|right|unsure, test sheets only).
Arm names come from the key.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import statistics
import sys
from pathlib import Path

from pantrychef.eval.m4_run import pair_stats as _pair_stats
from pantrychef.eval.stats import (
    clopper_pearson,
    mcnemar_exact,
    min_detectable_rate,
    power_at,
    sign_test,
    wilcoxon_signed_rank,
    wins_needed,
)

Z = 1.96  # two-sided 95% normal quantile
HALF_WIDTH = 0.1  # an interval of width 0.2


def power_estimate(p: float, tie_rate: float) -> dict:
    """Old M2 normal-approximation estimate of the pantries needed for a 95% interval of width 0.2.

    Kept for the M2 tests. The scorer now prints ``power_table`` (exact binomial, plan section 6).
    Non-tie pantries n = Z^2 * p * (1 - p) / HALF_WIDTH^2. Pantries = n / (1 - tie_rate).
    The worst case uses p = 0.5, because p from a small pilot is noisy.
    """

    def need(q: float) -> int:
        return math.ceil(Z * Z * q * (1 - q) / HALF_WIDTH**2)

    def total(n: int) -> int | None:
        return None if tie_rate >= 1 else math.ceil(n / (1 - tie_rate))

    n, w = need(p), need(0.5)
    return {
        "non_tie_needed": n,
        "pantries_needed": total(n),
        "worst_non_tie_needed": w,
        "worst_pantries_needed": total(w),
    }


def power_table(tie_rate: float, ns: tuple[int, ...] = (40, 60, 80, 100)) -> list[dict]:
    """Exact power rows (plan section 6, ESTIMATE) for the observed tie rate.

    ``decided`` is the expected number of decided items. ``mdw`` is the minimum detectable win
    rate at 80% power, rounded up to 0.005.
    """
    rows = []
    for n in ns:
        d = round(n * (1 - tie_rate))
        rows.append(
            {
                "n": n,
                "decided": d,
                "wins_needed": wins_needed(d) if d else None,
                "power_065": power_at(n, tie_rate, 0.65),
                "power_070": power_at(n, tie_rate, 0.70),
                "power_075": power_at(n, tie_rate, 0.75),
                "mdw": min_detectable_rate(n, tie_rate),
            }
        )
    return rows


def _yes(v: str) -> bool:
    v = v.strip().lower()
    if v not in ("yes", "no"):
        raise ValueError(f"expected yes or no, got {v!r}")
    return v == "yes"


def _pair_name(a: str, b: str) -> str:
    return f"{a}_vs_{b}"


def _tally(entries: list[tuple[tuple[str, str], str]], arms: list[str]) -> dict[str, dict]:
    """``entries`` are ((a, b), outcome). Return pair name to ``_pair_stats``."""
    out = {}
    for a, b in itertools.combinations(arms, 2):
        got = [o for pair, o in entries if pair == (a, b)]
        if got:
            out[_pair_name(a, b)] = _pair_stats(a, b, got.count(a), got.count(b), got.count("tie"))
    return out


def _outcomes(key: dict, rows: list[dict]) -> dict[str, str]:
    """Item id to the winning arm name, or ``tie``."""
    items = key.get("items", key)
    out: dict[str, str] = {}
    for r in rows:
        iid = r["item_id"]
        if iid not in items:
            raise ValueError(f"unknown item_id {iid!r}")
        k = items[iid]
        choice = r["choice"].strip()
        if choice not in ("A", "B", "tie"):
            raise ValueError(f"choice must be A, B or tie, got {choice!r}")
        out[iid] = {"A": k["left"], "B": k["right"], "tie": "tie"}[choice]
    return out


def probe_agreement(
    test_key: dict, test_rows: list[dict], dev_key: dict, dev_rows: list[dict]
) -> dict:
    """Drift probes: how often the test answer on a probe equals the dev answer on the same
    pantry and arm pair. Both answers are read as the winning arm, so side swaps do not matter."""
    t_items, d_items = test_key.get("items", test_key), dev_key.get("items", dev_key)
    t_out, d_out = _outcomes(test_key, test_rows), _outcomes(dev_key, dev_rows)
    dev = {
        (k["pantry_id"], frozenset((k["left"], k["right"]))): d_out[i]
        for i, k in d_items.items()
        if not k["repeat_of"] and i in d_out
    }
    n = agree = 0
    for i, k in t_items.items():
        if not k.get("probe") or i not in t_out:
            continue
        ref = dev.get((k["pantry_id"], frozenset((k["left"], k["right"]))))
        if ref is None:
            continue
        n += 1
        agree += ref == t_out[i]
    return {"n": n, "agree": agree}


def score(key: dict, rows: list[dict], model_arm: str | None = None) -> dict:
    """Per pair W, L, T, net preference, CP interval and exact p; repeats; times; would-cook.

    Only base items count: not repeats, not drift probes (``probe`` in the key). ``key`` maps
    item_id to ``{left, right, repeat_of}`` (M4 keys add ``probe`` and ``pantry_id``). With
    ``model_arm`` the result also holds ``primary``, ``secondary`` and, when the rows carry the
    column, ``arm_guess``, for the model against the other arm (plan 6.1).
    """
    items = key.get("items", key)
    arms = sorted({k[s] for k in items.values() for s in ("left", "right")})
    if model_arm is not None and model_arm not in arms:
        raise ValueError(f"model arm {model_arm!r} is not in the key arms {arms}")
    outcome = _outcomes(key, rows)
    has = {c: any(c in r for r in rows) for c in ("strength", "session", "arm_guess")}
    cook: dict[str, list[bool]] = {a: [] for a in arms}
    seconds = []
    info: dict[str, dict] = {}  # base item id to its row facts
    for r in rows:
        iid = r["item_id"]
        k = items[iid]
        if r["seconds"].strip():  # a model judge cannot time itself, so blank is allowed
            seconds.append(float(r["seconds"]))
        if k["repeat_of"] or k.get("probe"):
            continue
        wl, wr = _yes(r["would_cook_left"]), _yes(r["would_cook_right"])
        cook[k["left"]].append(wl)
        cook[k["right"]].append(wr)
        info[iid] = {"wl": wl, "wr": wr, "session": (r.get("session") or "").strip()}
        if has["strength"]:
            v = (r.get("strength") or "").strip()
            if v not in ("", "1", "2"):
                raise ValueError(f"strength must be 1, 2 or blank, got {v!r} for {iid}")
            if v and outcome[iid] == "tie":
                raise ValueError(f"strength {v} on a tie ({iid}); leave it blank")
            info[iid]["strength"] = int(v) if v else None
        if has["arm_guess"]:
            g = (r.get("arm_guess") or "").strip()
            if g not in ("left", "right", "unsure"):
                raise ValueError(f"arm_guess must be left, right or unsure, got {g!r} for {iid}")
            info[iid]["guess"] = g
    if 0 < len(seconds) < len(rows):
        raise ValueError("seconds is blank for some items and set for others")
    missing = sorted(set(items) - set(outcome))
    if missing:
        raise ValueError(f"no answer for {missing}")
    base = [i for i, k in items.items() if not k["repeat_of"] and not k.get("probe")]
    sessions_on = any(info[i]["session"] for i in base)
    if sessions_on and not all(info[i]["session"] for i in base):
        raise ValueError("session is blank for some items and set for others")

    def pair_of(i: str) -> tuple[str, str]:
        return tuple(sorted((items[i]["left"], items[i]["right"])))  # type: ignore[return-value]

    ties = sum(outcome[i] == "tie" for i in base)
    reps = [(i, k["repeat_of"]) for i, k in items.items() if k["repeat_of"]]
    tie_rate = ties / len(base)
    out = {
        "n_base": len(base),
        "arms": arms,
        "pairs": _tally([(pair_of(i), outcome[i]) for i in base], arms),
        "tie_rate": tie_rate,
        "repeats_same": sum(outcome[a] == outcome[b] for a, b in reps),
        "repeats_total": len(reps),
        "median_seconds": statistics.median(seconds) if seconds else None,
        "would_cook": {a: sum(v) / len(v) for a, v in cook.items() if v},
        "power": power_table(tie_rate),
        "probes": [
            {
                "item_id": i,
                "pantry_id": k.get("pantry_id"),
                "arms": sorted((k["left"], k["right"])),
                "outcome": outcome[i],
            }
            for i, k in items.items()
            if k.get("probe")
        ],
    }
    if sessions_on:
        out["sessions"] = {
            s: _tally([(pair_of(i), outcome[i]) for i in base if info[i]["session"] == s], arms)
            for s in sorted({info[i]["session"] for i in base})
        }
    if has["strength"]:
        out["strength"] = _strength(base, outcome, info, arms, pair_of)
    if model_arm is not None:
        out.update(_vs_rule(items, base, outcome, info, model_arm, has["arm_guess"], sessions_on))
    return out


def _strength(base, outcome, info, arms, pair_of) -> dict:
    """Signed strength scores per pair, toward the first arm of the pair (-2 to 2).

    A tie scores 0. A decided item with a blank strength is missing and not scored.
    """
    res = {}
    for a, b in itertools.combinations(arms, 2):
        scores, missing = [], 0
        for i in base:
            if pair_of(i) != (a, b):
                continue
            if outcome[i] == "tie":
                scores.append(0)
            elif info[i]["strength"] is None:
                missing += 1
            else:
                scores.append(info[i]["strength"] * (1 if outcome[i] == a else -1))
        res[_pair_name(a, b)] = {
            "scores": scores,
            "n_missing": missing,
            "wilcoxon_p": wilcoxon_signed_rank(scores),
        }
    return res


def _vs_rule(items, base, outcome, info, model, guessing: bool, sessions_on: bool) -> dict:
    """Plan 6.1: the model against the rule it was paired with, one item per pantry."""
    mine = [i for i in base if model in (items[i]["left"], items[i]["right"])]
    rules = {items[i]["right" if items[i]["left"] == model else "left"] for i in mine}
    if len(rules) != 1:
        raise ValueError(f"the model arm must face exactly one other arm, found {sorted(rules)}")
    rule = rules.pop()
    won = [i for i in mine if outcome[i] == model]
    lost = [i for i in mine if outcome[i] == rule]
    n = len(mine)
    ties = n - len(won) - len(lost)
    d = len(won) + len(lost)
    rate = len(won) / d if d else None
    ci = clopper_pearson(len(won), d) if d else None
    primary = {
        "model": model,
        "rule": rule,
        "W": len(won),
        "L": len(lost),
        "T": ties,
        "n": n,
        "win_rate": rate,
        "cp": list(ci) if ci else None,
        "gain": rate - 0.5 if rate is not None else None,
        "gain_ci": [ci[0] - 0.5, ci[1] - 0.5] if ci else None,
        "p_exact": sign_test(len(won), d),
        "cp_lo_above_half": bool(ci and ci[0] > 0.5),
        "tie_rate": ties / n,
        "win_rate_ties_as_half": (len(won) + 0.5 * ties) / n,
        "worst_case_win_rate": len(won) / n,  # every tie goes to the rule: W against L + T
        "net_preference": (len(won) - len(lost)) / n,
    }
    if sessions_on:
        primary["sessions"] = {}
        for s in sorted({info[i]["session"] for i in mine}):
            sw = sum(outcome[i] == model for i in mine if info[i]["session"] == s)
            sl = sum(outcome[i] == rule for i in mine if info[i]["session"] == s)
            primary["sessions"][s] = {
                "W": sw,
                "L": sl,
                "win_rate": sw / (sw + sl) if sw + sl else None,
            }

    if all("strength" in info[i] for i in mine):
        # Signed toward the model: +1 or +2 when the model list is preferred. A tie scores 0.
        scores, missing = [], 0
        for i in mine:
            if outcome[i] == "tie":
                scores.append(0)
            elif info[i]["strength"] is None:
                missing += 1
            else:
                scores.append(info[i]["strength"] * (1 if outcome[i] == model else -1))
        primary["strength"] = {
            "toward": model,
            "scores": scores,
            "n_missing": missing,
            "mean": sum(scores) / len(scores) if scores else None,
            "wilcoxon_p": wilcoxon_signed_rank(scores),
        }

    def says(i: str, arm: str) -> bool:
        return info[i]["wl"] if items[i]["left"] == arm else info[i]["wr"]

    # Would-cook (secondary): b = model yes and rule no, c = the reverse.
    b = sum(says(i, model) and not says(i, rule) for i in mine)
    c = sum(says(i, rule) and not says(i, model) for i in mine)
    res = {
        "primary": primary,
        "secondary": {
            "would_cook": {
                "b": b,
                "c": c,
                "mean_diff": (b - c) / n,
                "p_mcnemar": mcnemar_exact(b, c),
                "cp": list(clopper_pearson(b, b + c)) if b + c else None,
            }
        },
    }
    if guessing:
        res["arm_guess"] = _arm_guess(items, mine, outcome, info, model)
    return res


def _arm_guess(items, mine, outcome, info, model) -> dict:
    """Guess accuracy among left or right guesses, and the model win rate by guess result."""
    groups: dict[str, list[str]] = {"right": [], "wrong": [], "unsure": []}
    for i in mine:
        g = info[i]["guess"]
        if g == "unsure":
            groups["unsure"].append(i)
        else:
            groups["right" if items[i][g] == model else "wrong"].append(i)
    guessed = len(groups["right"]) + len(groups["wrong"])
    out = {
        "n_guessed": guessed,
        "n_right": len(groups["right"]),
        "n_wrong": len(groups["wrong"]),
        "n_unsure": len(groups["unsure"]),
        "unsure_share": len(groups["unsure"]) / len(mine),
        "accuracy": len(groups["right"]) / guessed if guessed else None,
        "cp": list(clopper_pearson(len(groups["right"]), guessed)) if guessed else None,
    }
    for name, ids in groups.items():
        w = sum(outcome[i] == model for i in ids)
        lo = sum(outcome[i] not in (model, "tie") for i in ids)
        out[name] = {"W": w, "L": lo, "win_rate": w / (w + lo) if w + lo else None}
    return out


def result_doc(
    key: dict, scored: dict, command: str, split: str = "test", *, corpus_fingerprint: str
) -> dict:
    """The results-file body for the test (plan 6.1 and 13.1). ``scripts/m4_rank.py score`` uses it.

    ``corpus_fingerprint`` is ``pack.info.corpus_fingerprint``, the same value every M4 file uses.

    ``write_result`` adds the git facts, the roles and the dependencies.
    """
    p = scored["primary"]
    model, rule = p["model"], p["rule"]
    d = p["W"] + p["L"]
    metrics = []

    def ci(lo: float, hi: float, n: int) -> dict:
        return {"lo": lo, "hi": hi, "level": 0.95, "method": "clopper-pearson-exact",
                "n_clusters": n}  # fmt: skip

    def add(name, value, n, arm=None, **extra):
        if value is not None:
            metrics.append(
                {"name": name, "arm": arm, "split": split, "n": n, "value": value, **extra}
            )

    if p["cp"]:
        add("pairwise_win_rate", p["win_rate"], d, model, ci=ci(*p["cp"], d))
    add("pairwise_tie_rate", p["tie_rate"], p["n"])
    add("pairwise_net_preference", p["net_preference"], p["n"])
    if scored["repeats_total"]:
        rate = scored["repeats_same"] / scored["repeats_total"]
        add("judge_repeat_agreement", rate, scored["repeats_total"])
    add("judge_median_seconds", scored["median_seconds"], p["n"])
    for arm in (model, rule):
        add("would_cook_rate", scored["would_cook"][arm], p["n"], arm)
    g = scored.get("arm_guess")
    if g and g["accuracy"] is not None:
        add(
            "judge_arm_guess_accuracy",
            g["accuracy"],
            g["n_guessed"],
            ci=ci(*g["cp"], g["n_guessed"]),
        )
    comparisons = []
    if p["gain_ci"]:
        comparisons.append(
            {
                "metric": "pairwise_win_rate",
                "a": model,
                "b": rule,
                "split": split,
                "diff": p["gain"],
                "ci": ci(*p["gain_ci"], d),
            }
        )
    return {
        "label": "MEASURED",
        "what": f"Hand-judged {split}: {model} against {rule}, one item per pantry, one judge. "
        "Primary: win rate among decided items with a two-sided exact Clopper-Pearson interval.",
        "command": command,
        "config": {
            "arms": [model, rule],
            "n_test": p["n"],
            "gold_out": key.get("gold_out"),
            "neutral_order": key.get("neutral_order"),
            "comparator": rule,
            "pool": key.get("pool"),
            "pack_core_sha256": key.get("pack_core_sha256"),
            "model_sha256": key.get("model_sha256"),
            "analysis": scored,
        },
        "seed": key.get("seed", 42),
        "corpus_fingerprint": corpus_fingerprint,
        "arms": [{"name": model}, {"name": rule}],
        "metrics": metrics,
        "comparisons": comparisons,
        "environment": {},
    }


def main(argv: list[str] | None = None) -> int:
    """Score an answers file and write the numbers to ``--out``. Print no result.

    The owner must not see dev or test numbers until the plan allows it (plan 8.1). The test is
    scored by ``scripts/m4_rank.py score``, which checks the freeze first.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--answers", required=True)
    ap.add_argument("--key", default="data/interim/judging_key.pilot.v1.json")
    ap.add_argument("--out", required=True, help="the scored analysis, as JSON")
    args = ap.parse_args(argv)
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    with open(args.answers, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    NL = chr(10)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(score(key, rows), indent=2) + NL, encoding="utf-8", newline=NL)
    print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
