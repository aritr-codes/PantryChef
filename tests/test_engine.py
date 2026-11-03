"""Reference engine tests. Expected values are computed by hand."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from pantrychef.engine import AnswerRequest, Pack, answer, load_pack, resolve_names

FIXTURE = Path(__file__).parent / "fixtures" / "pack"


def make_pack(recipes: dict[str, list[tuple]], idf: dict[str, float], staples=("s",)) -> Pack:
    """``recipes``: title -> lines of ``(options, optional, read)``."""
    ids = sorted({o for ls in recipes.values() for opts, _, _ in ls for o in opts} | set(staples))
    core = {
        "info": {"version": "t", "commit": "t", "corpus_fingerprint": "t"},
        "ingredients": [
            {"id": i, "name": i.upper(), "staple": i in staples, "idf": idf.get(i, 0.0)}
            for i in ids
        ],
        "keys": {i: i for i in ids},
        "recipes": [
            {
                "id": f"r-{title}",
                "title": title,
                "page": f"Cookbook:{title}",
                "rev": 1,
                "lines": [
                    {"t": "/".join(opts) or "unread text", "o": list(opts), "opt": opt, "r": read}
                    for opts, opt, read in ls
                ],
            }
            for title, ls in recipes.items()
        ],
    }
    return Pack.from_core(core)


def req(pantry, staples=("s",), limit=10, **kw):
    return AnswerRequest(pantry=list(pantry), staples=list(staples), limit=limit, **kw)


def L(*opts, optional=False, read=True):
    return (opts, optional, read)


IDF = {"a": 1.0, "b": 2.0, "c": 0.5, "d": 1.5}


def test_score_is_sum_of_satisfied_weights_over_sqrt_of_all_weights():
    pack = make_pack({"R": [L("a"), L("b"), L("c")]}, IDF)
    r = answer(pack, req(["a", "b"])).groups["one_away"].items[0]
    assert (r.have, r.total) == (2, 3)
    assert r.score == 3.0 / math.sqrt(3.5)
    assert [m.options for m in r.missing] == [["c"]]


def test_make_now_when_every_needed_line_is_satisfied():
    pack = make_pack({"R": [L("a"), L("b")]}, IDF)
    ans = answer(pack, req(["a", "b"]))
    assert ans.groups["make_now"].count == 1 and ans.groups["one_away"].count == 0
    assert ans.groups["make_now"].items[0].score == 3.0 / math.sqrt(3.0)


def test_score_is_zero_when_the_denominator_is_zero():
    pack = make_pack({"R": [L("z")]}, {"z": 0.0})
    assert answer(pack, req(["z"])).groups["make_now"].items[0].score == 0.0


def test_optional_unread_and_staple_lines_weigh_zero():
    pack = make_pack({"R": [L("a"), L("b", optional=True), L("s"), L(read=False)]}, IDF)
    ans = answer(pack, req(["a"]))
    r = ans.groups["one_away"].items[0]
    assert (r.have, r.total, r.unread) == (1, 2, 1)  # a plus the unread line; b and s do not count
    assert r.score == 1.0 / math.sqrt(1.0)
    assert ans.unlocks == []  # an unread line offers nothing to add


def test_unread_line_blocks_make_now():
    pack = make_pack({"R": [L("a"), L(read=False)]}, IDF)
    ans = answer(pack, req(["a"]))
    assert ans.groups["make_now"].count == 0 and ans.groups["one_away"].count == 1


def test_or_line_is_satisfied_by_any_option_and_weighs_the_largest_idf():
    pack = make_pack({"R": [L("a", "b"), L("c")]}, IDF)
    r = answer(pack, req(["a"])).groups["one_away"].items[0]
    assert r.score == 2.0 / math.sqrt(2.5)  # w(a|b) = 2.0 even though only a is held


def test_line_with_a_staple_option_is_free():
    pack = make_pack({"R": [L("a"), L("c", "s")]}, IDF)
    ans = answer(pack, req(["a"]))
    assert ans.groups["make_now"].count == 1
    assert ans.groups["make_now"].items[0].total == 1


def test_staples_come_from_the_request_not_the_pack():
    pack = make_pack({"R": [L("a"), L("b")]}, IDF)
    assert answer(pack, req(["a"], staples=["b"])).groups["make_now"].count == 1
    assert answer(pack, req(["a"], staples=[])).groups["one_away"].count == 1


def test_recipe_whose_needed_lines_all_become_staples_disappears():
    pack = make_pack({"R": [L("a"), L("s")]}, IDF)
    assert answer(pack, req(["a"], staples=["s", "a"])).groups["make_now"].count == 0


def test_candidate_needs_a_pantry_id_on_a_needed_line():
    pack = make_pack({"R": [L("a"), L("b"), L("d", optional=True)]}, IDF)
    # d is held but its line is optional, so R is not a candidate.
    ans = answer(pack, req(["d"]))
    assert sum(g.count for g in ans.groups.values()) == 0


def test_groups_by_missing_lines_and_cap_at_two():
    pack = make_pack(
        {
            "Zero": [L("a")],
            "One": [L("a"), L("b")],
            "Two": [L("a"), L("b"), L("c")],
            "Three": [L("a"), L("b"), L("c"), L("d")],
        },
        IDF,
    )
    ans = answer(pack, req(["a"]))
    assert {k: g.count for k, g in ans.groups.items()} == {
        "make_now": 1,
        "one_away": 1,
        "two_away": 1,
    }


def test_order_is_score_then_fewer_total_then_recipe_id():
    pack = make_pack(
        {"B": [L("a")], "A": [L("a")], "C": [L("b"), L("a"), L("c")], "D": [L("a"), L("d")]}, IDF
    )
    ans = answer(pack, req(["a", "b", "c", "d"]))
    ids = [r.recipe_id for r in ans.groups["make_now"].items]
    # scores: A=B=1.0 (total 1); D = 2.5/sqrt(2.5)=1.58; C = 3.5/sqrt(3.5)=1.87
    assert ids == ["r-C", "r-D", "r-A", "r-B"]


def test_equal_scores_prefer_fewer_total_lines():
    # X: lines a(1.0) -> 1/sqrt(1) = 1.0, total 1.  Y: a(1.0) + s-free staple option... total 1 too
    # so use a zero-weight extra needed line: an unread line is needed but weighs 0.
    pack = make_pack({"X": [L("a")], "Y": [L("a"), L(read=False)]}, IDF)
    ans = answer(pack, req(["a"]))
    assert [r.recipe_id for r in ans.groups["make_now"].items] == ["r-X"]
    assert [r.recipe_id for r in ans.groups["one_away"].items] == ["r-Y"]


def test_unlocks_count_one_away_recipes_by_missing_option_then_id():
    pack = make_pack(
        {
            "R1": [L("a"), L("b")],
            "R2": [L("a"), L("b", "c")],
            "R3": [L("a"), L("d")],
            "R4": [L("a"), L("b"), L("d")],  # two away, not counted
        },
        IDF,
    )
    ans = answer(pack, req(["a"]))
    assert [(u.ingredient_id, u.recipes) for u in ans.unlocks] == [("b", 2), ("c", 1), ("d", 1)]
    assert ans.unlocks[0].name == "B"


def test_unlocks_count_all_one_away_recipes_not_just_the_listed_ones():
    pack = make_pack({f"R{i}": [L("a"), L("b")] for i in range(5)}, IDF)
    ans = answer(pack, req(["a"], limit=2))
    assert len(ans.groups["one_away"].items) == 2 and ans.groups["one_away"].count == 5
    assert ans.unlocks[0].recipes == 5


def test_blockers_only_when_every_group_is_empty():
    pack = make_pack({"R": [L("a"), L("b"), L("c"), L("d")], "S": [L("a"), L("b"), L("c")]}, IDF)
    # pantry {a}: S has 2 missing -> two_away, so there is no blocker
    assert answer(pack, req(["a"])).blockers == []


def test_blockers_name_the_item_that_returns_the_most_recipes():
    pack = make_pack(
        {
            "R1": [L("a"), L("b"), L("c"), L("d")],
            "R2": [L("a"), L("b"), L("c"), L("d")],
            "R3": [L("a"), L("c"), L("d"), L("x")],
        },
        {**IDF, "x": 3.0},
    )
    ans = answer(pack, req(["a"]))
    assert sum(g.count for g in ans.groups.values()) == 0
    # adding b helps R1 and R2 (2 missing left); c helps all three; d helps all three; x helps R3
    assert [(b.ingredient_id, b.recipes) for b in ans.blockers] == [
        ("c", 3),
        ("d", 3),
        ("b", 2),
        ("x", 1),
    ]
    assert all(b.kind == "add_item" for b in ans.blockers)


def test_blocker_can_open_recipes_the_pantry_does_not_touch():
    pack = make_pack({"R": [L("b"), L("c"), L("d")], "Q": [L("a"), L("b"), L("c"), L("d")]}, IDF)
    ans = answer(pack, req(["a"]))
    assert sum(g.count for g in ans.groups.values()) == 0
    # adding b gives R one held line (2 missing) and Q two held lines (2 missing)
    assert [(b.ingredient_id, b.recipes) for b in ans.blockers] == [("b", 2), ("c", 2), ("d", 2)]


def test_empty_pantry_gives_empty_groups_and_no_blockers():
    pack = make_pack({"R": [L("a")]}, IDF)
    ans = answer(pack, req([]))
    assert all(g.count == 0 for g in ans.groups.values()) and ans.blockers == []


def test_group_count_is_independent_of_limit():
    pack = make_pack({f"R{i}": [L("a")] for i in range(4)}, IDF)
    g = answer(pack, req(["a"], limit=2)).groups["make_now"]
    assert g.count == 4 and len(g.items) == 2


def test_unknown_pantry_collects_typed_names_and_unknown_ids():
    pack = make_pack({"R": [L("a")]}, IDF)
    ans = answer(pack, req(["a", "zz"], unknown_names=["mystery"]))
    assert ans.unknown_pantry == ["mystery", "zz"]
    assert ans.groups["make_now"].count == 1


def test_diet_is_not_supported_in_m1():
    pack = make_pack({"R": [L("a")]}, IDF)
    with pytest.raises(NotImplementedError):
        answer(pack, req(["a"], diet="vegan"))


def test_fixture_pack_pancakes_example():
    pack = load_pack(FIXTURE, "v1")
    ids, unknown = resolve_names(pack, ["flour", "Eggs", "milk", "xylophone"])
    assert ids == ["flour", "egg", "milk"] and unknown == ["xylophone"]
    ans = answer(pack, AnswerRequest(ids, pack.default_staples, limit=3, unknown_names=unknown))
    titles = [r.title for r in ans.groups["one_away"].items]
    assert "Banana Pancakes" in titles
    assert ans.unknown_pantry == ["xylophone"]
    assert ans.pack.version == "fixture"
