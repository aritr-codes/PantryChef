"""ADR 0006 graph spike: traversal, draw, sheet, scoring and freeze (M3 Task 8).

Every input is invented. The real pantries file is read by one test only, and only when it exists.
"""

from __future__ import annotations

import itertools
import json
import shutil
from pathlib import Path

import pytest

from pantrychef.engine import AnswerRequest, Pack, answer
from pantrychef.eval import graph_spike as gs
from pantrychef.eval.graph_spike import (
    GROUP_RANK,
    NewItem,
    check_freeze,
    diff,
    draw,
    edge_list,
    edges_in_use,
    expand,
    freeze_manifest,
    max_depth,
    placements,
    score,
    sheet_rows,
    up,
)
from pantrychef.eval.stats import wilson
from pantrychef.ingredients.table import DEFAULT_WORDS_PATH, IngredientTable

ROOT = Path(__file__).resolve().parents[2]
PANTRIES = ROOT / "data" / "eval" / "graph_spike" / "pantries.v1.json"

# ---------------------------------------------------------------- fixtures


def L(text, *opts, optional=False, read=True):
    return (text, opts, optional, read)


def make_pack(recipes, staples=("veg_oil",), extra_ids=()):
    """``recipes``: title -> lines of ``L(text, *option_ids)``. The recipe id is ``r-<title>``."""
    ids = sorted({o for ls in recipes.values() for _, opts, _, _ in ls for o in opts})
    ids = sorted(set(ids) | set(staples) | set(extra_ids))
    core = {
        "info": {"version": "t", "commit": "t", "corpus_fingerprint": "t"},
        "ingredients": [
            {"id": i, "name": i.replace("_", " ").title(), "staple": i in staples, "idf": 1.0}
            for i in ids
        ],
        "keys": {i.replace("_", " "): i for i in ids},
        "recipes": [
            {
                "id": f"r-{title}",
                "title": title,
                "page": f"Cookbook:{title}",
                "rev": 1,
                "lines": [
                    {"t": text, "o": list(opts), "opt": opt, "r": read}
                    for text, opts, opt, read in ls
                ],
            }
            for title, ls in recipes.items()
        ],
    }
    return Pack.from_core(core)


EDGES = sorted(
    [
        ("paneer", "is_a", "cheese"),
        ("garlic_paste", "form_of", "garlic"),
        ("ginger_garlic_paste", "form_of", "garlic"),
        ("ginger_garlic_paste", "form_of", "ginger"),
        ("veg_oil", "is_a", "fat"),
    ]
)
RECIPES = {
    "Cheese toast": [L("2 slices bread", "bread"), L("grated cheese", "cheese")],
    "Garlic soup": [L("3 cloves garlic", "garlic"), L("1 onion", "onion")],
    "Creamy dish": [L("cheese or cream", "cheese", "cream"), L("garlic", "garlic")],
    "Paneer curry": [L("200 g paneer", "paneer"), L("1 onion", "onion")],
    "Optional extra": [L("bread", "bread"), L("cheese, optional", "cheese", optional=True)],
    "Unread line": [L("cheese", "cheese"), L("a strange thing", read=False)],
    "Oil dish": [L("some fat", "fat"), L("1 onion", "onion")],
    "Ginger mix": [L("ginger", "ginger"), L("garlic", "garlic")],
}
SRC = ("garlic_paste", "ginger_garlic_paste")


@pytest.fixture(scope="module")
def pack():
    return make_pack(RECIPES, extra_ids=SRC)


def arms(pack, ids, edges=EDGES):
    staples = set(pack.default_staples)
    return placements(pack, ids), placements(pack, sorted(expand(edges, set(ids), staples)))


def rank(group):
    return GROUP_RANK.get(group, 3)


# ---------------------------------------------------------------- traversal


def test_up_follows_edges_forward():
    assert "cheese" in up(EDGES, "paneer")
    assert "paneer" not in up(EDGES, "cheese")
    assert up(EDGES, "paneer")["cheese"] == frozenset({("paneer", "is_a", "cheese")})


def test_reverse_direction_never_satisfies(pack):
    flat, graph = arms(pack, ["cheese", "onion"])
    assert flat["r-Paneer curry"] == graph["r-Paneer curry"] == "one_away"


def test_depth_limit():
    chain = [("a", "is_a", "b"), ("b", "is_a", "c"), ("c", "is_a", "d"), ("d", "is_a", "e")]
    assert set(up(chain, "a")) == {"b", "c", "d"}
    assert "e" not in up(chain, "a")
    assert set(up(chain, "a", max_hops=1)) == {"b"}


def test_mixed_edge_types_on_one_path():
    edges = [("x", "form_of", "y"), ("y", "is_a", "z")]
    assert up(edges, "x")["z"] == frozenset(edges)
    assert up(edges, "x")["y"] == frozenset({("x", "form_of", "y")})


TABLE_CSV = (
    "id,name,synonyms,staple,provenance,is_a,form_of\n"
    "salt,Salt,,1,hand,,\n"
    "black_pepper,Black pepper,,0,hand,,\n"
    "ginger,Ginger,,0,hand,,\n"
    "garlic,Garlic,,0,hand,,\n"
    "cheese,Cheese,,0,hand,,\n"
    "paneer,Paneer,,0,hand,cheese,\n"
    "ginger_garlic_paste,Ginger garlic paste,,0,hand,,ginger|garlic\n"
)


def test_multi_target_cell():
    table = IngredientTable.from_text(TABLE_CSV)
    assert edge_list(table) == [
        ("ginger_garlic_paste", "form_of", "garlic"),
        ("ginger_garlic_paste", "form_of", "ginger"),
        ("paneer", "is_a", "cheese"),
    ]


LABELS = {
    "edges": [
        {"from": "paneer", "type": "is_a", "to": "cheese", "label": "usable"},
        {"from": "garlic_paste", "type": "form_of", "to": "garlic", "label": "not usable"},
        {"from": "ginger_garlic_paste", "type": "form_of", "to": "garlic", "label": "usable"},
        {"from": "ginger_garlic_paste", "type": "form_of", "to": "ginger", "label": "usable"},
        {"from": "veg_oil", "type": "is_a", "to": "fat", "label": "not usable"},
    ]
}


def test_option_b_filters_edges():
    assert edges_in_use(EDGES, "a", None) == EDGES
    used = edges_in_use(EDGES, "b", LABELS)
    assert ("garlic_paste", "form_of", "garlic") not in used
    assert ("veg_oil", "is_a", "fat") not in used
    assert used == [e for e in EDGES if e[0] not in ("garlic_paste", "veg_oil")]
    with pytest.raises(ValueError):
        edges_in_use(EDGES, "b", None)
    with pytest.raises(ValueError, match="no label"):
        edges_in_use(EDGES, "b", {"edges": LABELS["edges"][:2]})
    with pytest.raises(ValueError):
        edges_in_use(EDGES, "c", None)


def _labels(**changes):
    rows = [dict(x) for x in LABELS["edges"]]
    rows[0].update(changes)
    return {"edges": rows}


def test_option_b_rejects_odd_labels_and_stray_edges():
    for odd in ("Usable", "usable ", "yes", "not_usable", ""):
        with pytest.raises(ValueError, match="usable"):
            edges_in_use(EDGES, "b", _labels(label=odd))
    extra = {"from": "x", "type": "is_a", "to": "y", "label": "usable"}
    with pytest.raises(ValueError, match="not in the table"):
        edges_in_use(EDGES, "b", {"edges": [*LABELS["edges"], extra]})


def test_option_b_rejects_a_label_listed_twice():
    twice = {"edges": [*LABELS["edges"], dict(LABELS["edges"][0], label="not usable")]}
    with pytest.raises(ValueError, match="twice"):
        edges_in_use(EDGES, "b", twice)


def test_option_b_checks_owner_edits_against_labels():
    edit = {"from": "paneer", "type": "is_a", "to": "cheese", "old_label": "not usable"}
    ok = {**LABELS, "owner_edits": [{**edit, "new_label": "usable"}]}
    assert ("paneer", "is_a", "cheese") in edges_in_use(EDGES, "b", ok)
    bad = {**LABELS, "owner_edits": [{**edit, "new_label": "not usable"}]}
    with pytest.raises(ValueError, match="owner edit"):
        edges_in_use(EDGES, "b", bad)
    gone = {**LABELS, "owner_edits": [{**edit, "from": "nothing", "new_label": "usable"}]}
    with pytest.raises(ValueError, match="owner edit"):
        edges_in_use(EDGES, "b", gone)


def test_max_depth():
    assert max_depth(EDGES) == 1
    assert max_depth([("a", "is_a", "b"), ("b", "is_a", "c")]) == 2
    assert max_depth([]) == 0


def test_option_set_any_option(pack):
    flat, graph = arms(pack, ["paneer", "garlic"])
    assert flat["r-Creamy dish"] == "one_away"
    assert graph["r-Creamy dish"] == "make_now"


def test_staples_not_expanded(pack):
    for ids in (["onion"], ["onion", "veg_oil"]):
        flat, graph = arms(pack, ids)
        assert flat["r-Oil dish"] == graph["r-Oil dish"] == "one_away"


def test_optional_and_unread_unchanged(pack):
    flat, graph = arms(pack, ["paneer"])
    assert "r-Optional extra" not in flat and "r-Optional extra" not in graph
    assert "r-Unread line" not in flat
    assert graph["r-Unread line"] == "one_away"  # the unread line stays missing


def test_flat_equals_answer(pack):
    for ids in (["onion", "garlic"], ["paneer", "bread"], ["cheese"], []):
        got = answer(pack, AnswerRequest(pantry=ids, staples=pack.default_staples, limit=10**6))
        expect = {r.recipe_id: g for g, grp in got.groups.items() for r in grp.items}
        assert placements(pack, ids) == expect


def test_traversal_is_monotone(pack):
    universe = [
        "paneer", "garlic_paste", "ginger_garlic_paste", "cheese",
        "garlic", "onion", "bread", "veg_oil",
    ]  # fmt: skip
    for n in range(len(universe) + 1):
        for ids in itertools.combinations(universe, n):
            flat, graph = arms(pack, list(ids))
            for rid in {r.recipe_id for r in pack.recipes}:
                assert rank(graph.get(rid)) <= rank(flat.get(rid)), (ids, rid)


def test_expand_adds_ancestors_of_non_staples_only():
    out = expand(EDGES, {"paneer", "veg_oil"}, {"veg_oil"})
    assert out == {"paneer", "veg_oil", "cheese"}


# ---------------------------------------------------------------- diff and signature

DIFF_RECIPES = {
    "Cheese toast": [L("2 slices bread", "bread"), L("grated cheese", "cheese")],
    "Cheesy onions": [L("1 onion", "onion"), L("cheese", "cheese")],
    "Garlic bread": [L("garlic", "garlic"), L("2 slices bread", "bread")],
    **{f"Plain {i}": [L("1 onion", "onion")] for i in range(6)},
    **{f"Needs {i}": [L("1 onion", "onion"), L(f"jam {i}", f"jam{i}")] for i in range(6)},
}


@pytest.fixture(scope="module")
def dpack():
    return make_pack(DIFF_RECIPES, extra_ids=(*SRC, "paneer"))


def test_signature_uses_newly_met_lines_only(dpack):
    # garlic is held directly, so the garlic_paste edge is not part of the item
    new, _ = diff(dpack, EDGES, "pt_x", ["paneer", "garlic_paste", "garlic", "bread"])
    got = {i.recipe_id: i for i in new}
    cheese = got["r-Cheese toast"]
    assert cheese.signature == ("is_a",)
    assert cheese.edges == (("paneer", "is_a", "cheese"),)
    assert cheese.group == "make_now" and cheese.flat_group == "one_away" and cheese.hops == 1
    assert "r-Garlic bread" not in got  # met without any edge, so not new


def test_signature_unions_types_over_newly_met_lines():
    pack = make_pack({"Mix": [L("cheese", "cheese"), L("garlic", "garlic")]}, extra_ids=SRC)
    new, _ = diff(pack, EDGES, "pt_x", ["paneer", "garlic_paste"])
    (item,) = new
    assert item.signature == ("form_of", "is_a")
    assert item.edges == (("garlic_paste", "form_of", "garlic"), ("paneer", "is_a", "cheese"))
    assert (item.group, item.flat_group) == ("make_now", None)


def test_hops_is_the_longest_line_of_the_shortest_paths():
    pack = make_pack({"R": [L("c", "c"), L("b", "b")]})
    edges = [("a", "is_a", "b"), ("b", "is_a", "c")]
    (item,) = diff(pack, edges, "pt_x", ["a"])[0]
    assert item.hops == 2 and item.signature == ("is_a",)


def test_diff_decoys_are_the_same_group_in_both_arms(dpack):
    new, decoys = diff(dpack, EDGES, "pt_x", ["paneer", "onion", "bread"])
    flat, graph = arms(dpack, ["paneer", "onion", "bread"])
    # one_away also holds "Garlic bread": bread is held and garlic is not, in both arms
    assert len(decoys["make_now"]) == 6 and len(decoys["one_away"]) == 7
    for g, ids in decoys.items():
        assert all(flat[r] == graph[r] == g for r in ids)
    assert not {i.recipe_id for i in new} & {r for ids in decoys.values() for r in ids}


# ---------------------------------------------------------------- draw


def _item(p, r, group, sig, edges=(), hops=1):
    return NewItem(p, r, group, None, tuple(sig), tuple(edges), hops)


def _pool(sizes, npantries=40):
    items, k = [], 0
    for (g, sig), n in sizes.items():
        for _ in range(n):
            items.append(_item(f"pt{k % npantries:02d}", f"rec{k:04d}", g, sig))
            k += 1
    return items


def _decoys(npantries=40, per=10):
    return {
        f"pt{i:02d}": {
            "make_now": [f"dm{i:02d}-{j}" for j in range(per)],
            "one_away": [f"do{i:02d}-{j}" for j in range(per)],
        }
        for i in range(npantries)
    }


BIG_POOL = {
    ("make_now", ("is_a",)): 80,
    ("make_now", ("form_of",)): 10,
    ("make_now", ("form_of", "is_a")): 5,
    ("one_away", ("is_a",)): 30,
    ("one_away", ("form_of",)): 30,
}


def _base(items):
    return [i for i in items if i.repeat_of is None]


def _count(items, kind, key):
    out = {}
    for i in _base(items):
        if i.kind == kind:
            out[key(i)] = out.get(key(i), 0) + 1
    return out


def test_draw_is_seeded_and_stratified():
    pool = _pool(BIG_POOL)
    a, b, c = draw(pool, _decoys(), 46), draw(pool, _decoys(), 46), draw(pool, _decoys(), 47)
    assert a == b
    assert {(i.pantry_id, i.recipe_id) for i in a} != {(i.pantry_id, i.recipe_id) for i in c}
    got = _count(a, "new", lambda i: (i.group, "+".join(i.signature)))
    assert got == {
        ("make_now", "is_a"): 35,  # 50 over 3 strata: the two small strata give all they have
        ("make_now", "form_of"): 10,
        ("make_now", "form_of+is_a"): 5,
        ("one_away", "is_a"): 25,  # equal shares
        ("one_away", "form_of"): 25,
    }
    w = {(i.group, i.signature): i.weight for i in a if i.kind == "new"}
    assert w[("make_now", ("is_a",))] == pytest.approx(80 / 35)
    assert w[("make_now", ("form_of",))] == 1.0  # census of the stratum
    assert w[("one_away", ("is_a",))] == pytest.approx(30 / 25)
    assert all(i.weight == 0.0 for i in a if i.kind == "decoy")


def test_draw_borrows_from_the_other_group():
    pool = _pool({("make_now", ("is_a",)): 20, ("one_away", ("is_a",)): 60,
                  ("one_away", ("form_of",)): 40})  # fmt: skip
    got = _count(draw(pool, _decoys(), 46), "new", lambda i: (i.group, "+".join(i.signature)))
    assert got == {("make_now", "is_a"): 20, ("one_away", "is_a"): 40, ("one_away", "form_of"): 40}


def test_repeats_in_other_session_and_gap():
    items = draw(_pool(BIG_POOL), _decoys(), 46)
    by_id = {i.item_id: i for i in items}
    repeats = [i for i in items if i.repeat_of is not None]
    assert len(repeats) == 10
    assert sorted(by_id[r.repeat_of].kind for r in repeats) == ["decoy"] * 5 + ["new"] * 5
    pos = {i.item_id: k for k, i in enumerate(items)}
    for r in repeats:
        orig = by_id[r.repeat_of]
        assert r.session != orig.session
        assert abs(pos[r.item_id] - pos[orig.item_id]) >= 20
    assert [i.session for i in items] == sorted(i.session for i in items)  # sessions are in order
    assert {i.session for i in items} == {1, 2, 3}
    assert len({i.item_id for i in items}) == len(items) == 210


def test_decoys_match_new_per_group(dpack):
    pantries = {"pt_a": ["paneer", "onion", "bread"], "pt_b": ["paneer", "onion"]}
    pool, decoys = [], {}
    for pid, ids in pantries.items():
        new, dec = diff(dpack, EDGES, pid, ids)
        pool += new
        decoys[pid] = dec
    items = draw(pool, decoys, 46)
    new_n = _count(items, "new", lambda i: i.group)
    assert new_n == {"make_now": 3, "one_away": 1}
    assert _count(items, "decoy", lambda i: i.group) == new_n
    for i in items:
        if i.kind == "decoy":
            flat, graph = arms(dpack, pantries[i.pantry_id])
            assert flat[i.recipe_id] == graph[i.recipe_id] == i.group
        else:
            assert rank(i.group) < rank(i.flat_group)
    assert all(
        (i.pantry_id, i.recipe_id) not in {(n.pantry_id, n.recipe_id) for n in pool}
        for i in items
        if i.kind == "decoy"
    )


def test_decoy_falls_back_to_other_pantries():
    pool = [_item("pt00", f"n{j}", "make_now", ("is_a",)) for j in range(3)]
    decoys = {
        "pt00": {"make_now": ["d0"], "one_away": []},
        "pt01": {"make_now": ["d1", "d2"], "one_away": ["o1", "o2"]},
    }
    items = draw(pool, decoys, 46)
    got = {(i.pantry_id, i.recipe_id) for i in items if i.kind == "decoy"}
    assert got == {("pt00", "d0"), ("pt01", "d1"), ("pt01", "d2")}
    with pytest.raises(ValueError, match="decoy"):
        draw(pool, {"pt00": {"make_now": ["d0"]}}, 46)


def test_draw_empty_pool_gives_no_sheet():
    assert draw([], _decoys(), 46) == []


# ---------------------------------------------------------------- sheet


def test_sheet_hides_arm_and_edges(dpack):
    pantries = {
        "pt_alpha": {"names": ["Paneer", "onions", "bread"], "ids": ["paneer", "onion", "bread"]},
        "pt_beta": {"names": ["paneer", "onions"], "ids": ["paneer", "onion"]},
    }
    pool, decoys = [], {}
    for pid, p in pantries.items():
        new, dec = diff(dpack, EDGES, pid, p["ids"])
        pool += new
        decoys[pid] = dec
    items = draw(pool, decoys, 46)
    rows = sheet_rows(items, dpack, pantries, EDGES)
    assert len(rows) == len(items)
    for row in rows:
        assert list(row) == list(gs.SHEET_COLUMNS)
        assert row["answer"] == row["unmet_lines"] == row["seconds"] == row["note"] == ""
        text = " | ".join(str(v) for v in row.values()).lower()
        for banned in ("pt_alpha", "pt_beta", "r-", "is_a", "form_of", "flat", "graph", "weight"):
            assert banned not in text, banned
    by_key = {(i.pantry_id, i.recipe_id): r for i, r in zip(items, rows, strict=True)}
    toast = by_key[("pt_beta", "r-Cheese toast")]
    assert toast["claim"] == "one away" and toast["missing_line"] == "2 slices bread"
    assert toast["pantry"] == "paneer; onions" and toast["staples"] == "Veg Oil"
    assert (
        toast["lines"] == "1. 2 slices bread\n2. grated cheese" and toast["title"] == "Cheese toast"
    )
    full = by_key[("pt_alpha", "r-Cheese toast")]
    assert full["claim"] == "make now" and full["missing_line"] == ""


# ---------------------------------------------------------------- scoring

PILOT = [f"pilot{i:02d}" for i in range(1, 21)]
NEW = [f"new{i:02d}" for i in range(1, 21)]
SETS = {**dict.fromkeys(PILOT, "pilot"), **dict.fromkeys(NEW, "new")}
T = gs.THRESHOLDS
PANEER = ("paneer", "is_a", "cheese")
PASTE = ("garlic_paste", "form_of", "garlic")


def _entry(pid, group, kind, sig, w, edges=(), repeat_of=None, session=1, hops=1):
    return {
        "pantry_id": pid, "recipe_id": f"r-{pid}-{group}", "group": group, "kind": kind,
        "weight": w, "signature": list(sig), "edges": [list(e) for e in edges], "hops": hops,
        "flat_group": None, "repeat_of": repeat_of, "session": session,
    }  # fmt: skip


def _key(entries, pool=None, sets=SETS, pool_by_set=None):
    items = {f"g{k + 1:03d}": e for k, e in enumerate(entries)}
    if pool is None:
        pool, pool_by_set = {}, {"pilot": {}, "new": {}}
        for e in entries:
            if e["kind"] == "new" and e["repeat_of"] is None:
                k = f"{e['group']}|{'+'.join(e['signature'])}"
                pool[k] = pool.get(k, 0) + 1
                sub = pool_by_set[sets[e["pantry_id"]]]
                sub[k] = sub.get(k, 0) + 1
    return {"version": 1, "seed": 46, "pantries": dict(sets), "pool": pool,
            "pool_by_set": pool_by_set or {"pilot": {}, "new": {}}, "items": items}  # fmt: skip


def _answers(key, no=(), unsure=()):
    out = []
    for iid in key["items"]:
        a = "no" if iid in no else "unsure" if iid in unsure else "yes"
        out.append({"item_id": iid, "answer": a, "unmet_lines": "", "seconds": "", "note": ""})
    return out


def _hand():
    e = [
        _entry("p1", "make_now", "new", ("is_a",), 2.0, [PANEER]),  # g001 yes
        _entry("p1", "make_now", "new", ("is_a",), 2.0, [PANEER]),  # g002 no
        _entry("p1", "one_away", "new", ("form_of",), 1.0, [PASTE]),  # g003 yes
        _entry("p2", "one_away", "new", ("form_of",), 1.0, [PASTE]),  # g004 unsure
        _entry("p3", "make_now", "new", ("form_of", "is_a"), 1.0, [PANEER, PASTE]),  # g005 yes
        _entry("p1", "make_now", "decoy", (), 0.0),  # g006 yes
        _entry("p2", "one_away", "decoy", (), 0.0),  # g007 no
        _entry("p1", "make_now", "new", ("is_a",), 2.0, [PANEER], repeat_of="g001"),  # g008 yes
        _entry("p1", "make_now", "new", ("is_a",), 2.0, [PANEER], repeat_of="g002"),  # g009 yes
    ]
    key = _key(e, pool={"make_now|is_a": 10, "make_now|form_of+is_a": 1, "one_away|form_of": 2},
               sets={"p1": "pilot", "p2": "pilot", "p3": "new"},
               pool_by_set={"pilot": {"make_now|is_a": 7, "one_away|form_of": 2},
                            "new": {"make_now|is_a": 3, "make_now|form_of+is_a": 1}})  # fmt: skip
    answers = _answers(key, no=("g002", "g007"), unsure=("g004",))
    return key, answers


def test_score_hand_case():
    key, answers = _hand()
    r = score(key, answers, T, 46)
    n = r["net_new_per_pantry"]
    assert n["mean"] == pytest.approx(1 / 3)  # d = [1, -1, 1]: +2 -2 +1, -1, +1
    assert (n["pantries_positive"], n["pantries_negative"], n["n_pantries"]) == (2, 1, 3)
    assert n["t_lo"] == pytest.approx(1 / 3 - 4.302653 * (2 / 3), abs=1e-4)
    assert n["t_hi"] == pytest.approx(1 / 3 + 4.302653 * (2 / 3), abs=1e-4)
    assert n["boot_lo"] <= n["mean"] <= n["boot_hi"]
    assert n["decision_lo"] == min(n["boot_lo"], n["t_lo"])
    mn, oa = r["precision"]["make_now"], r["precision"]["one_away"]
    assert mn["weighted"] == pytest.approx(3 / 5) and mn["n"] == 3  # (2 + 1) / (2 + 2 + 1)
    assert (mn["wilson_lo"], mn["wilson_hi"]) == wilson(2, 3)
    assert oa["weighted"] == pytest.approx(1 / 2) and oa["n"] == 2
    assert (mn["decoy_precision"], mn["decoy_n"]) == (1.0, 1)
    assert (oa["decoy_precision"], oa["decoy_n"]) == (0.0, 1)
    s = {(x["group"], x["signature"]): x for x in r["strata"]}
    assert s[("make_now", "is_a")]["weighted"] == pytest.approx(0.5)
    assert (s[("make_now", "is_a")]["n"], s[("make_now", "is_a")]["pool_n"]) == (2, 10)
    assert s[("make_now", "is_a")]["mode"] == "sample"
    assert s[("make_now", "form_of+is_a")]["weighted"] == 1.0
    assert s[("make_now", "form_of+is_a")]["mode"] == "census"
    assert s[("one_away", "form_of")]["weighted"] == pytest.approx(0.5)
    t = r["edge_types"]
    assert t["is_a"] == {"correct": 2, "wrong": 1, "pantries": 2, "correct_pantries": 2}
    assert t["form_of"] == {"correct": 2, "wrong": 1, "pantries": 3, "correct_pantries": 2}
    e = {(x["from"], x["type"], x["to"]): (x["correct"], x["wrong"]) for x in r["edges"]}
    assert e == {PANEER: (2, 1), PASTE: (2, 1)}
    assert r["repeat_agreement"] == {"pairs": 2, "agree": 1, "rate": 0.5}
    assert r["hops"] == {"1": 5}
    pil, new = r["split_report"]["pilot"], r["split_report"]["new"]
    assert pil["net_new_per_pantry"]["mean"] == 0.0  # d = [1, -1]
    assert new["net_new_per_pantry"]["mean"] == 1.0 and new["net_new_per_pantry"]["n_pantries"] == 1
    assert r["rated"]["new"] == 5 and r["rated"]["decoys"] == 2 and r["rated"]["repeats"] == 2


def test_split_strata_use_the_pool_of_their_own_subset():
    key, answers = _hand()
    r = score(key, answers, T, 46)
    pil = {(x["group"], x["signature"]): x for x in r["split_report"]["pilot"]["strata"]}
    new = {(x["group"], x["signature"]): x for x in r["split_report"]["new"]["strata"]}
    assert pil[("make_now", "is_a")]["pool_n"] == 7 and pil[("make_now", "is_a")]["n"] == 2
    assert pil[("make_now", "is_a")]["mode"] == "sample"
    assert new[("make_now", "is_a")]["pool_n"] == 3 and new[("make_now", "is_a")]["n"] == 0
    assert new[("make_now", "form_of+is_a")]["mode"] == "census"
    assert ("one_away", "form_of") not in new  # no pool and no item in the new pantries


def test_first_answer_counts_when_a_repeat_comes_before_its_original():
    # g001 is the repeat of g003: the rater saw g001 first, so its answer is the one that counts
    e = [
        _entry("p1", "make_now", "new", ("is_a",), 1.0, [PANEER], repeat_of="g003"),  # g001
        _entry("p2", "make_now", "new", ("is_a",), 1.0, [PANEER]),  # g002
        _entry("p1", "make_now", "new", ("is_a",), 1.0, [PANEER]),  # g003, the original
    ]
    key = _key(e, pool={"make_now|is_a": 2}, sets={"p1": "pilot", "p2": "pilot"},
               pool_by_set={"pilot": {"make_now|is_a": 2}, "new": {}})  # fmt: skip
    first_yes = score(key, _answers(key, no=("g003",)), T, 46)
    assert first_yes["precision"]["make_now"]["weighted"] == 1.0  # g001 yes, g002 yes
    assert first_yes["net_new_per_pantry"]["mean"] == 1.0  # d = [1, 1]
    assert first_yes["rated"]["new"] == 2
    assert first_yes["repeat_agreement"] == {"pairs": 1, "agree": 0, "rate": 0.0}
    first_no = score(key, _answers(key, no=("g001",)), T, 46)
    assert first_no["precision"]["make_now"]["weighted"] == 0.5  # g001 no, g002 yes
    assert first_no["net_new_per_pantry"]["mean"] == 0.0


def test_pantry_with_no_new_item_stays_in_with_zero():
    key, answers = _hand()
    key["pantries"]["p4"] = "new"  # a fourth pantry, no item
    n = score(key, answers, T, 46)["net_new_per_pantry"]
    assert n["n_pantries"] == 4 and n["mean"] == pytest.approx(1 / 4)


def test_unsure_counts_as_wrong():
    key, _ = _hand()
    as_no = score(key, _answers(key, no=("g001",)), T, 46)["precision"]["make_now"]["weighted"]
    as_unsure = score(key, _answers(key, unsure=("g001",)), T, 46)["precision"]["make_now"][
        "weighted"
    ]
    all_yes = score(key, _answers(key), T, 46)["precision"]["make_now"]["weighted"]
    assert as_no == as_unsure < all_yes
    with pytest.raises(ValueError, match="unsure_is_wrong"):
        score(key, _answers(key), {**T, "unsure_is_wrong": False}, 46)


def test_score_rejects_bad_answers():
    key, answers = _hand()
    with pytest.raises(ValueError, match="missing"):
        score(key, answers[:-1], T, 46)
    with pytest.raises(ValueError, match="unknown"):
        score(key, [*answers, {"item_id": "g999", "answer": "yes"}], T, 46)
    with pytest.raises(ValueError, match="twice"):
        score(key, [*answers, answers[0]], T, 46)
    with pytest.raises(ValueError, match="answer"):
        score(key, [{**answers[0], "answer": "maybe"}, *answers[1:]], T, 46)


def test_empty_pool_rejects():
    key = _key([], pool={})
    r = score(key, [], T, 46)
    assert r["verdict"] == "rejected" and r["reason"] == "no_new_recipes"


def _spread(group, sig, pantries, yes, no, edge):
    """``yes`` correct and ``no`` wrong items of one group, spread over ``pantries``."""
    items = []
    for k in range(yes + no):
        items.append(_entry(pantries[k % len(pantries)], group, "new", sig, 1.0, [edge]))
    return items, set(range(yes, yes + no))


def _rate(parts):
    """Build one key from ``(entries, wrong_positions)`` parts. Items in ``wrong`` answer no."""
    entries, no = [], set()
    for items, wrong in parts:
        no |= {len(entries) + w for w in wrong}
        entries += items
    key = _key(entries)
    ids = list(key["items"])
    return key, _answers(key, no={ids[i] for i in no})


def _t3(make_now_yes, make_now_no, thresholds=T):
    key, answers = _rate([
        _spread("make_now", ("is_a",), PILOT, make_now_yes, make_now_no, PANEER),
        _spread("one_away", ("form_of",), PILOT, 50, 0, PASTE),
    ])  # fmt: skip
    return score(key, answers, thresholds, 46)


def test_small_group_fails_t3():
    r = _t3(19, 0)
    assert r["checks"]["T3"] == "fail" and r["verdict"] == "rejected"
    assert _t3(20, 0)["checks"]["T3"] == "pass"  # 20 of 20 is enough
    point = {**T, "T3": {**T["T3"], "form": "point"}}
    assert _t3(19, 0, point)["checks"]["T3"] == "fail"
    assert _t3(20, 0, point)["checks"]["T3"] == "pass"


def test_t3_wilson_form():
    assert wilson(46, 50)[0] >= 0.80 > wilson(45, 50)[0]
    assert _t3(46, 4)["checks"]["T3"] == "pass"
    assert _t3(45, 5)["checks"]["T3"] == "fail"
    point = {**T, "T3": {**T["T3"], "form": "point"}}
    assert _t3(45, 5, point)["checks"]["T3"] == "pass"  # weighted 0.90 passes the point form
    assert _t3(44, 6, point)["checks"]["T3"] == "fail"


def _scenario(new_yes, new_no, pilot_yes=10):
    parts = []
    for group, sig, edge in (("make_now", ("is_a",), PANEER), ("one_away", ("form_of",), PASTE)):
        parts.append(_spread(group, sig, PILOT, pilot_yes * 20, 0, edge))
        parts.append(_spread(group, sig, NEW, 20 * new_yes, 0, edge))
        parts.append(_spread(group, sig, NEW, 20 * new_no, 0, edge))
    # the last part of each group is wrong
    entries, no = [], set()
    for k, (items, _) in enumerate(parts):
        if k % 3 == 2:
            no |= set(range(len(entries), len(entries) + len(items)))
        entries += items
    key = _key(entries)
    ids = list(key["items"])
    return key, _answers(key, no={ids[i] for i in no})


def test_accept_when_all_pass():
    r = score(*_scenario(2, 0), T, 46)
    assert r["checks"] == {"T1": "pass", "T2": "pass", "T3": "pass", "guard": "pass"}
    assert r["verdict"] == "accepted"


@pytest.mark.parametrize(("new_yes", "new_no"), [(1, 1), (2, 1)])
def test_new_subset_guard(new_yes, new_no):
    # (1, 1): the new pantries net 0 per pantry. (2, 1): net positive but precision 0.667.
    r = score(*_scenario(new_yes, new_no), T, 46)
    assert [r["checks"][k] for k in ("T1", "T2", "T3")] == ["pass"] * 3
    assert r["checks"]["guard"] == "fail"
    assert r["verdict"] == "exploration"


def test_guard_can_be_switched_off_and_is_ignored_when_a_test_fails():
    off = {**T, "new_subset_guard": False}
    assert score(*_scenario(1, 1), off, 46)["verdict"] == "accepted"
    r = score(*_scenario(1, 1, pilot_yes=0), T, 46)  # T2 and T3 fail anyway
    assert r["verdict"] == "rejected"


def test_t1_needs_both_types_in_correct_items_from_enough_pantries():
    key, answers = _rate([
        _spread("make_now", ("is_a",), PILOT, 30, 0, PANEER),
        _spread("one_away", ("is_a",), PILOT, 30, 0, PANEER),
        _spread("one_away", ("form_of",), PILOT[:2], 6, 0, PASTE),  # 6 items, 2 pantries
    ])  # fmt: skip
    r = score(key, answers, T, 46)
    assert r["checks"]["T1"] == "fail"
    key, answers = _rate([
        _spread("make_now", ("is_a",), PILOT, 30, 0, PANEER),
        _spread("one_away", ("is_a",), PILOT, 30, 0, PANEER),
        _spread("one_away", ("form_of",), PILOT[:3], 5, 0, PASTE),  # 5 items, 3 pantries
    ])  # fmt: skip
    assert score(key, answers, T, 46)["checks"]["T1"] == "pass"


def test_t_critical_values():
    assert gs.t_critical(39) == pytest.approx(2.02269, abs=1e-4)
    assert gs.t_critical(10) == pytest.approx(2.22814, abs=1e-4)
    assert gs.t_critical(2) == pytest.approx(4.30265, abs=1e-4)
    assert gs.t_critical(1) == pytest.approx(12.7062, abs=1e-3)


def test_draw_then_key_then_score_round_trip(dpack):
    pantries = {"pt_a": ["paneer", "onion", "bread"], "pt_b": ["paneer", "onion"]}
    pool, decoys = [], {}
    for pid, ids in pantries.items():
        new, dec = diff(dpack, EDGES, pid, ids)
        pool += new
        decoys[pid] = dec
    items = draw(pool, decoys, 46)
    key = gs.make_key(items, pool, {"pt_a": "pilot", "pt_b": "new"}, 46)
    assert json.loads(json.dumps(key)) == key  # plain JSON
    answers = [{"item_id": i, "answer": "yes"} for i in key["items"]]
    r = score(key, answers, T, 46)
    assert r["rated"]["new"] == 4 and r["net_new_per_pantry"]["n_pantries"] == 2
    assert r["precision"]["make_now"]["weighted"] == 1.0


# ---------------------------------------------------------------- pool summaries


def test_pool_counts_top_edges_and_source_hits(dpack):
    pool, decoys = gs.build_pool(
        dpack, EDGES, {"pt_a": ["paneer", "onion", "bread"], "pt_b": ["paneer", "onion"]}
    )
    counts = gs.pool_counts(pool, decoys)
    assert counts["new"] == {"make_now|is_a": 3, "one_away|is_a": 1}
    assert counts["decoy_candidates"] == {"make_now": 12, "one_away": 13}
    assert counts["edge_types"] == {
        "is_a": {"new": 4, "pantries": 2},
        "form_of": {"new": 0, "pantries": 0},
    }
    assert gs.pool_by_edge(pool, top=10) == [["paneer", "is_a", "cheese", 4]]
    hits = gs.edge_source_hits(
        dpack,
        EDGES,
        {
            "pt_a": {"names": ["paneer", "onion", "zzz"], "set": "pilot"},
            "pt_b": {"names": ["garlic paste", "paneer"], "set": "new"},
        },
    )
    assert hits == {"pilot": 1, "new": 2, "by_pantry": {"pt_a": 1, "pt_b": 2}}


# ---------------------------------------------------------------- freeze

CODE_FILES = (
    "pantrychef/eval/graph_spike.py",
    "pantrychef/engine.py",
    "pantrychef/ingredients/names.py",
    "pantrychef/ingredients/table.py",
    "pantrychef/pack/build.py",
    "pantrychef/eval/stats.py",
    "scripts/graph_spike.py",
)


USABLE = {"paneer": "usable"}


def _tree(tmp: Path, option="a") -> Path:
    g = tmp / "data" / "eval" / "graph_spike"
    g.mkdir(parents=True)
    (tmp / "data" / "ingredients").mkdir(parents=True)
    (tmp / "data" / "raw").mkdir()
    (tmp / "pantrychef" / "pack").mkdir(parents=True)
    shutil.copy(DEFAULT_WORDS_PATH, tmp / "data" / "ingredients" / "words.v1.json")
    (g / "table.frozen.csv").write_bytes(TABLE_CSV.encode())
    (g / "pantries.v1.json").write_text('{"version": 1, "pantries": []}\n')
    (tmp / "data" / "raw" / "snap.jsonl.gz").write_bytes(b"snapshot bytes")
    (tmp / "pantrychef" / "pack" / "allowlist.json").write_text(
        json.dumps({"inputs": {"snapshot": {"path": "data/raw/snap.jsonl.gz"}}})
    )
    for rel in CODE_FILES:
        f = tmp / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"# stub {rel}\n")
    if option == "b":
        edges = edge_list(IngredientTable.from_text(TABLE_CSV))
        doc = {
            "edges": [
                {"from": a, "type": t, "to": b, "label": USABLE.get(a, "not usable")}
                for a, t, b in edges
            ],
            "owner_edits": [{"from": "paneer", "type": "is_a", "to": "cheese",
                             "old_label": "not usable", "new_label": "usable"}],
        }  # fmt: skip
        (g / "edge_labels.v1.json").write_text(json.dumps(doc))
    return tmp


def _freeze(tmp: Path, option="a") -> Path:
    root = _tree(tmp, option)
    manifest = freeze_manifest(root, gs.PLAN, T, option, extras={"pool_counts": {"new": {}}})
    path = root / "data" / "eval" / "graph_spike" / "freeze.v1.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def test_freeze_manifest_fields(tmp_path):
    path = _freeze(tmp_path, "b")
    m = json.loads(path.read_text())
    assert m["edge_option"] == {
        "option": "b",
        "confirmed_by": "owner",
        "confirmed_on": "2026-11-09",
    }
    assert m["edges"] == [
        ["ginger_garlic_paste", "form_of", "garlic"],
        ["ginger_garlic_paste", "form_of", "ginger"],
        ["paneer", "is_a", "cheese"],
    ]
    assert m["edges_in_use"]["edges"] == [["paneer", "is_a", "cheese"]]
    assert m["edges_in_use"]["count_per_type"] == {"is_a": 1, "form_of": 0}
    assert m["max_depth_observed"] == 1
    assert m["owner_edits"][0]["from"] == "paneer"
    assert sorted(m["code_sha256"]) == sorted(CODE_FILES)
    assert m["plan"]["seed"] == 46 and m["thresholds"]["T3"]["min_rated"] == 20
    assert m["pool_counts"] == {"new": {}}
    assert check_freeze(path, tmp_path) == []


def test_freeze_check_names_changed_field(tmp_path):
    path = _freeze(tmp_path)
    assert check_freeze(path, tmp_path) == []
    table = tmp_path / "data" / "eval" / "graph_spike" / "table.frozen.csv"
    raw = bytearray(table.read_bytes())
    raw[raw.index(b"Cheese")] ^= 0x20  # one byte of a name, not an edge
    table.write_bytes(bytes(raw))
    assert check_freeze(path, tmp_path) == ["table_sha256"]


def test_freeze_check_sees_other_inputs(tmp_path):
    path = _freeze(tmp_path)
    (tmp_path / "pantrychef" / "engine.py").write_text("# changed\n")
    (tmp_path / "data" / "eval" / "graph_spike" / "pantries.v1.json").write_text("{}\n")
    assert check_freeze(path, tmp_path) == ["code_sha256", "pantries_sha256"]


def test_freeze_check_sees_a_changed_edge(tmp_path):
    path = _freeze(tmp_path)
    table = tmp_path / "data" / "eval" / "graph_spike" / "table.frozen.csv"
    table.write_bytes(table.read_bytes().replace(b",hand,cheese,", b",hand,,"))
    assert check_freeze(path, tmp_path) == [
        "table_sha256", "edges", "edges_sha256", "edges_in_use",
    ]  # fmt: skip


def test_hash_ignores_crlf(tmp_path):
    lf, crlf = tmp_path / "lf.csv", tmp_path / "crlf.csv"
    lf.write_bytes(b"a,b\n1,2\n")
    crlf.write_bytes(b"a,b\r\n1,2\r\n")
    other = tmp_path / "other.csv"
    other.write_bytes(b"a,b\n1,3\n")
    assert gs.sha256_lf(lf) == gs.sha256_lf(crlf)
    assert gs.sha256_lf(lf) != gs.sha256_lf(other)


# ---------------------------------------------------------------- the real pantries file


@pytest.mark.skipif(
    not PANTRIES.exists(),
    reason="data/eval/graph_spike/pantries.v1.json is absent: it arrives with the freeze commit",
)
def test_spike_pantries_are_dev_only():
    doc = json.loads(PANTRIES.read_text(encoding="utf-8"))
    ps = doc["pantries"]
    assert doc["split"] == "dev" and doc["never_in"] == "M4 test split"
    assert len(ps) == 40
    assert len({p["id"] for p in ps}) == 40
    pilot = [p for p in ps if p["id"].startswith("pilot")]
    new = [p for p in ps if p["id"].startswith("new")]
    assert (len(pilot), len(new)) == (20, 20)
    assert all(p["source"].startswith("m2_pilot:") and p["source_recipe_id"] for p in pilot)
    assert len({p["source_recipe_id"] for p in pilot}) == 20
    assert all(p["source"] == "spike_writer" and p["profile"] for p in new)
    assert all(p["names"] and all(isinstance(n, str) and n.strip() for n in p["names"]) for p in ps)
    assert [p["profile"] for p in new] == doc["writer"]["profiles"]
    assert len(doc["writer"]["profiles"]) == 20
    assert doc["writer"]["model"] == "Sonnet" and doc["writer"]["date"] == "2026-11-09"
    assert doc["writer"]["prompt"].startswith("Write 20 pantries.")
