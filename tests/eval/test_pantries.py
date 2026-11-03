"""Hand-computed tests for masked pantries (plan section 3)."""

from __future__ import annotations

import random

import pytest

from pantrychef.engine import Ingredient, Line, Pack, PackInfo, Recipe
from pantrychef.eval.pantries import (
    assign_splits,
    build_pantries,
    document_frequency,
    eligible,
    mask_count,
    sample_distractors,
)


def L(*opts: str, opt: bool = False, read: bool = True) -> Line:
    return Line(text="/".join(opts), options=opts if read else (), optional=opt, read=read)


def R(rid: str, title: str, *lines: Line) -> Recipe:
    return Recipe(rid, title, f"Cookbook:{title}", 1, tuple(lines))


def make_pack(recipes: list[Recipe], extra: tuple[str, ...] = ()) -> Pack:
    ids = {o for r in recipes for ln in r.lines for o in ln.options} | set(extra)
    ings = {i: Ingredient(i, i, i == "salt", 1.0) for i in ids | {"salt"}}
    return Pack(PackInfo("t", "t", "fp"), ings, {}, tuple(recipes))


STAPLES = {"salt"}


@pytest.mark.parametrize(
    ("total", "m"),
    [(3, 1), (4, 1), (5, 1), (6, 2), (7, 2), (10, 3)],
)
def test_mask_count_round_half_up(total, m):
    # floor(0.25*total + 0.5): 3->1.25->1, 4->1.5->1, 5->1.75->1, 6->2.0->2, 7->2.25->2, 10->3.0->3
    assert mask_count(total) == m


def test_eligible_rules():
    four = R("r4", "Four", L("a"), L("b"), L("c"), L("d"))
    assert eligible(four, STAPLES)
    # total 2 -> not eligible
    assert not eligible(R("r2", "Two", L("a"), L("b")), STAPLES)
    # staple and optional lines do not count: total is 2
    assert not eligible(
        R("rs", "S", L("a"), L("b"), L("salt"), L("c", opt=True)),
        STAPLES,
    )
    # total 3, only 1 read line, m = 1 -> eligible
    assert eligible(R("ru", "U", L("a"), L("x", read=False), L("y", read=False)), STAPLES)
    # total 3 with 0 read lines -> not eligible
    assert not eligible(R("r0", "Z", *[L("x", read=False)] * 3), STAPLES)
    # total 6 (m = 2) with only 1 read line -> not eligible
    assert not eligible(R("r6", "Six", L("a"), *[L("x", read=False)] * 5), STAPLES)


def test_assign_splits_groups_and_exact_cut():
    # 9 groups: "pancakes" has 3 variants that normalise to one key.
    titles = [
        ("1", "Pancakes"),
        ("2", "Pancakes (Thin)"),
        ("3", "pancakes!"),
        *[(str(i), f"Dish {i}") for i in range(4, 12)],
    ]
    recipes = [R(i, t, L("a")) for i, t in titles]
    sp = assign_splits(recipes, seed=42)
    assert sp == assign_splits(recipes, seed=42)
    assert sp["1"] == sp["2"] == sp["3"]
    assert len(sp) == 11
    # 9 groups: 4 dev groups and 5 test groups
    dev_groups = {"pancakes" if i in "123" else i for i, s in sp.items() if s == "dev"}
    test_groups = {"pancakes" if i in "123" else i for i, s in sp.items() if s == "test"}
    assert len(dev_groups) == 4 and len(test_groups) == 5
    assert dev_groups.isdisjoint(test_groups)


def test_document_frequency_counts_recipes_not_lines():
    pack = make_pack(
        [
            R("r1", "A", L("a"), L("a", "b")),  # a appears on 2 lines of one recipe -> 1
            R("r2", "B", L("a"), L("c", opt=True)),
        ]
    )
    assert document_frequency(pack) == {"a": 2, "b": 1, "c": 1}


def test_popularity_sampler_frequency_on_tiny_pack():
    # df = {a: 3, b: 1}; d = 1 -> P(a) = 3/4. N = 4000 seeded draws.
    # sd = sqrt(.75 * .25 / 4000) = 0.00685, so a tolerance of 0.03 is about 4.4 sd.
    pack = make_pack(
        [R("r1", "A", L("a")), R("r2", "B", L("a")), R("r3", "C", L("a"), L("b"))],
    )
    assert document_frequency(pack) == {"a": 3, "b": 1}
    rng = random.Random(123)
    n = 4000
    hits = sum(sample_distractors("popularity", pack, set(), 1, rng) == ("a",) for _ in range(n))
    assert abs(hits / n - 0.75) < 0.03
    # uniform on the same pack gives 1/2
    rng = random.Random(123)
    hits = sum(sample_distractors("uniform", pack, set(), 1, rng) == ("a",) for _ in range(n))
    assert abs(hits / n - 0.5) < 0.03


def test_sample_distractors_exclude_exact_count_no_repeat_and_overdraw():
    pack = make_pack(
        [R("r1", "A", L("a"), L("b"), L("c")), R("r2", "B", L("e"), L("f"), L("g"))],
        extra=("x1", "x2", "x3", "x4"),
    )
    for sampler in ("uniform", "popularity"):
        got = sample_distractors(sampler, pack, {"a", "b", "c"}, 2, random.Random(1))
        assert len(got) == len(set(got)) == 2
        assert not set(got) & {"a", "b", "c", "salt"}
    # popularity ignores ids with df 0 (x1..x4): only e, f, g are left after excluding a, b, c
    assert len(sample_distractors("popularity", pack, {"a", "b", "c"}, 3, random.Random(1))) == 3
    with pytest.raises(ValueError):
        sample_distractors("popularity", pack, {"a", "b", "c"}, 4, random.Random(1))
    with pytest.raises(ValueError):
        sample_distractors("uniform", pack, {"a", "b", "c"}, 8, random.Random(1))  # 7 left
    with pytest.raises(ValueError):
        sample_distractors("sibling", pack, set(), 1, random.Random(1))


def _pantry_pack() -> Pack:
    recipes = [
        R(
            "g1",
            "Gold One",
            L("a"),
            L("b"),
            L("zz", "yy"),  # first option in sort order is yy
            L("d"),
            L("salt"),  # staple: never masked, never in pantry
            L("o", opt=True),  # optional
            L("u", read=False),  # unread but required -> total 5
        ),
        R("g2", "Gold Two", L("p"), L("q"), L("r")),
        R("g3", "Too Small", L("p"), L("q")),
    ]
    return make_pack(recipes, extra=tuple(f"x{i}" for i in range(10)))


def test_build_pantries_masking_and_distractors():
    pack = _pantry_pack()
    ps = build_pantries(pack, "uniform", 3, seed=7, draws=3)
    assert [p.gold_id for p in ps] == ["g1"] * 3 + ["g2"] * 3  # g3 not eligible
    gold_ids = {"a", "b", "zz", "yy", "d", "salt", "o", "u"}
    for p in ps[:3]:
        # g1: required non-staple = a, b, zz/yy, d, u -> total 5, m = 1, maskable 4 (u unread)
        assert len(p.masked) == 1
        assert p.masked[0] in {"a", "b", "yy", "d"}  # first option of zz/yy line is yy
        assert "zz" not in p.pantry and "salt" not in p.pantry and "o" not in p.pantry
        assert len(p.distractors) == 3
        assert not set(p.distractors) & gold_ids
        assert len(p.pantry) == 3 + 3  # 3 kept lines + 3 distractors
        assert p.masked[0] not in p.pantry
        assert list(p.pantry) == sorted(p.pantry)
        assert p.sampler == "uniform"
    # g2: total 3, m = 1 -> pantry holds 2 kept ids
    assert all(len(p.masked) == 1 for p in ps[3:])


def test_build_pantries_deterministic_and_masks_shared_across_d():
    pack = _pantry_pack()
    a = build_pantries(pack, "popularity", 3, seed=7)
    assert a == build_pantries(pack, "popularity", 3, seed=7)
    assert a != build_pantries(pack, "popularity", 3, seed=8)
    # the mask is drawn before distractors, so masks do not depend on d or sampler
    z = build_pantries(pack, "uniform", 0, seed=7)
    assert [p.masked for p in a] == [p.masked for p in z]


def test_sampler_none_only_when_d_zero():
    pack = _pantry_pack()
    with pytest.raises(ValueError):
        build_pantries(pack, "none", 3)
    for p in build_pantries(pack, "none", 0):
        assert p.sampler == "none" and p.distractors == ()
    # d == 0 records "none" even when a real sampler is named
    assert {p.sampler for p in build_pantries(pack, "uniform", 0)} == {"none"}


def test_dev_test_disjoint_and_balanced_on_fixture_pack():
    from pathlib import Path

    from pantrychef.engine import load_pack

    pack = load_pack(Path(__file__).resolve().parents[1] / "fixtures" / "pack", "v1")
    sp = assign_splits(list(pack.recipes))
    assert set(sp) == {r.recipe_id for r in pack.recipes}
    # fixture titles are unique, so each recipe is its own group
    n_dev = sum(v == "dev" for v in sp.values())
    n_test = sum(v == "test" for v in sp.values())
    assert abs(n_dev - n_test) <= 1 and n_dev + n_test == 47
    ps = build_pantries(pack, "uniform", 3)
    dev = {p.gold_id for p in ps if p.split == "dev"}
    test = {p.gold_id for p in ps if p.split == "test"}
    assert dev and test and dev.isdisjoint(test)
