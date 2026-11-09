"""Coverage of the pack rules and the M3 growth row. Invented 5-page snapshot and invented table."""

from __future__ import annotations

import json
from pathlib import Path

from pantrychef.eval.parser_gold import line_hash
from pantrychef.eval.results import load_result
from pantrychef.ingredients.table import TABLE_V2_PATH, IngredientTable
from pantrychef.pack.build import _core_recipe, coverage
from pantrychef.sources.wikibooks import parse_page
from scripts.ingredient_coverage import (
    dev_scores,
    growth_row,
    read_id_map,
    top_unread,
    write_growth,
)

ROOT = Path(__file__).resolve().parent.parent
TABLE = IngredientTable.from_text(
    "id,name,synonyms,staple,provenance,is_a,form_of\n"
    "salt,salt,,1,hand,,\n"
    "black_pepper,black pepper,,1,hand,,\n"
    "butter,butter,,0,hand,,\n"
    "flour,flour,,0,hand,,\n"
    "egg,egg,,0,hand,,\n"
)
# page -> ingredient lines
PAGES = {
    "Alpha": ["2 cups flour", "1 egg"],  # kept, all read
    "Beta": ["1 cup flour", "3 zorblat"],  # kept, one unread
    "Gamma": ["salt"],  # staple only: the pack drops it
    "Delta": ["2 tbsp butter", "1 tsp frobnitz (optional)"],  # kept, optional line is skipped
    "Epsilon": ["3 ZORBLAT", "2 Wibble Sauce"],  # kept, two unread
}


def _recipes():
    out = []
    for i, (title, lines) in enumerate(PAGES.items()):
        body = "".join(f"*{ln}\n" for ln in lines)
        rec = {
            "page_id": str(i),
            "title": f"Cookbook:{title}",
            "revision_id": "1",
            "timestamp": "2026-01-01T00:00:00Z",
            "wikitext": f"==Ingredients==\n{body}\n==Procedure==\n#Mix.\n",
        }
        out.append(parse_page(rec, "2026-01-01"))
    return out


def test_coverage_matches_a_hand_count():
    recipes = _recipes()
    cov = coverage(recipes, TABLE)
    assert cov["kept_recipes"] == 4  # Gamma has only a staple line
    assert cov["fully_read"] == 2  # Alpha and Delta
    assert cov["recipes_fully_read"] == 0.5
    assert cov["required_lines"] == 8 and cov["lines_read"] == 5
    assert cov["optional_lines"] == 1
    assert sorted(cov["unread"]) == ["2 Wibble Sauce", "3 ZORBLAT", "3 zorblat"]


def test_coverage_keeps_the_recipes_the_pack_keeps():
    recipes = _recipes()
    kept = [r for r in recipes if _core_recipe(r, TABLE) is not None]
    assert coverage(recipes, TABLE)["kept_recipes"] == len(kept) == 4


def test_coverage_of_nothing_is_zero():
    assert coverage([], TABLE)["recipes_fully_read"] == 0.0


def test_a_frozen_line_never_counts_in_top_unread_in_any_case():
    unread = coverage(_recipes(), TABLE)["unread"]
    assert top_unread(unread, TABLE, frozenset(), 10) == [["zorblat", 2], ["wibble sauce", 1]]
    frozen = frozenset({line_hash("3 Zorblat")})  # both the "zorblat" lines hash to this
    assert top_unread(unread, TABLE, frozen, 10) == [["wibble sauce", 1]]
    assert top_unread(unread, TABLE, frozenset(), 1) == [["zorblat", 2]]


def test_growth_file_appends_a_row_each_run_and_stays_valid(tmp_path):
    cov = coverage(_recipes(), TABLE)
    parser = {"gold_groups": 10, "mention_accuracy": 0.5, "pred_groups": 8, "precision": 0.75}
    inputs = {"n": 4, "input_accuracy": 0.25}
    path = tmp_path / "growth.json"
    for _ in range(2):
        row = growth_row("c" * 40, TABLE, cov, parser, inputs, [["zorblat", 2]])
        write_growth(path, row, cov, parser, inputs, fingerprint="f" * 64, command="x")
    doc = load_result(path)
    rows = doc["config"]["rows"]
    assert len(rows) == 2
    assert rows[1] == {
        "commit": "c" * 40,
        "resolver": "resolve_name",
        "rows": 5,
        "lines_read": 5,
        "recipes_fully_read": 0.5,
        "mention_accuracy_dev": 0.5,
        "parser_precision_dev": 0.75,
        "input_accuracy_dev": 0.25,
        "top_unread": [["zorblat", 2]],
        "dev_scoring": "table_keys",
        "id_map": None,
    }
    got = {m["name"]: (m["n"], m["value"]) for m in doc["metrics"]}
    assert got == {
        "recipes_fully_read": (4, 0.5),
        "mention_accuracy": (10, 0.5),
        "parser_precision": (8, 0.75),
        "input_accuracy": (4, 0.25),
    }
    assert json.loads(path.read_text(encoding="utf8"))["corpus_fingerprint"] == "f" * 64


def test_growth_row_with_an_id_map_is_labelled_and_old_rows_are_marked(tmp_path):
    cov = coverage(_recipes(), TABLE)
    parser = {"gold_groups": 10, "mention_accuracy": 0.5, "pred_groups": 8, "precision": 0.75}
    inputs = {"n": 4, "input_accuracy": 0.25}
    path = tmp_path / "growth.json"
    old = growth_row("a" * 40, TABLE, cov, parser, inputs, [])
    del old["dev_scoring"], old["id_map"]  # a row written before the id map existed
    write_growth(path, old, cov, parser, inputs, fingerprint="f" * 64, command="x")
    new = growth_row("b" * 40, TABLE, cov, parser, inputs, [], "data/eval/map.json")
    write_growth(path, new, cov, parser, inputs, fingerprint="f" * 64, command="y")
    rows = load_result(path)["config"]["rows"]
    assert [(r["dev_scoring"], r["id_map"]) for r in rows] == [
        ("table_keys", None),
        ("id_map", "data/eval/map.json"),
    ]


MAP_PATH = ROOT / "data/eval/parser_gold/dev_id_map.v1.json"


def test_frozen_dev_id_map_points_at_ids_that_exist():
    table = IngredientTable.load(TABLE_V2_PATH)
    id_map = read_id_map(MAP_PATH)
    assert len(id_map) == 134 and sum(v is None for v in id_map.values()) == 14
    assert [v for v in id_map.values() if v is not None and v not in table.by_id] == []


def test_dev_scores_with_the_id_map_score_the_random_stratum_and_ignore_table_keys():
    table = IngredientTable.load(TABLE_V2_PATH)
    id_map = read_id_map(MAP_PATH)
    parser, _ = dev_scores(table, id_map)
    assert parser["lines"] == 150 and parser["random_stratum"]["lines"] == 50
    assert 0 < parser["random_stratum"]["mention_accuracy"] <= 1
    assert 0 < parser["mention_accuracy"] <= 1
    # The map does not depend on the keys. Without a map, a name loses its id when its key goes.
    rows = [
        type(r)(r.id, r.name, (), r.staple, r.provenance, r.is_a, r.form_of)
        if r.id == "chili_pepper"
        else r
        for r in table.rows
    ]
    thin = IngredientTable(rows, table.words)
    assert dev_scores(thin, id_map)[0]["gold_out_of_table"] == parser["gold_out_of_table"]
    assert dev_scores(thin)[0]["gold_out_of_table"] > dev_scores(table)[0]["gold_out_of_table"]
