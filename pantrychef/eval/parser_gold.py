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

M3 adds ``mention_accuracy``: gold groups with a correct predicted group / gold groups. With an
``id_map`` (gold name to id), gold names map through it and not through the table keys.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pantrychef.ingredients.resolve import resolve_lines
from pantrychef.ingredients.table import IngredientTable, tokens

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / "data/eval/m3_frozen_lines.v1.json"


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


def label_from_fields(lid: str, names: str, optional: str, not_an_ingredient: str) -> Label:
    """Build a ``Label`` from the three work-sheet fields. Raise ``LabelError`` if they conflict."""
    skip = not_an_ingredient.strip() == "1"
    groups = parse_names(names)
    if skip and groups:
        raise LabelError(f"{lid}: not_an_ingredient with names")
    if not skip and not groups:
        raise LabelError(f"{lid}: blank label")
    opt = optional.strip()
    if opt not in ("", "0", "1"):
        raise LabelError(f"{lid}: optional must be 0, 1 or blank")
    return Label(groups, opt == "1", skip)


def read_labels_csv(path: Path, line_ids: Iterable[str]) -> dict[str, Label]:
    """Read the work CSV. Raise ``LabelError`` for a missing, extra, blank or contradictory row.

    The ``optional`` and ``not_an_ingredient`` columns may be absent (realistic-input sheets).
    """
    expected = set(line_ids)
    out: dict[str, Label] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for rec in csv.DictReader(fh):
            lid = rec["id"]
            if lid not in expected:
                raise LabelError(f"unknown line id {lid}")
            if lid in out:
                raise LabelError(f"duplicate line id {lid}")
            out[lid] = label_from_fields(
                lid,
                rec["names"] or "",
                rec.get("optional") or "",
                rec.get("not_an_ingredient") or "",
            )
    missing = expected - set(out)
    if missing:
        raise LabelError(f"{len(missing)} lines have no label, for example {sorted(missing)[0]}")
    return out


def read_labels_json(path: Path) -> dict[str, Label]:
    """Read a ``labels.*.json`` file (parser gold) or ``realistic_inputs.labels`` file."""
    raw = json.loads(Path(path).read_text(encoding="utf8"))["labels"]
    return {
        k: Label(tuple(tuple(g) for g in v["groups"]), v["optional"], v["not_an_ingredient"])
        for k, v in raw.items()
    }


def line_hash(text: str) -> str:
    """sha256 of the case-folded, stripped line text. The key of the M3 frozen set."""
    return hashlib.sha256(text.casefold().strip().encode("utf8")).hexdigest()


def load_frozen() -> frozenset[str]:
    """Hashes of every test and extra line. Table growth must not read these lines."""
    return frozenset(json.loads(FROZEN.read_text(encoding="utf8"))["hashes"])


def to_ids(
    group: tuple[str, ...], table: IngredientTable, id_map: dict[str, str | None] | None = None
) -> tuple[set[str], list[str]]:
    """Return ``(ids found, names with no id)`` for one gold group.

    With ``id_map`` a name maps through it (``None`` means no id). A name that is missing from
    the map raises ``LabelError``. Map keys and names are compared by ``tokens``. Without
    ``id_map`` a name maps through the table keys.
    """
    norm = None if id_map is None else {tokens(k): v for k, v in id_map.items()}
    ids: set[str] = set()
    unknown: list[str] = []
    for name in group:
        if norm is None:
            hit = table.keys.get(tokens(name))
        elif tokens(name) in norm:
            hit = norm[tokens(name)]
        else:
            raise LabelError(f"gold name {name!r} is not in the id map")
        if hit is None:
            unknown.append(name)
        else:
            ids.add(hit)
    return ids, unknown


def score(
    lines: list[dict],
    labels: dict[str, Label],
    table: IngredientTable,
    id_map: dict[str, str | None] | None = None,
) -> dict[str, float | int]:
    """Score the resolver on ``lines`` (sheet records) against ``labels``."""
    pred_total = pred_ok = gold_total = gold_found = out_of_table = mention_ok = 0
    opt_total = opt_ok = 0
    for rec in lines:
        label = labels[rec["id"]]
        resolved = [rl for rl in resolve_lines(rec["text"], table) if rl.read]
        preds = [set(rl.options) for rl in resolved]
        pred_total += len(preds)
        gold_sets: list[set[str]] = []
        for group in label.groups:
            ids, unknown = to_ids(group, table, id_map)
            out_of_table += bool(unknown) and not ids
            gold_sets.append(ids)
        gold_total += len(gold_sets)
        pred_ok += sum(1 for p in preds if p and any(g and p <= g for g in gold_sets))
        gold_found += sum(1 for g in gold_sets if g and any(p & g for p in preds))
        mention_ok += sum(1 for g in gold_sets if g and any(p and p <= g for p in preds))
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
        "mention_correct": mention_ok,
        "mention_accuracy": mention_ok / gold_total if gold_total else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "optional_accuracy": opt_ok / opt_total if opt_total else 0.0,
        "optional_n": opt_total,
    }
