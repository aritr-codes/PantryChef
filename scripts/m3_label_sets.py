"""M3 label sets: blind sheets, label comparison, owner sheet and merge (M3 Task 1).

  uv run python scripts/m3_label_sets.py make-sheets
  uv run python scripts/m3_label_sets.py compare NAME A B
  uv run python scripts/m3_label_sets.py owner-sheet
  uv run python scripts/m3_label_sets.py merge [OWNER_CSV]

NAME is ``test150``, ``extra100`` or ``inputs166``. A and B are filled CSVs (B may also be a
labels JSON such as ``labels.test.v1.json``). Work files go to ``data/interim/`` (git ignores
it). Every command prints counts only. It never prints a line or a label.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections.abc import Callable
from pathlib import Path

from pantrychef.eval.parser_gold import Label, LabelError, label_from_fields, read_labels_csv

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data/interim"
GOLD = ROOT / "data/eval/parser_gold"
SHEET = GOLD / "sheet.v1.json"
EXTRA = GOLD / "extra.v1.json"
INPUTS = ROOT / "data/eval/realistic_inputs.v1.json"
PARSER_SETS = ("test150", "extra100", "fresh200")  # the owner checks agreed lines from these
SEED_AGREED = 44
N_AGREED = 30
MAX_AGREED_ERRORS = 2
Sets = dict[str, list[tuple[str, str]]]  # name -> [(id, text)]


def load_sets() -> Sets:
    """The three sets, from the committed files. Inputs get ids ``in000`` and up."""
    sheet = json.loads(SHEET.read_text(encoding="utf8"))["lines"]
    extra = json.loads(EXTRA.read_text(encoding="utf8"))["lines"]
    inputs = json.loads(INPUTS.read_text(encoding="utf8"))["inputs"]
    return {
        "test150": [(r["id"], r["text"]) for r in sheet if r["split"] == "test"],
        "extra100": [(r["id"], r["text"]) for r in extra],
        "inputs166": [(f"in{i:03d}", r["text"]) for i, r in enumerate(inputs)],
    }


def _columns(name: str) -> list[str]:
    cols = ["id", "text", "names"]
    return cols if name.startswith("inputs") else cols + ["optional", "not_an_ingredient"]


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def make_sheets(sets: Sets, work: Path) -> None:
    """Write one blind CSV per set: only ``id`` and ``text`` are filled."""
    paths = {name: work / f"m3_label_{name}.csv" for name in sets}
    if any(p.exists() for p in paths.values()):
        raise SystemExit("a blind sheet exists; delete it first (it may hold labels)")
    for name, items in sets.items():
        cols = _columns(name)
        blank = [""] * (len(cols) - 2)
        _write_csv(paths[name], cols, [[i, t, *blank] for i, t in items])
        print(f"{paths[name].name}: {len(items)} rows")


def _label_json(label: Label) -> dict:
    return {
        "groups": [list(g) for g in label.groups],
        "optional": label.optional,
        "not_an_ingredient": label.not_an_ingredient,
    }


def _load(path: Path, ids: list[str]) -> dict[str, Label]:
    """Read labels from a filled CSV or from a labels JSON. The ids must match exactly."""
    if path.suffix != ".json":
        return read_labels_csv(path, ids)
    raw = json.loads(path.read_text(encoding="utf8"))["labels"]
    if set(raw) != set(ids):
        raise LabelError(f"{path.name}: ids do not match the set")
    return {
        k: Label(tuple(tuple(g) for g in v["groups"]), v["optional"], v["not_an_ingredient"])
        for k, v in raw.items()
    }


def _key(label: Label) -> tuple:
    """Same set of groups, ignoring order and alternative order, and the same flags."""
    groups = frozenset(frozenset(a.casefold() for a in g) for g in label.groups)
    return groups, label.optional, label.not_an_ingredient


def _ref(path: Path) -> dict:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _load_pair(d: dict, ids: list[str]) -> tuple[dict[str, Label], dict[str, Label]]:
    """Reload both labeller files of a disagreement record. Refuse if either file changed."""
    out = []
    for side in ("a", "b"):
        ref = d[side]
        path = Path(ref["path"])
        if _ref(path)["sha256"] != ref["sha256"]:
            raise LabelError(f"{path.name} changed since compare; run compare again")
        out.append(_load(path, ids))
    return out[0], out[1]


def compare(name: str, sets: Sets, a: Path, b: Path, work: Path) -> tuple[int, int, list[str]]:
    """Return ``(n, exact agreements, ids that differ)`` and write the disagreement file."""
    ids = [i for i, _ in sets[name]]
    la, lb = _load(a, ids), _load(b, ids)
    diff = [i for i in ids if _key(la[i]) != _key(lb[i])]
    out = {
        "name": name,
        "n": len(ids),
        "exact_agreement": len(ids) - len(diff),
        "a": _ref(a),
        "b": _ref(b),
        "ids": diff,
    }
    (work / f"m3_disagreements_{name}.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf8", newline="\n"
    )
    return len(ids), len(ids) - len(diff), diff


def _fmt(label: Label) -> str:
    if label.not_an_ingredient:
        return "[not an ingredient]"
    text = ";".join("|".join(g) for g in label.groups)
    return text + (" [optional]" if label.optional else "")


def _dis(work: Path, name: str) -> dict:
    return json.loads((work / f"m3_disagreements_{name}.json").read_text(encoding="utf8"))


def owner_sheet(sets: Sets, work: Path, n_agreed: int = N_AGREED, seed: int = SEED_AGREED) -> Path:
    """Write the owner sheet: every disagreement plus a seeded sample of agreed parser lines."""
    rows: list[list[str]] = []
    agreed: list[tuple[str, str, str, Label]] = []
    for name, items in sets.items():
        d = _dis(work, name)
        ids = [i for i, _ in items]
        la, lb = _load_pair(d, ids)
        text = dict(items)
        bad = set(d["ids"])
        rows += [
            [name, i, "disagree", text[i], _fmt(la[i]), _fmt(lb[i]), "", "", "", ""]
            for i in ids
            if i in bad
        ]
        if name in PARSER_SETS:
            agreed += [(name, i, text[i], la[i]) for i in ids if i not in bad]
    for name, i, t, label in random.Random(seed).sample(agreed, min(n_agreed, len(agreed))):
        rows.append([name, i, "agreed", t, _fmt(label), "", "", "", "", ""])
    random.Random(seed).shuffle(rows)
    path = work / "m3_owner_sheet.csv"
    header = ["set", "id", "kind", "text", "label_a", "label_b"]
    _write_csv(path, header + ["names", "optional", "not_an_ingredient", "error"], rows)
    n_dis = sum(r[2] == "disagree" for r in rows)
    print(f"{path.name}: {n_dis} disagreements, {len(rows) - n_dis} agreed lines")
    return path


def merge(
    sets: Sets,
    owner_csv: Path,
    work: Path,
    targets: dict[str, Path],
    max_agreed_errors: int = MAX_AGREED_ERRORS,
    n_agreed: int = N_AGREED,
) -> None:
    """Write the new label files from a filled owner sheet. Never overwrite an existing file.

    The sheet must hold exactly ``n_agreed`` agreed rows, no duplicate row, and no label text on
    an agreed row unless its ``error`` is 1.
    """
    for p in targets.values():
        if p.exists():
            raise SystemExit(f"{p.name} exists; v1 and frozen files are never overwritten")
    owner: dict[tuple[str, str], dict] = {}
    with owner_csv.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r["set"], r["id"]) in owner:
                raise LabelError(f"{r['id']}: duplicate row in the owner sheet")
            if r["kind"] not in ("disagree", "agreed"):
                raise LabelError(f"{r['id']}: kind must be disagree or agreed")
            owner[(r["set"], r["id"])] = r
    if sum(r["kind"] == "agreed" for r in owner.values()) != n_agreed:
        raise LabelError(f"the owner sheet must hold exactly {n_agreed} agreed rows")
    final: dict[str, dict[str, Label]] = {}
    adjudication: dict[str, dict] = {}
    checked: list[str] = []
    errors: list[str] = []
    for name, items in sets.items():
        d = _dis(work, name)
        ids = [i for i, _ in items]
        text = dict(items)
        la, lb = _load_pair(d, ids)
        final[name] = dict(la)  # agreed lines keep labeller A
        records = []
        for i in d["ids"]:
            r = owner.get((name, i))
            if r is None:
                raise LabelError(f"{i}: not in the owner sheet")
            final[name][i] = label_from_fields(i, r["names"], r["optional"], r["not_an_ingredient"])
            records.append(_record(i, text[i], la[i], lb[i], final[name][i]))
        for (set_name, i), r in owner.items():
            if set_name != name or r["kind"] != "agreed":
                continue
            if i not in ids or i in d["ids"]:
                raise LabelError(f"{i}: not an agreed line of {name}")
            checked.append(i)
            flag = r["error"].strip()
            if flag not in ("", "0", "1"):
                raise LabelError(f"{i}: error must be 0, 1 or blank")
            if flag != "1" and (
                r["names"].strip() or r["optional"].strip() or r["not_an_ingredient"].strip()
            ):
                raise LabelError(f"{i}: label filled on an agreed row, but error is not 1")
            if flag == "1":
                errors.append(i)
                final[name][i] = label_from_fields(
                    i, r["names"], r["optional"], r["not_an_ingredient"]
                )
        adjudication[name] = {
            "lines": len(ids),
            "exact_agreement": d["exact_agreement"],
            "a": Path(d["a"]["path"]).name,
            "b": Path(d["b"]["path"]).name,
            "disagreements": records,
        }
    if len(errors) > max_agreed_errors:
        raise SystemExit(f"{len(errors)} of {len(checked)} agreed lines are wrong; stop and report")
    gold_files = {
        "test": ("test150", {"version": 2, "split": "test"}),
        "extra": ("extra100", {"version": 1, "split": "extra"}),
    }
    for key, (name, head) in gold_files.items():
        _dump(targets[key], {**head, "labels": _by_id(final[name])})
    by_text = dict(sets["inputs166"])
    _dump(
        targets["inputs"],
        {
            "version": 1,
            "labels": {by_text[i]: _label_json(v) for i, v in final["inputs166"].items()},
        },
    )
    _dump(
        targets["adjudication"],
        {
            "version": 1,
            "resolved_by": "owner",
            "agreed_check": {
                "n": len(checked),
                "errors": len(errors),
                "agreed_error_rate": len(errors) / len(checked) if checked else 0.0,
                "error_ids": errors,
            },
            "sets": adjudication,
        },
    )
    print(f"wrote {len(targets)} files; agreed-line errors {len(errors)} of {len(checked)}")


def _by_id(labels: dict[str, Label]) -> dict[str, dict]:
    return {i: _label_json(v) for i, v in labels.items()}


def _record(i: str, text: str, a: Label, b: Label, final: Label) -> dict:
    return {
        "id": i,
        "text": text,
        "a": _label_json(a),
        "b": _label_json(b),
        "final": _label_json(final),
        "resolved_by": "owner",
    }


def _dump(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("make-sheets")
    c = sub.add_parser("compare")
    c.add_argument("name", choices=["test150", "extra100", "inputs166"])
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    sub.add_parser("owner-sheet")
    m = sub.add_parser("merge")
    m.add_argument("owner_csv", type=Path, nargs="?", default=WORK / "m3_owner_sheet.csv")
    args = ap.parse_args()
    sets = load_sets()
    run: dict[str, Callable[[], object]] = {
        "make-sheets": lambda: make_sheets(sets, WORK),
        "owner-sheet": lambda: owner_sheet(sets, WORK),
        "merge": lambda: merge(
            sets,
            args.owner_csv,
            WORK,
            {
                "test": GOLD / "labels.test.v2.json",
                "extra": GOLD / "labels.extra.v1.json",
                "adjudication": GOLD / "adjudication.m3.v1.json",
                "inputs": ROOT / "data/eval/realistic_inputs.labels.v1.json",
            },
        ),
    }
    if args.cmd == "compare":
        n, agree, _ids = compare(args.name, sets, args.a, args.b, WORK)
        print(f"{args.name}: n={n}, exact agreements={agree}, disagreements={n - agree}")
    else:
        run[args.cmd]()


if __name__ == "__main__":
    main()
