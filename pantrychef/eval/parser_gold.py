"""Parser gold set: label checks and scoring (M2).

A label has ``names``: ingredient groups separated by ``;``. Inside a group, alternatives are
separated by ``|``. Example: ``bulgur|cracked wheat`` is one group with two alternatives, and
``salt;pepper`` is two groups. ``optional`` is 0 or 1. ``not_an_ingredient`` is 1 for a heading
or a non-ingredient line, and then ``names`` must be empty.

A gold name is matched to a table id by exact table key (name or synonym, same normalisation as
the resolver). A name with no key is ``out_of_table``. It stays in the gold, so M3 can score table
growth. The current resolver cannot reach it, so it counts as a missed group.

Scoring, per split (group level, micro-averaged):

- A predicted group is correct when it is non-empty and its ids are a subset of one gold group.
  (Reading only one side of "A or B" is acceptable.)
- A gold group is found when some predicted group shares an id with it.
- precision = correct predicted groups / predicted groups. recall = found gold groups / gold groups.
- Unread lines give no predicted group.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pantrychef.ingredients.resolve import resolve_lines
from pantrychef.ingredients.table import IngredientTable, tokens


class LabelError(ValueError):
    pass


@dataclass(frozen=True)
class Label:
    groups: tuple[tuple[str, ...], ...]  # alternatives per group, as written
    optional: bool
    not_an_ingredient: bool


def parse_names(text: str) -> tuple[tuple[str, ...], ...]:
    groups = []
    for part in text.split(";"):
        alts = tuple(a.strip() for a in part.split("|") if a.strip())
        if alts:
            groups.append(alts)
    return tuple(groups)


def read_labels_csv(path: Path, line_ids: Iterable[str]) -> dict[str, Label]:
    """Read the work CSV. Raise ``LabelError`` for a missing, extra, blank or contradictory row."""
    expected = set(line_ids)
    out: dict[str, Label] = {}
    with path.open(encoding="utf8", newline="") as fh:
        for rec in csv.DictReader(fh):
            lid = rec["id"]
            if lid not in expected:
                raise LabelError(f"unknown line id {lid}")
            if lid in out:
                raise LabelError(f"duplicate line id {lid}")
            skip = rec["not_an_ingredient"].strip() == "1"
            groups = parse_names(rec["names"])
            if skip and groups:
                raise LabelError(f"{lid}: not_an_ingredient with names")
            if not skip and not groups:
                raise LabelError(f"{lid}: blank label")
            opt = rec["optional"].strip()
            if opt not in ("", "0", "1"):
                raise LabelError(f"{lid}: optional must be 0, 1 or blank")
            out[lid] = Label(groups, opt == "1", skip)
    missing = expected - set(out)
    if missing:
        raise LabelError(f"{len(missing)} lines have no label, for example {sorted(missing)[0]}")
    return out


def to_ids(group: tuple[str, ...], table: IngredientTable) -> tuple[set[str], list[str]]:
    """Return ``(ids found, names with no table key)`` for one gold group."""
    ids: set[str] = set()
    unknown: list[str] = []
    for name in group:
        hit = table.keys.get(tokens(name))
        if hit is None:
            unknown.append(name)
        else:
            ids.add(hit)
    return ids, unknown


def score(
    lines: list[dict], labels: dict[str, Label], table: IngredientTable
) -> dict[str, float | int]:
    """Score the resolver on ``lines`` (sheet records) against ``labels``."""
    pred_total = pred_ok = gold_total = gold_found = out_of_table = 0
    opt_total = opt_ok = 0
    for rec in lines:
        label = labels[rec["id"]]
        resolved = [rl for rl in resolve_lines(rec["text"], table) if rl.read]
        preds = [set(rl.options) for rl in resolved]
        pred_total += len(preds)
        gold_sets: list[set[str]] = []
        for group in label.groups:
            ids, unknown = to_ids(group, table)
            out_of_table += bool(unknown) and not ids
            gold_sets.append(ids)
        gold_total += len(gold_sets)
        pred_ok += sum(1 for p in preds if p and any(g and p <= g for g in gold_sets))
        gold_found += sum(1 for g in gold_sets if g and any(p & g for p in preds))
        if resolved and not label.not_an_ingredient:
            opt_total += 1
            opt_ok += any(rl.optional for rl in resolved) == label.optional
    precision = pred_ok / pred_total if pred_total else 0.0
    recall = gold_found / gold_total if gold_total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "lines": len(lines),
        "pred_groups": pred_total,
        "pred_correct": pred_ok,
        "gold_groups": gold_total,
        "gold_found": gold_found,
        "gold_out_of_table": out_of_table,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "optional_accuracy": opt_ok / opt_total if opt_total else 0.0,
        "optional_n": opt_total,
    }
