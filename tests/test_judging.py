"""Judging pilot: hand-computed scoring on a 6-item key, and sheet-builder properties."""

import json
from pathlib import Path

import pytest

from pantrychef.engine import load_pack
from scripts.judging_score import power_estimate, score
from scripts.judging_sheet import build_sheet, write_outputs

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "pack"

# i5 repeats i1 and i6 repeats i2. Left/right arms per item.
KEY = {
    "i1": {"left": "shipped", "right": "overlap", "repeat_of": None},
    "i2": {"left": "overlap", "right": "shipped", "repeat_of": None},
    "i3": {"left": "shipped", "right": "overlap", "repeat_of": None},
    "i4": {"left": "overlap", "right": "shipped", "repeat_of": None},
    "i5": {"left": "overlap", "right": "shipped", "repeat_of": "i1"},
    "i6": {"left": "shipped", "right": "overlap", "repeat_of": "i2"},
}
# (choice, would_cook_left, would_cook_right, seconds)
ANS = {
    "i1": ("A", "yes", "no", 10),  # left = shipped wins
    "i2": ("A", "yes", "yes", 20),  # left = overlap wins
    "i3": ("B", "yes", "no", 30),  # right = overlap wins
    "i4": ("tie", "no", "yes", 40),  # tie
    "i5": ("B", "no", "yes", 50),  # right = shipped wins (same as i1)
    "i6": ("A", "yes", "no", 60),  # left = shipped wins (i2 was overlap)
}
ROWS = [
    {
        "item_id": i,
        "choice": c,
        "would_cook_left": wl,
        "would_cook_right": wr,
        "seconds": str(s),
    }
    for i, (c, wl, wr, s) in ANS.items()
]


def test_score_hand_computed():
    r = score(KEY, ROWS)
    # Base items i1..i4: shipped wins 1, overlap wins 2, tie 1.
    assert (r["shipped_wins"], r["overlap_wins"], r["ties"], r["n_base"]) == (1, 2, 1, 4)
    assert r["win_rate_ties_excluded"] == pytest.approx(1 / 3)
    assert r["win_rate_ties_as_half"] == pytest.approx(1.5 / 4)
    assert r["tie_rate"] == pytest.approx(0.25)
    # Repeats: (i1,i5) both shipped = same. (i2,i6) overlap vs shipped = different.
    assert (r["repeats_same"], r["repeats_total"]) == (1, 2)
    assert r["median_seconds"] == 35  # 10,20,30,40,50,60
    # Would cook, base items. Shipped side: i1 L yes, i2 R yes, i3 L yes, i4 R yes = 4/4.
    # Overlap side: i1 R no, i2 L yes, i3 R no, i4 L no = 1/4.
    assert r["would_cook_shipped"] == pytest.approx(1.0)
    assert r["would_cook_overlap"] == pytest.approx(0.25)


def test_power_estimate_hand_computed():
    # p = 1/3: 1.96^2 * (2/9) / 0.1^2 = 85.37 -> 86 non-tie pantries; 86 / 0.75 = 114.7 -> 115.
    # Worst case p = 0.5: 1.96^2 * 0.25 / 0.01 = 96.04 -> 97 non-tie; 97 / 0.75 = 129.3 -> 130.
    p = power_estimate(1 / 3, 0.25)
    assert (p["non_tie_needed"], p["pantries_needed"]) == (86, 115)
    assert (p["worst_non_tie_needed"], p["worst_pantries_needed"]) == (97, 130)
    assert power_estimate(0.5, 1.0)["pantries_needed"] is None


def test_score_rejects_unknown_item_and_bad_choice():
    with pytest.raises(ValueError):
        score(KEY, [{**ROWS[0], "item_id": "zz"}])
    with pytest.raises(ValueError):
        score(KEY, [{**ROWS[0], "choice": "C"}])


@pytest.fixture(scope="module")
def built():
    pack = load_pack(FIXTURE)
    return build_sheet(pack, seed=42, n=6, repeats=2, d=3)


def test_sheet_is_blind_and_shaped(built):
    sheet, key = built
    text = json.dumps(sheet)
    assert len(sheet["items"]) == 8 == len(key["items"])
    for word in ("shipped", "overlap", "gold", "repeat"):
        assert word not in text
    for it in sheet["items"]:
        assert len(it["left"]) == len(it["right"]) == 5
        assert it["pantry"] == sorted(it["pantry"]) and all(
            isinstance(x, str) for x in it["pantry"]
        )
        for rec in it["left"] + it["right"]:
            assert set(rec) == {"title", "missing"}


def test_repeats_same_pantry_not_adjacent(built):
    sheet, key = built
    ids = [it["item_id"] for it in sheet["items"]]
    reps = {i: v["repeat_of"] for i, v in key["items"].items() if v["repeat_of"]}
    assert len(reps) == 2
    for rep, orig in reps.items():
        a, b = ids.index(rep), ids.index(orig)
        assert abs(a - b) >= 2
        by_id = {it["item_id"]: it for it in sheet["items"]}
        assert by_id[rep]["pantry"] == by_id[orig]["pantry"]
        assert key["items"][rep]["gold_id"] == key["items"][orig]["gold_id"]
    # base items use distinct gold recipes
    base = [v["gold_id"] for v in key["items"].values() if not v["repeat_of"]]
    assert len(set(base)) == 6


def test_sheet_is_deterministic(built):
    again = build_sheet(load_pack(FIXTURE), seed=42, n=6, repeats=2, d=3)
    assert again == built


def test_key_hash_is_pinned(built, tmp_path):
    sheet, key = built
    s, k, h = tmp_path / "s.json", tmp_path / "k.json", tmp_path / "h.txt"
    write_outputs(sheet, key, s, k, h)
    import hashlib

    assert h.read_text().strip() == hashlib.sha256(k.read_bytes()).hexdigest()
    write_outputs(sheet, key, s, k, h)  # same key: fine
    key2 = {**key, "seed": 43}
    with pytest.raises(SystemExit):
        write_outputs(sheet, key2, s, k, h)
