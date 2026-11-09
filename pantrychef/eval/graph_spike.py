"""ADR 0006 graph spike (M3 Task 8): one-step edge traversal, blind sample, scoring and freeze.

Design: ``docs/research/2026-11-m3/graph_spike_design.md``. The spike is offline and in Python.
It adds no edge logic to ``engine.py``: the ``graph`` arm calls the same ``answer()`` with the
pantry ``ids ∪ up(ids − staples)``. The ``flat`` arm calls it with ``ids``.

Edges go from the row to the value in its ``is_a`` or ``form_of`` cell. Traversal is forward only
(specific to general). The rater never sees an id, an edge, an arm or a weight.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from pantrychef.engine import AnswerRequest, Pack, _needed, answer, load_pack, resolve_names
from pantrychef.eval.stats import paired_cluster_bootstrap, wilson
from pantrychef.ingredients.table import IngredientTable

EDGE_TYPES = ("is_a", "form_of")
MAX_HOPS = 3  # MEASURED max depth is 1; the cap only matters if Task 5 adds chains
GROUP_RANK = {"make_now": 0, "one_away": 1, "two_away": 2}  # absent = 3
SAMPLED_GROUPS = ("make_now", "one_away")
CLAIM = {"make_now": "make now", "one_away": "one away"}
ANSWERS = ("yes", "no", "unsure")

Edge = tuple[str, str, str]  # (from, type, to)

# Plan values (design section 3, row "plan") and the owner-confirmed thresholds (section 4.5).
PLAN = {
    "seed": 46,
    "max_hops": MAX_HOPS,
    "cap_new": 100,
    "split": {"make_now": 50, "one_away": 50},
    "repeats": 10,
    "repeat_min_gap": 20,
    "sessions": 3,
    "bootstrap_resamples": 10_000,
    "allocation_rule": "equal_shares_over_signature_strata_borrow_across_groups",
    "decoy_rule": "same_pantry_same_group_hash_order_fallback_all_pantries",
    "repeat_placement_rule": "next_session_hash_place_min_gap_moved_away",
}
THRESHOLDS = {
    "T1": {"min_correct": 5, "min_pantries": 3},  # each edge type, in correct rated new items
    "T2": {"min_lower_bound": 0.0},  # decision lower bound must be above this
    "T3": {"form": "wilson_lb", "min_rated": 20, "point_min": 0.90, "wilson_lb_min": 0.80},
    "guard": {"new_mean_max": 0.0, "new_precision_min": 0.85},
    "unsure_is_wrong": True,
    "new_subset_guard": True,
    "confirmed_by": "owner",
    "confirmed_on": "2026-11-09",
}

# ------------------------------------------------------------------------------ traversal


def edge_list(table: IngredientTable) -> list[Edge]:
    """Every ``(from, type, to)`` of the table, sorted. A cell ``a|b`` gives two edges."""
    return sorted(
        {
            (r.id, kind, target)
            for r in table.rows
            for kind, targets in (("is_a", r.is_a), ("form_of", r.form_of))
            for target in targets
        }
    )


def edges_in_use(edges: list[Edge], option: str, labels: dict | None) -> list[Edge]:
    """Option ``a``: all edges. Option ``b``: only edges the labels mark ``usable``.

    Under ``b`` every edge needs a label. A missing label is an error, not a silent drop.
    """
    if option == "a":
        return list(edges)
    if option != "b":
        raise ValueError(f"edge option must be 'a' or 'b', got {option!r}")
    if labels is None:
        raise ValueError("option b needs the edge labels")
    by_edge = {(x["from"], x["type"], x["to"]): x["label"] for x in labels["edges"]}
    missing = [e for e in edges if e not in by_edge]
    if missing:
        raise ValueError(f"option b: no label for {len(missing)} edge(s), first {missing[0]}")
    return [e for e in edges if by_edge[e] == "usable"]


def _adjacency(edges: list[Edge]) -> dict[str, list[Edge]]:
    adj: dict[str, list[Edge]] = {}
    for e in edges:
        adj.setdefault(e[0], []).append(e)
    return adj


def _paths(
    adj: dict[str, list[Edge]], item: str, max_hops: int
) -> dict[str, list[tuple[Edge, ...]]]:
    """Ancestor id -> every forward path of 1..max_hops hops from ``item``."""
    out: dict[str, list[tuple[Edge, ...]]] = {}

    def walk(node: str, path: tuple[Edge, ...], seen: frozenset[str]) -> None:
        if len(path) == max_hops:
            return
        for e in adj.get(node, ()):
            if e[2] in seen:
                continue
            nxt = (*path, e)
            out.setdefault(e[2], []).append(nxt)
            walk(e[2], nxt, seen | {e[2]})

    walk(item, (), frozenset({item}))
    return out


def max_depth(edges: list[Edge]) -> int:
    """Number of edges on the longest forward path. No edges give 0."""
    adj = _adjacency(edges)
    memo: dict[str, int] = {}

    def depth(node: str, stack: frozenset[str]) -> int:
        if node in stack:
            raise ValueError(f"cycle through {node!r}")
        if node not in memo:
            memo[node] = max(
                (1 + depth(e[2], stack | {node}) for e in adj.get(node, ())), default=0
            )
        return memo[node]

    return max((depth(n, frozenset()) for n in list(adj)), default=0)


def up(edges: list[Edge], item: str, max_hops: int = MAX_HOPS) -> dict[str, frozenset[Edge]]:
    """Ancestor id -> edges seen on any forward path of 1..max_hops hops."""
    paths = _paths(_adjacency(edges), item, max_hops)
    return {anc: frozenset(e for p in ps for e in p) for anc, ps in paths.items()}


def expand(edges: list[Edge], pantry: set[str], staples: set[str]) -> set[str]:
    """``pantry ∪ up(pantry − staples)``. A staple is never expanded."""
    adj = _adjacency(edges)
    out = set(pantry)
    for x in pantry - staples:
        out |= set(_paths(adj, x, MAX_HOPS))
    return out


# ------------------------------------------------------------------------------ arms and diff


def placements(pack: Pack, ids: list[str]) -> dict[str, str]:
    """recipe_id -> group name for the shipped ``answer()``, with no group cut."""
    got = answer(
        pack,
        AnswerRequest(pantry=list(ids), staples=pack.default_staples, limit=len(pack.recipes)),
    )
    return {r.recipe_id: g for g, grp in got.groups.items() for r in grp.items}


@dataclass(frozen=True)
class NewItem:
    pantry_id: str
    recipe_id: str
    group: str  # graph arm
    flat_group: str | None  # flat arm, None when the recipe is in no group
    signature: tuple[str, ...]  # sorted edge types over the newly met lines
    edges: tuple[Edge, ...]  # sorted edges on those paths
    hops: int  # the longest, over the newly met lines, of the shortest path to the line


@dataclass(frozen=True)
class SheetItem:
    item_id: str
    session: int
    pantry_id: str
    recipe_id: str
    group: str
    kind: str  # "new" or "decoy"
    weight: float  # 0.0 for a decoy
    signature: tuple[str, ...]
    edges: tuple[Edge, ...]
    hops: int
    flat_group: str | None
    repeat_of: str | None


def _rank(group: str | None) -> int:
    return GROUP_RANK.get(group, 3)  # type: ignore[arg-type]


def diff(
    pack: Pack, edges: list[Edge], pantry_id: str, ids: list[str]
) -> tuple[list[NewItem], dict[str, list[str]]]:
    """New items of one pantry, and its decoy candidates per group.

    A new item is in ``make_now`` or ``one_away`` for ``graph`` and in a worse place (or none) for
    ``flat``. A decoy candidate is in the same one of those two groups for both arms.
    """
    staples = set(pack.default_staples)
    held = set(ids) - staples
    flat = placements(pack, ids)
    graph = placements(pack, sorted(expand(edges, set(ids), staples)))
    adj = _adjacency(edges)
    paths = {x: _paths(adj, x, MAX_HOPS) for x in held}
    by_id = {r.recipe_id: r for r in pack.recipes}
    new: list[NewItem] = []
    decoys: dict[str, list[str]] = {g: [] for g in SAMPLED_GROUPS}
    for rid in sorted(graph):
        g, f = graph[rid], flat.get(rid)
        if g not in SAMPLED_GROUPS:
            continue
        if f == g:
            decoys[g].append(rid)
            continue
        if _rank(f) < _rank(g):  # cannot happen (monotone); fail loudly if it ever does
            raise AssertionError(f"traversal made {rid} worse for {pantry_id}")
        types: set[str] = set()
        used: set[Edge] = set()
        hops = 0
        for ln in _needed(by_id[rid], staples):
            if any(o in held for o in ln.options):
                continue  # met without an edge: not part of the signature
            best = None
            for x in held:
                for o in ln.options:
                    for p in paths[x].get(o, ()):
                        used.update(p)
                        types.update(e[1] for e in p)
                        best = len(p) if best is None else min(best, len(p))
            if best is not None:
                hops = max(hops, best)
        new.append(NewItem(pantry_id, rid, g, f, tuple(sorted(types)), tuple(sorted(used)), hops))
    return new, decoys


def build_pool(
    pack: Pack, edges: list[Edge], pantry_ids: dict[str, list[str]]
) -> tuple[list[NewItem], dict[str, dict[str, list[str]]]]:
    """New items over all pantries, and decoy candidates per pantry and group."""
    pool: list[NewItem] = []
    decoys: dict[str, dict[str, list[str]]] = {}
    for pid in sorted(pantry_ids):
        new, dec = diff(pack, edges, pid, pantry_ids[pid])
        pool += new
        decoys[pid] = dec
    return pool, decoys


def stratum_name(group: str, signature: tuple[str, ...]) -> str:
    return f"{group}|{'+'.join(signature)}"


def pool_counts(pool: list[NewItem], decoys: dict[str, dict[str, list[str]]]) -> dict:
    """Counts only: new items per group and signature, and decoy candidates per group."""
    new: dict[str, int] = {}
    for i in pool:
        k = stratum_name(i.group, i.signature)
        new[k] = new.get(k, 0) + 1
    cand = {g: sum(len(d.get(g, ())) for d in decoys.values()) for g in SAMPLED_GROUPS}
    return {"new": dict(sorted(new.items())), "decoy_candidates": cand}


def pool_by_edge(pool: list[NewItem], top: int = 10) -> list[list]:
    """The ``top`` edges in use with the most new items: ``[from, type, to, count]``."""
    counts: dict[Edge, int] = {}
    for i in pool:
        for e in i.edges:
            counts[e] = counts.get(e, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return [[*e, n] for e, n in ranked]


def edge_source_hits(pack: Pack, edges: list[Edge], pantries: dict[str, dict]) -> dict:
    """Pantry names that resolve to the source of an edge in use, for ``pilot`` and ``new``."""
    sources = {e[0] for e in edges}
    by_pantry: dict[str, int] = {}
    out = {"pilot": 0, "new": 0}
    for pid in sorted(pantries):
        n = 0
        for name in pantries[pid]["names"]:
            ids, _ = resolve_names(pack, [name])
            n += bool(sources & set(ids))
        by_pantry[pid] = n
        out[pantries[pid]["set"]] += n
    return {**out, "by_pantry": by_pantry}


# ------------------------------------------------------------------------------ draw


def _h(seed: int, tag: str, *parts: str) -> str:
    return hashlib.sha256(f"{seed}:{tag}:{':'.join(parts)}".encode()).hexdigest()


def _alloc(sizes: dict[str, int], total: int) -> dict[str, int]:
    """Equal shares over the non-empty strata. A small stratum gives all, the rest is shared."""
    take: dict[str, int] = {}
    active = sorted(k for k, n in sizes.items() if n > 0)
    left = min(total, sum(sizes.values()))
    while active and left > 0:
        base, extra = divmod(left, len(active))
        share = {k: base + (1 if i < extra else 0) for i, k in enumerate(active)}
        full = [k for k in active if sizes[k] <= share[k]]
        if not full:
            take.update(share)
            break
        for k in full:
            take[k] = sizes[k]
            left -= sizes[k]
        active = [k for k in active if k not in full]
    return take


def _sample_new(pool: list[NewItem], seed: int, cap: int) -> list[tuple[NewItem, float]]:
    half = cap // 2
    by_group = {g: [i for i in pool if i.group == g] for g in SAMPLED_GROUPS}
    quota = {g: min(half, len(v)) for g, v in by_group.items()}
    spare = cap - sum(quota.values())
    for g in SAMPLED_GROUPS:  # a small group hands its unused share to the other group
        extra = min(len(by_group[g]) - quota[g], spare)
        quota[g] += extra
        spare -= extra
    out: list[tuple[NewItem, float]] = []
    for g in SAMPLED_GROUPS:
        strata: dict[tuple[str, ...], list[NewItem]] = {}
        for i in by_group[g]:
            strata.setdefault(i.signature, []).append(i)
        names = {"+".join(sig): sig for sig in strata}
        take = _alloc({n: len(strata[sig]) for n, sig in names.items()}, quota[g])
        for n, k in take.items():
            members = sorted(
                strata[names[n]], key=lambda i: _h(seed, "new", i.pantry_id, i.recipe_id)
            )
            out += [(i, len(members) / k) for i in members[:k]]
    return out


def _pick_decoys(
    sampled: list[tuple[NewItem, float]],
    pool: list[NewItem],
    decoys: dict[str, dict[str, list[str]]],
    seed: int,
) -> list[tuple[str, str, str]]:
    """One decoy ``(pantry_id, recipe_id, group)`` per sampled new item, from the same group."""
    is_new = {(i.pantry_id, i.recipe_id) for i in pool}
    used: set[tuple[str, str]] = set()
    everywhere: dict[str, list[tuple[str, str]]] = {}
    out = []
    order = sorted(sampled, key=lambda s: _h(seed, "new", s[0].pantry_id, s[0].recipe_id))
    for item, _ in order:
        g = item.group
        own = [(item.pantry_id, r) for r in decoys.get(item.pantry_id, {}).get(g, ())]
        if g not in everywhere:
            everywhere[g] = sorted(
                ((p, r) for p, d in decoys.items() for r in d.get(g, ())),
                key=lambda pr: _h(seed, "decoy", *pr),
            )
        for cands in (sorted(own, key=lambda pr: _h(seed, "decoy", *pr)), everywhere[g]):
            pick = next((c for c in cands if c not in used and c not in is_new), None)
            if pick:
                break
        else:
            raise ValueError(f"not enough decoy candidates in group {g}")
        used.add(pick)
        out.append((*pick, g))
    return out


def draw(
    pool: list[NewItem],
    decoys: dict[str, dict[str, list[str]]],
    seed: int,
    cap: int = PLAN["cap_new"],
    sessions: int = PLAN["sessions"],
    repeats: int = PLAN["repeats"],
    min_gap: int = PLAN["repeat_min_gap"],
) -> list[SheetItem]:
    """The blind sample: stratified new items, matching decoys, sessions and unmarked repeats."""
    if not pool:
        return []
    if sessions < 2:
        raise ValueError("repeats need at least 2 sessions")
    sampled = _sample_new(pool, seed, cap)
    base: list[dict] = [
        {
            "pantry_id": i.pantry_id, "recipe_id": i.recipe_id, "group": i.group, "kind": "new",
            "weight": w, "signature": i.signature, "edges": i.edges, "hops": i.hops,
            "flat_group": i.flat_group,
        }
        for i, w in sampled
    ]  # fmt: skip
    for pid, rid, g in _pick_decoys(sampled, pool, decoys, seed):
        base.append(
            {
                "pantry_id": pid, "recipe_id": rid, "group": g, "kind": "decoy", "weight": 0.0,
                "signature": (), "edges": (), "hops": 0, "flat_group": g,
            }
        )  # fmt: skip
    base.sort(key=lambda b: _h(seed, "order", b["pantry_id"], b["recipe_id"]))

    n = len(base)
    cuts = [n // sessions + (1 if s < n % sessions else 0) for s in range(sessions)]
    lists: list[list[list]] = []  # entry = [base index, original base index or None]
    start = 0
    for c in cuts:
        lists.append([[k, None] for k in range(start, start + c)])
        start += c
    session_of = {e[0]: s for s, lst in enumerate(lists) for e in lst}

    def rep_key(k: int) -> str:
        return _h(seed, "repeat", base[k]["pantry_id"], base[k]["recipe_id"])

    chosen: list[int] = []
    for kind, count in (("new", repeats // 2), ("decoy", repeats - repeats // 2)):
        pick = sorted((k for k in range(n) if base[k]["kind"] == kind), key=rep_key)
        chosen += pick[:count]
    for k in sorted(chosen, key=rep_key):
        s = session_of[k]
        t = (s + 1) % sessions
        lst = lists[t]
        offset = sum(len(x) for x in lists[:t])
        flat = [e[0] if e[1] is None else None for x in lists for e in x]
        orig = flat.index(k)
        pos = int(rep_key(k), 16) % (len(lst) + 1)
        candidates = range(pos, len(lst) + 1) if t > s else range(pos, -1, -1)
        place = pos
        for place in candidates:
            at = offset + place
            gap = at - orig if t > s else orig + 1 - at
            if gap >= min_gap:
                break
        lst.insert(place, [k, k])  # best effort when the sessions are too short for the gap

    ids: dict[tuple[int, bool], str] = {}
    order: list[tuple[int, list]] = []
    for s, lst in enumerate(lists):
        for e in lst:
            order.append((s, e))
    for pos, (_, e) in enumerate(order):
        ids[(e[0], e[1] is not None)] = f"g{pos + 1:03d}"
    items = []
    for s, e in order:
        b = base[e[0]]
        repeat = ids[(e[0], False)] if e[1] is not None else None
        items.append(SheetItem(item_id=ids[(e[0], e[1] is not None)], session=s + 1,
                               repeat_of=repeat, **b))  # fmt: skip
    return items


def repeat_gaps(items: list[SheetItem]) -> list[int]:
    """Distance in places between each repeat and its original."""
    pos = {i.item_id: k for k, i in enumerate(items)}
    return sorted(abs(pos[i.item_id] - pos[i.repeat_of]) for i in items if i.repeat_of)


# ------------------------------------------------------------------------------ sheet and key

SHEET_COLUMNS = (
    "item_id", "session", "pantry", "staples", "title", "lines", "claim", "missing_line",
    "answer", "unmet_lines", "seconds", "note",
)  # fmt: skip


def sheet_rows(items: list[SheetItem], pack: Pack, pantries: dict, edges: list[Edge]) -> list[dict]:
    """Rows with the columns of design 4.2 only. ``pantries``: id -> ``{"names", "ids"}``."""
    staples = set(pack.default_staples)
    by_id = {r.recipe_id: r for r in pack.recipes}
    staple_names = "; ".join(pack.ingredients[i].name for i in pack.default_staples)
    rows = []
    for it in items:
        recipe = by_id[it.recipe_id]
        p = pantries[it.pantry_id]
        held = expand(edges, set(p["ids"]), staples)
        missing = [ln for ln in _needed(recipe, staples) if not any(o in held for o in ln.options)]
        if len(missing) != {"make_now": 0, "one_away": 1}[it.group]:
            raise ValueError(f"claim of {it.pantry_id}/{it.recipe_id} does not match the engine")
        rows.append(
            {
                "item_id": it.item_id,
                "session": it.session,
                "pantry": "; ".join(p["names"]),
                "staples": staple_names,
                "title": recipe.title,
                "lines": "\n".join(f"{n}. {ln.text}" for n, ln in enumerate(recipe.lines, 1)),
                "claim": CLAIM[it.group],
                "missing_line": missing[0].text if missing else "",
                "answer": "",
                "unmet_lines": "",
                "seconds": "",
                "note": "",
            }
        )
    return rows


def make_key(items: list[SheetItem], pool: list[NewItem], sets: dict[str, str], seed: int) -> dict:
    """The private key: everything the rater must not see. Plain JSON."""
    pool_n: dict[str, int] = {}
    for i in pool:
        k = stratum_name(i.group, i.signature)
        pool_n[k] = pool_n.get(k, 0) + 1
    return {
        "version": 1,
        "seed": seed,
        "pantries": dict(sorted(sets.items())),
        "pool": dict(sorted(pool_n.items())),
        "items": {
            i.item_id: {
                "pantry_id": i.pantry_id,
                "recipe_id": i.recipe_id,
                "group": i.group,
                "kind": i.kind,
                "weight": i.weight,
                "signature": list(i.signature),
                "edges": [list(e) for e in i.edges],
                "hops": i.hops,
                "flat_group": i.flat_group,
                "repeat_of": i.repeat_of,
                "session": i.session,
            }
            for i in items
        },
    }


# ------------------------------------------------------------------------------ statistics


def _betacf(a: float, b: float, x: float) -> float:
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 500):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        c = 1.0 + aa / c
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        c = 1.0 + aa / c
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_critical(df: int, level: float = 0.95) -> float:
    """Two-sided Student t critical value. No SciPy: it is an optional extra of this project."""
    if df < 1:
        raise ValueError("df must be at least 1")
    target = 1.0 - (1.0 - level) / 2.0
    lo, hi = 0.0, 1e5
    for _ in range(200):
        mid = (lo + hi) / 2.0
        cdf = 1.0 - 0.5 * _betainc(df / 2.0, 0.5, df / (df + mid * mid))
        if cdf < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _t_interval(vals: list[float]) -> tuple[float, float]:
    n = len(vals)
    mean = sum(vals) / n
    if n < 2:
        return mean, mean
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
    half = t_critical(n - 1) * sd / math.sqrt(n)
    return mean - half, mean + half


def _net(rated: list[dict], pantry_ids: list[str], seed: int, resamples: int) -> dict | None:
    if not pantry_ids:
        return None
    d = dict.fromkeys(pantry_ids, 0.0)
    seen: set[str] = set()
    for r in rated:
        if r["kind"] == "new" and r["pantry_id"] in d:
            d[r["pantry_id"]] += r["weight"] * (1 if r["correct"] else -1)
            seen.add(r["pantry_id"])
    vals = [d[p] for p in pantry_ids]
    iv = paired_cluster_bootstrap(
        vals, [0.0] * len(vals), pantry_ids, resamples=resamples, seed=seed
    )
    t_lo, t_hi = _t_interval(vals)
    return {
        "n_pantries": len(vals),
        "mean": sum(vals) / len(vals),
        "boot_lo": iv.lo,
        "boot_hi": iv.hi,
        "t_lo": t_lo,
        "t_hi": t_hi,
        "decision_lo": min(iv.lo, t_lo),
        "pantries_positive": sum(v > 0 for v in vals),
        "pantries_negative": sum(v < 0 for v in vals),
        "pantries_with_new": len(seen),
    }


def _precision(rated: list[dict], group: str) -> dict:
    new = [r for r in rated if r["kind"] == "new" and r["group"] == group]
    dec = [r for r in rated if r["kind"] == "decoy" and r["group"] == group]
    wsum = sum(r["weight"] for r in new)
    k = sum(r["correct"] for r in new)
    lo, hi = wilson(k, len(new)) if new else (None, None)
    return {
        "weighted": sum(r["weight"] for r in new if r["correct"]) / wsum if wsum > 0 else None,
        "n": len(new),
        "wilson_lo": lo,
        "wilson_hi": hi,
        "decoy_precision": sum(r["correct"] for r in dec) / len(dec) if dec else None,
        "decoy_n": len(dec),
    }


def _figures(rated: list[dict], pantry_ids: list[str], pool: dict, seed: int, resamples: int):
    new = [r for r in rated if r["kind"] == "new"]
    strata = []
    for name in sorted(set(pool) | {stratum_name(r["group"], r["signature"]) for r in new}):
        group, _, sig = name.partition("|")
        members = [r for r in new if stratum_name(r["group"], r["signature"]) == name]
        p = _precision(
            [{**r, "group": "x"} for r in members], "x"
        )  # reuse: one stratum as one group
        pool_n = pool.get(name, 0)
        strata.append(
            {"group": group, "signature": sig, "weighted": p["weighted"], "n": p["n"],
             "wilson_lo": p["wilson_lo"], "wilson_hi": p["wilson_hi"], "pool_n": pool_n,
             "mode": "census" if p["n"] == pool_n else "sample"}
        )  # fmt: skip
    edge_types = {}
    for t in EDGE_TYPES:
        hit = [r for r in new if t in r["signature"]]
        good = [r for r in hit if r["correct"]]
        edge_types[t] = {
            "correct": len(good),
            "wrong": len(hit) - len(good),
            "pantries": len({r["pantry_id"] for r in hit}),
            "correct_pantries": len({r["pantry_id"] for r in good}),
        }
    per_edge: dict[tuple, list[int]] = {}
    for r in new:
        for e in r["edges"]:
            per_edge.setdefault(e, [0, 0])[0 if r["correct"] else 1] += 1
    return {
        "net_new_per_pantry": _net(rated, pantry_ids, seed, resamples),
        "precision": {g: _precision(rated, g) for g in SAMPLED_GROUPS},
        "strata": strata,
        "edge_types": edge_types,
        "edges": [
            {"from": e[0], "type": e[1], "to": e[2], "correct": c[0], "wrong": c[1]}
            for e, c in sorted(per_edge.items())
        ],
    }


def score(
    key: dict,
    answers: list[dict],
    thresholds: dict,
    seed: int,
    resamples: int = PLAN["bootstrap_resamples"],
) -> dict:
    """Score the rated sheet. ``unsure`` and ``no`` are wrong. Raises on a bad answers file."""
    if not thresholds.get("unsure_is_wrong", False):
        raise ValueError("only unsure_is_wrong = true is supported")
    items = key["items"]
    new_in_pool = sum(key["pool"].values())
    if not new_in_pool and not any(v["kind"] == "new" for v in items.values()):
        return {"verdict": "rejected", "reason": "no_new_recipes", "checks": {}}
    got: dict[str, str] = {}
    for a in answers:
        iid = a["item_id"]
        if iid not in items:
            raise ValueError(f"unknown item_id {iid!r}")
        if iid in got:
            raise ValueError(f"item_id {iid!r} answered twice")
        ans = str(a.get("answer", "")).strip().lower()
        if ans not in ANSWERS:
            raise ValueError(f"item {iid!r}: answer must be one of {ANSWERS}, got {ans!r}")
        got[iid] = ans
    missing = sorted(set(items) - set(got))
    if missing:
        raise ValueError(f"missing answers for {len(missing)} item(s), first {missing[0]!r}")

    rated = [
        {
            **v,
            "signature": tuple(v["signature"]),
            "edges": [tuple(e) for e in v["edges"]],
            "correct": got[iid] == "yes",
            "set": key["pantries"].get(v["pantry_id"]),
        }
        for iid, v in items.items()
        if v["repeat_of"] is None
    ]
    sets = key["pantries"]
    ids = {s: sorted(p for p, x in sets.items() if x == s) for s in ("pilot", "new")}
    all_ids = sorted(sets)
    pool = key["pool"]
    full = _figures(rated, all_ids, pool, seed, resamples)
    split = {
        s: _figures([r for r in rated if r["set"] == s], ids[s], pool, seed, resamples)
        for s in ("pilot", "new")
    }

    pairs = [(iid, v["repeat_of"]) for iid, v in items.items() if v["repeat_of"]]
    agree = sum((got[a] == "yes") == (got[b] == "yes") for a, b in pairs)
    new_rated = [r for r in rated if r["kind"] == "new"]

    t1, t2, t3, tg = (thresholds[k] for k in ("T1", "T2", "T3", "guard"))
    checks = {
        "T1": all(
            full["edge_types"][t]["correct"] >= t1["min_correct"]
            and full["edge_types"][t]["correct_pantries"] >= t1["min_pantries"]
            for t in EDGE_TYPES
        ),
        "T2": full["net_new_per_pantry"]["decision_lo"] > t2["min_lower_bound"],
        "T3": all(_t3_ok(full["precision"][g], t3) for g in SAMPLED_GROUPS),
    }
    verdict_checks = {k: ("pass" if v else "fail") for k, v in checks.items()}
    if thresholds.get("new_subset_guard"):
        n = split["new"]
        bad = (
            n["net_new_per_pantry"] is None or n["net_new_per_pantry"]["mean"] <= tg["new_mean_max"]
        )
        bad = bad or any(
            n["precision"][g]["weighted"] is None
            or n["precision"][g]["weighted"] < tg["new_precision_min"]
            for g in SAMPLED_GROUPS
        )
        verdict_checks["guard"] = "fail" if bad else "pass"
    else:
        verdict_checks["guard"] = "skipped"
    failed = [k for k in ("T1", "T2", "T3") if verdict_checks[k] == "fail"]
    if failed:
        verdict = "rejected"
    elif verdict_checks["guard"] == "fail":
        verdict = "exploration"
    else:
        verdict = "accepted"
    hops: dict[str, int] = {}
    for r in new_rated:
        hops[str(r["hops"])] = hops.get(str(r["hops"]), 0) + 1
    return {
        **full,
        "split_report": split,
        "repeat_agreement": {
            "pairs": len(pairs),
            "agree": agree,
            "rate": agree / len(pairs) if pairs else None,
        },
        "hops": dict(sorted(hops.items())),
        "rated": {
            "new": len(new_rated),
            "decoys": sum(r["kind"] == "decoy" for r in rated),
            "repeats": len(pairs),
        },
        "checks": verdict_checks,
        "failed": failed,
        "verdict": verdict,
        "reason": None,
    }


def _t3_ok(p: dict, t3: dict) -> bool:
    if p["n"] < t3["min_rated"]:
        return False
    if t3["form"] == "point":
        return p["weighted"] is not None and p["weighted"] >= t3["point_min"]
    if t3["form"] == "wilson_lb":
        return p["wilson_lo"] is not None and p["wilson_lo"] >= t3["wilson_lb_min"]
    raise ValueError(f"unknown T3 form {t3['form']!r}")


# ------------------------------------------------------------------------------ freeze

GRAPH_DIR = "data/eval/graph_spike"
TABLE_NAME = "table.frozen.csv"
PANTRIES_NAME = "pantries.v1.json"
LABELS_NAME = "edge_labels.v1.json"
FREEZE_NAME = "freeze.v1.json"
WORDS_REL = "data/ingredients/words.v1.json"
ALLOWLIST_REL = "pantrychef/pack/allowlist.json"
CODE_GLOBS = (
    "pantrychef/eval/graph_spike.py",
    "pantrychef/engine.py",
    "pantrychef/ingredients/*.py",
    "pantrychef/pack/build.py",
)
CHECKED_FIELDS = (
    "table_sha256", "words_sha256", "snapshot_sha256", "code_sha256", "edges", "edges_sha256",
    "edge_labels_sha256", "owner_edits", "edges_in_use", "max_depth_observed", "pantries_sha256",
)  # fmt: skip


def sha256_lf(path: Path) -> str:
    """sha256 of a text file with CRLF changed to LF, so Windows and CI agree."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def sha256_raw(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _jsha(obj: object) -> str:
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _code_files(root: Path) -> list[str]:
    found: set[str] = set()
    for pattern in CODE_GLOBS:
        found |= {p.relative_to(root).as_posix() for p in root.glob(pattern) if p.is_file()}
    return sorted(found)


def snapshot_entry(root: Path) -> tuple[Path, str]:
    """The pinned snapshot path and its ``retrieved_on``, from the pack allow-list."""
    entry = json.loads((root / ALLOWLIST_REL).read_text(encoding="utf-8"))["inputs"]["snapshot"]
    path = Path(entry["path"])
    return (path if path.is_absolute() else root / path), entry.get("retrieved_on", "")


def _compute(root: Path, option: str, strict: bool) -> dict:
    """The fields of the manifest that come from files. ``strict`` False gives None on a failure."""
    g = root / GRAPH_DIR

    def safe(fn):
        if strict:
            return fn()
        try:
            return fn()
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return None

    out: dict = {
        "table_sha256": safe(lambda: sha256_lf(g / TABLE_NAME)),
        "words_sha256": safe(lambda: sha256_lf(root / WORDS_REL)),
        "snapshot_sha256": safe(lambda: sha256_raw(snapshot_entry(root)[0])),
        "code_sha256": safe(lambda: {rel: sha256_lf(root / rel) for rel in _code_files(root)}),
    }

    def edge_fields() -> dict:
        table = IngredientTable.from_text(
            (g / TABLE_NAME).read_bytes().decode("utf-8").replace("\r\n", "\n"),
            (root / WORDS_REL).read_text(encoding="utf-8"),
        )
        edges = edge_list(table)
        fields: dict = {"edges": [list(e) for e in edges], "edges_sha256": _jsha(edges)}
        labels = None
        if option == "b":
            labels = json.loads((g / LABELS_NAME).read_text(encoding="utf-8"))
            fields["edge_labels_sha256"] = sha256_lf(g / LABELS_NAME)
            fields["owner_edits"] = labels.get("owner_edits", [])
        used = edges_in_use(edges, option, labels)
        fields["edges_in_use"] = {
            "edges": [list(e) for e in used],
            "sha256": _jsha(used),
            "count_per_type": {t: sum(e[1] == t for e in used) for t in EDGE_TYPES},
        }
        fields["max_depth_observed"] = max_depth(used)
        return fields

    fields = safe(edge_fields)
    if fields is None:
        fields = dict.fromkeys(
            ("edges", "edges_sha256", "edges_in_use", "max_depth_observed")
            + (("edge_labels_sha256", "owner_edits") if option == "b" else ()),
        )
    out.update(fields)
    out["pantries_sha256"] = safe(lambda: sha256_lf(g / PANTRIES_NAME))
    return out


def freeze_manifest(
    root: Path, plan: dict, thresholds: dict, option: str, extras: dict | None = None
) -> dict:
    """The manifest of ``freeze.v1.json``. ``root`` is the repository root."""
    fields = _compute(Path(root), option, strict=True)
    return {
        "version": 1,
        **{k: fields[k] for k in CHECKED_FIELDS if k in fields},
        "edge_option": {
            "option": option,
            "confirmed_by": thresholds["confirmed_by"],
            "confirmed_on": thresholds["confirmed_on"],
        },
        "plan": plan,
        "thresholds": thresholds,
        **(extras or {}),
    }


def check_freeze(path: Path, repo_root: Path | None = None) -> list[str]:
    """Recompute every hash and return the names of the fields that differ. Empty means intact."""
    path = Path(path)
    root = Path(repo_root) if repo_root is not None else path.resolve().parents[3]
    stored = json.loads(path.read_text(encoding="utf-8"))
    fresh = _compute(root, stored["edge_option"]["option"], strict=False)
    return [
        k for k in CHECKED_FIELDS if (k in fresh or k in stored) and stored.get(k) != fresh.get(k)
    ]


# ------------------------------------------------------------------------------ inputs


def load_pantries(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve_pantries(pack: Pack, doc: dict) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """Resolve the typed names. Return ``({id: names, ids, set}, {id: unknown names})``."""
    out: dict[str, dict] = {}
    unknown: dict[str, list[str]] = {}
    for p in doc["pantries"]:
        ids, bad = resolve_names(pack, p["names"])
        out[p["id"]] = {
            "names": list(p["names"]),
            "ids": ids,
            "set": "pilot" if p["id"].startswith("pilot") else "new",
        }
        if bad:
            unknown[p["id"]] = bad
    return out, unknown


def build_frozen_pack(root: Path, out_dir: Path) -> Pack:
    """Build the pack in ``out_dir`` from the frozen table and the pinned snapshot."""
    from pantrychef.pack.build import build_pack

    root, out_dir = Path(root), Path(out_dir)
    snap, retrieved_on = snapshot_entry(root)
    inputs = {
        "snapshot": {
            "path": str(snap),
            "sha256": sha256_raw(snap),
            "retrieved_on": retrieved_on,
        },
        "table": {
            "path": str(root / GRAPH_DIR / TABLE_NAME),
            "sha256": sha256_raw(root / GRAPH_DIR / TABLE_NAME),
        },
        "words": {"path": str(root / WORDS_REL), "sha256": sha256_raw(root / WORDS_REL)},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    allow = out_dir.parent / f"{out_dir.name}.allowlist.json"
    allow.write_text(json.dumps({"inputs": inputs}), encoding="utf-8")
    build_pack(allow, out_dir, repo_root=root, commit="frozen", dirty=False)
    return load_pack(out_dir)
