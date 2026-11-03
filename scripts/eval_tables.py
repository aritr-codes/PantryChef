"""Render the M2 leaderboard tables from results/*.json into docs/EVALUATION.md.

uv run python scripts/eval_tables.py          # rewrite the block
uv run python scripts/eval_tables.py --check  # exit 1 if the committed block is stale
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = Path("docs/EVALUATION.md")
BEGIN = "<!-- BEGIN table:m2-wikibooks -->"
END = "<!-- END table:m2-wikibooks -->"
# Result files shown in the block. The Kaggle result is added here later.
REGISTRY = [Path("results/m2_baseline_wikibooks.json")]
SPLIT = "test"


def _footer(doc: dict, path: Path) -> str:
    return (
        f"*Label: {doc['label']}. Commit: {doc['commit'][:8]}. "
        f"Dirty: {'yes' if doc['dirty'] else 'no'}. "
        f"Results: [{path.name}](../{path.as_posix()}). "
        f"Rebuild: `{doc['command']}`.*"
    )


def _table(head: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(head) + " |", "|" + " --- |" * len(head)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def _group_key(g: dict) -> tuple:
    return (g["sampler"], g["d"])


def render(doc: dict, path: Path) -> str:
    """Markdown for the test split, one section per (sampler, d) group. Pure."""
    foot = _footer(doc, path)
    arms = [a["name"] for a in doc["arms"]]
    groups = list(dict.fromkeys(_group_key(m["group"]) for m in doc["metrics"]))
    out = []
    for sampler, d in groups:
        mine = [
            m
            for m in doc["metrics"]
            if _group_key(m["group"]) == (sampler, d) and m["split"] == SPLIT
        ]
        val = {(m["name"], m["arm"]): m for m in mine}
        sec = [f"### sampler={sampler}, d={d}", ""]
        rows = [
            [
                a,
                f"{val[('recall_at_10', a)]['value']:.4f}",
                f"{val[('mrr_at_10', a)]['value']:.4f}",
                str(val[("recall_at_10", a)]["n"]),
            ]
            for a in arms
            if ("recall_at_10", a) in val
        ]
        sec += [
            "**Table 1. Recovery sanity check (role: sanity, never selects a model). Test split.**",
            "",
            _table(["Arm", "recall@10", "MRR@10", "n"], rows),
            "",
            foot,
            "",
        ]
        comps = [
            c
            for c in doc["comparisons"]
            if _group_key(c["group"]) == (sampler, d) and c["split"] == SPLIT
        ]
        rows = []
        for c in comps:
            lo, hi = c["ci"]["lo"], c["ci"]["hi"]
            holds = "HOLDS" if lo > 0 or hi < 0 else "no"
            rows.append(
                [c["a"], c["b"], c["metric"], f"{c['diff']:+.4f}", f"[{lo:.4f}, {hi:.4f}]", holds]
            )
        n_cl = comps[0]["ci"]["n_clusters"] if comps else 0
        sec += [
            "**Table 2. Paired comparisons, a minus b. Test split.**",
            "",
            _table(["a", "b", "Metric", "Diff", "95% interval", "Holds"], rows),
            "",
            f"HOLDS means the interval excludes 0. Clusters: {n_cl}.",
            "",
            foot,
            "",
        ]
        rows = []
        for name, arm in (
            ("makeable_at_10", "shipped"),
            ("hit_rate", None),
            ("visible_rate", None),
        ):
            m = val.get((name, arm))
            if m:
                rows.append([name, arm or "all arms", f"{m['value']:.4f}", str(m["n"])])
        sec += [
            "**Table 3. Product metrics. Test split.**",
            "",
            _table(["Metric", "Arm", "Value", "n"], rows),
            "",
            "makeable_at_10 is high for `shipped` by construction: "
            "the shipped order lists recipes you can make now first.",
            "",
            foot,
        ]
        out.append("\n".join(sec) + "\n")
    return "\n".join(out)


def render_all(root: Path) -> str:
    parts = [render(json.loads((root / p).read_text(encoding="utf-8")), p) for p in REGISTRY]
    return "\n".join(parts)


def replace_block(text: str, body: str) -> str:
    """Swap the text between the markers. Raise if a marker is missing."""
    if BEGIN not in text or END not in text:
        raise ValueError(f"markers {BEGIN} and {END} not found")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{BEGIN}\n{body}{END}{tail}"


def _read(path: Path) -> tuple[str, str]:
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), "\r\n" if "\r\n" in raw else "\n"


def check(root: Path) -> str | None:
    """None when the committed block is fresh, else a diff message."""
    text, _ = _read(root / DOC)
    want = replace_block(text, render_all(root))
    if want == text:
        return None
    diff = "".join(
        difflib.unified_diff(
            text.splitlines(True), want.splitlines(True), "committed", "rendered", n=1
        )
    )
    return f"{DOC} is stale. Run `uv run python scripts/eval_tables.py`.\n{diff}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.check:
        msg = check(ROOT)
        if msg:
            print(msg, file=sys.stderr)
            return 1
        return 0
    text, nl = _read(ROOT / DOC)
    new = replace_block(text, render_all(ROOT))
    (ROOT / DOC).write_bytes(new.replace("\n", nl).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
