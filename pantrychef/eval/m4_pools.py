"""M4 pantry pools, split-leak check and label-free IDF variants (plan sections 4.2 and 5)."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from pantrychef.engine import Pack, _needed
from pantrychef.eval.arms import CandidateIndex
from pantrychef.eval.pantries import _group_key, build_pantries, document_frequency

SEED = 42
SALT = "m4"
TOP = 5
MAX_MISSING = 2
# Dev-side pool sizes, taken in this order from the fixed sha256 order of the dev split. The
# pilot is first, so growing a later pool never changes it. The owner chose 100 dev pantries on
# 2026-11-19, after the timing pilot gave a median of 30 s per item (the plan said 60).
PILOT_N, DEV_N, FUTILITY_N, RESERVE_N = 10, 100, 20, 10
POOL_SIZES = (
    ("pilot", PILOT_N),
    ("dev", DEV_N),
    ("futility", FUTILITY_N),
    ("reserve", RESERVE_N),
)
VARIANTS = (
    "idf_smooth",
    "idf_lucene",
    "shipped_b0",
    "shipped_b1",
    "shipped_missmass",
    "grouped_overlap",
)


def pack_core_sha256(pack_dir: str | Path) -> str:
    """sha256 of the core file as stored (gz if present, else plain JSON)."""
    folder = Path(pack_dir)
    path = folder / "core.v2.json.gz"
    if not path.exists():
        path = folder / "core.v2.json"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def order_key(gold_id: str) -> str:
    return hashlib.sha256(f"{SEED}:{SALT}:{gold_id}".encode()).hexdigest()


def content_sha256(ids) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def canonical(doc: Any) -> bytes:
    return (json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def pilot_exclusions(spike_path: str | Path, pack: Pack) -> tuple[set[str], set[str]]:
    """Pilot gold ids and their title groups. The written `new*` pantries have no gold."""
    doc = json.loads(Path(spike_path).read_text(encoding="utf-8"))
    golds = {p["source_recipe_id"] for p in doc["pantries"] if p.get("source_recipe_id")}
    group = {r.recipe_id: _group_key(r) for r in pack.recipes}
    return golds, {group[g] for g in golds if g in group}


def usable_pantries(
    pack: Pack,
    split: str,
    excl_golds: set[str],
    excl_groups: set[str],
    min_candidates: int = TOP,
) -> list[dict]:
    """Draw-0 popularity pantries of one split, in order-key order, after exclusions and
    gold-out. Each item: pantry (EvalPantry), title_group, cands (gold-out Scored list)."""
    staples = set(pack.default_staples)
    index = CandidateIndex(pack, staples)
    group = {r.recipe_id: _group_key(r) for r in pack.recipes}
    out = []
    for p in build_pantries(pack, "popularity", 3, SEED, draws=1):
        g = group[p.gold_id]
        if p.split != split or p.gold_id in excl_golds or g in excl_groups:
            continue
        cands = [
            c
            for c in index.candidates(set(p.pantry))
            if c.total - c.have <= MAX_MISSING and group[c.recipe_id] != g
        ]
        if len(cands) >= min_candidates:
            out.append({"pantry": p, "title_group": g, "cands": cands})
    out.sort(key=lambda x: order_key(x["pantry"].gold_id))
    return out


def _entry(split: str, item: dict) -> dict:
    p = item["pantry"]
    return {
        "pantry_id": f"m4-{split}-{p.gold_id}",
        "gold_id": p.gold_id,
        "title_group": item["title_group"],
        "pantry": list(p.pantry),
        "content_sha256": content_sha256(p.pantry),
    }


def build_pools(
    pack: Pack,
    pack_sha: str,
    spike_path: str | Path,
    sizes: tuple[tuple[str, int], ...] = POOL_SIZES,
) -> tuple[dict, dict]:
    """Return (pantries document, stats)."""
    golds, groups = pilot_exclusions(spike_path, pack)
    dev = usable_pantries(pack, "dev", golds, groups)
    test = usable_pantries(pack, "test", golds, groups)
    need = sum(n for _, n in sizes)
    if len(dev) < need:
        raise ValueError(f"only {len(dev)} usable dev pantries, need {need}")
    pools: dict[str, list[dict]] = {}
    at = 0
    for name, n in sizes:
        pools[name] = [_entry("dev", it) for it in dev[at : at + n]]
        at += n
    pools["test"] = [_entry("test", it) for it in test]
    seen: dict[str, list[str]] = defaultdict(list)
    for rows in pools.values():
        for r in rows:
            seen[r["content_sha256"]].append(r["pantry_id"])
    doc = {
        "version": 1,
        "pack_core_sha256": pack_sha,
        "salt": SALT,
        "excluded": {"gold_ids": sorted(golds), "title_groups": sorted(groups)},
        "pools": pools,
    }
    stats = {
        "usable_dev": len(dev),
        "usable_test": len(test),
        "excluded_golds": len(golds),
        "excluded_groups": len(groups),
        "duplicates": sorted(v for v in seen.values() if len(v) > 1),
    }
    return doc, stats


def check_no_leak(
    doc: dict,
    train_rows: list[dict],
    trained_on: dict,
    pilot_golds: set[str] | None = None,
    *,
    table_sha256: str | None = None,
) -> list[str]:
    """Plan 5.4 assertions on committed data only. Return violations (empty means pass).

    ``train_rows`` need ``pantry_id``. ``gold_id``, ``title_group`` and ``content_sha256`` are
    checked too when present. ``trained_on.pantries_sha256`` is the sha256 of the sorted
    distinct training pantry ids joined by newline. When ``table_sha256`` (the sha256 of the
    training table file bytes) is given, ``trained_on.train_table_sha256`` must equal it.
    """
    pools = doc["pools"]
    bad: list[str] = []
    test = pools["test"]
    t_ids = {r["pantry_id"] for r in test}
    t_gold = {r["gold_id"] for r in test}
    t_grp = {r["title_group"] for r in test}
    t_hash = {r["content_sha256"] for r in test}
    futility = {r["pantry_id"] for r in pools["futility"]}
    known = {r["pantry_id"] for rows in pools.values() for r in rows}
    for row in train_rows:
        pid = row["pantry_id"]
        if pid in t_ids or row.get("gold_id") in t_gold:
            bad.append(f"test pantry in training: {pid}")
        if row.get("title_group") in t_grp or row.get("content_sha256") in t_hash:
            bad.append(f"test title group or content in training: {pid}")
        if pid in futility:
            bad.append(f"futility pantry in training: {pid}")
        if pid not in known:
            bad.append(f"training pantry not in any pool: {pid}")
    ids = sorted({row["pantry_id"] for row in train_rows})
    if hashlib.sha256("\n".join(ids).encode()).hexdigest() != trained_on.get("pantries_sha256"):
        bad.append("trained_on.pantries_sha256 does not match the training table")
    dev_grp = {r["title_group"] for n in ("pilot", "dev", "futility", "reserve") for r in pools[n]}
    if dev_grp & t_grp:
        bad.append("dev and test share a title group")
    all_golds = {r["gold_id"] for rows in pools.values() for r in rows}
    excluded = doc.get("excluded", {})
    pilot_golds = set(pilot_golds or ()) | set(excluded.get("gold_ids", ()))
    if pilot_golds & all_golds:
        bad.append("a pilot gold id is in an M4 pantry")
    pilot_grp = set(excluded.get("title_groups", ()))
    all_grp = {r["title_group"] for rows in pools.values() for r in rows}
    if pilot_grp & all_grp:
        bad.append("a pilot title group is in an M4 pantry")
    owner: dict[str, str] = {}
    for name, rows in pools.items():
        for r in rows:
            first = owner.setdefault(r["content_sha256"], name)
            if first != name:
                bad.append(f"same content in pools {first} and {name}: {r['pantry_id']}")
    if table_sha256 is not None and trained_on.get("train_table_sha256") != table_sha256:
        bad.append("trained_on.train_table_sha256 does not match the training table file")
    return bad


# ---- label-free IDF variants (plan 4.2) ----


class VariantScorer:
    """Top 5 of the shipped order and the six variants, on gold-out candidates."""

    def __init__(self, pack: Pack):
        self.pack = pack
        staples = set(pack.default_staples)
        self.index = CandidateIndex(pack, staples)
        by_id = {r.recipe_id: r for r in pack.recipes}
        n, df = len(pack.recipes), document_frequency(pack)
        fns = {
            "shipped": lambda i: pack.ingredients[i].idf,
            "smooth": lambda i: math.log((n + 1) / (df[i] + 1)) + 1,
            "lucene": lambda i: math.log(1 + (n - df[i] + 0.5) / (df[i] + 0.5)),
        }
        self.w: dict[str, list[list[float]]] = {}
        for name, f in fns.items():
            self.w[name] = [
                [
                    max((f(o) for o in ln.options if o in pack.ingredients), default=0.0)
                    for ln in _needed(by_id[rid], staples)
                ]
                for rid in self.index.ids
            ]
        self.groups = {r.recipe_id: _group_key(r) for r in pack.recipes}

    def top5(self, pantry: set[str], gold_group: str) -> dict[str, list[str]]:
        ix = self.index
        held = {i for i in pantry if i in self.pack.ingredients} - ix.staples
        hit: dict[int, set[int]] = {}
        for i in held:
            for r, li in ix.by_id.get(i, ()):
                hit.setdefault(r, set()).add(li)
        rows: dict[str, list[tuple]] = {k: [] for k in ("shipped", *VARIANTS)}
        for r in sorted(hit):
            rid = ix.ids[r]
            lines = sorted(hit[r])
            have, total = len(lines), ix.total[r]
            miss = total - have
            if miss > MAX_MISSING or self.groups[rid] == gold_group:
                continue
            rows["grouped_overlap"].append((miss, -have, total, rid))
            for wname in ("shipped", "smooth", "lucene"):
                ws = self.w[wname][r]
                m = sum(ws[li] for li in lines)
                t = sum(ws)
                s = m / math.sqrt(t) if t > 0 else 0.0
                if wname == "shipped":
                    rows["shipped"].append((miss, -s, total, rid))
                    rows["shipped_b0"].append((miss, -m, total, rid))
                    rows["shipped_b1"].append((miss, -(m / t if t > 0 else 0.0), total, rid))
                    rows["shipped_missmass"].append((miss, t - m, -s, total, rid))
                else:
                    rows["idf_" + wname].append((miss, -s, total, rid))
        return {k: [x[-1] for x in sorted(v)[:TOP]] for k, v in rows.items()}


def top5_agreement(pack: Pack, items: list[dict]) -> dict[str, dict[str, float]]:
    """Per variant: share of pantries with the identical (ordered) top 5 as ``shipped``,
    and the mean share of the 5 ids that match as a set."""
    sc = VariantScorer(pack)
    same = dict.fromkeys(VARIANTS, 0)
    shared = dict.fromkeys(VARIANTS, 0)
    for it in items:
        t = sc.top5(set(it["pantry"].pantry), it["title_group"])
        for v in VARIANTS:
            same[v] += t[v] == t["shipped"]
            shared[v] += len(set(t[v]) & set(t["shipped"]))
    n = len(items)
    return {
        v: {"identical": same[v] / n, "mean_shared": shared[v] / n / TOP, "n": n} for v in VARIANTS
    }
