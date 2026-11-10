# Datasets

Provenance, licenses, schema, and preprocessing for every data source. Data
files themselves are gitignored — this file is the source of truth for *what*
the data is and *how to reproduce* it.

> Update whenever a dataset is added, a version changes, or preprocessing
> changes.

Licence rules for each path are in [LICENSES.md](../LICENSES.md).

## Snapshots

Git ignores these files. The sha256 values below were computed from the files on disk on
2026-10-30, and the first two match [ADR 0003](decisions/0003-licence-clean-recipe-corpus.md).

| File under `data/raw/` | Source | Size in bytes | sha256 |
| --- | --- | --- | --- |
| `wikibooks_cookbook/recipes_parsed.mini.json` | `gossminn/wikibooks-cookbook` on Hugging Face. Third-party scrape, dated 2024-07-31, with no revision ids. Measurement only. M1 replaces it | 10008463 | `67fd704a6d9280742d2f217ad9f9e4f50921b84fcdefdff9bac749a518c4d46b` |
| `wikibooks/snapshot.2026-11-03.jsonl.gz` | Official MediaWiki API, built by `scripts/fetch_wikibooks.py` on 2026-11-03. 3,865 Cookbook pages, with a revision id and timestamp for each. CC BY-SA 4.0. This is the display corpus snapshot. The release copy is not published yet | 2501026 | `a1a076ab0aee385c4e01cdc904342214dfaa6b01dc35d80d32519ea625c597d2` |
| `openrecipes/20170107-061401-recipeitems.json.gz` | `napsternxg/openrecipes-20170107-061401-recipeitems` on Hugging Face. The original S3 URLs now return 403 | 30795953 | `6e40a82e0bd83468f8020b461924d9d6cf8bdba822642c5276868104acb6d682` |
| `full_dataset.csv` | RecipeNLG, manual download. Research only | 2294981083 | `f376ee0bb9f99f323761abf6270d453f4eff2002c3625d04cabcf8b57dca0803` |
| `dataset.zip` | RecipeNLG source archive. Research only | 620612136 | `1428b7e0029e3b74c63810e4a2fca1533baabd662bb024b57ca517d71b8f895e` |

## Sources

### Wikibooks Cookbook  (planned display corpus)
- **Licence:** CC BY-SA 4.0. **Size:** about 3,800 recipes with an ingredient list.
- **Status:** M1 fetched an official snapshot on 2026-11-03 (see the table above). 3,713 of its
  3,865 pages have an ingredient list. The third-party scrape stays for measurement only.

### Open Recipes  (planned statistics corpus)
- **Licence:** CC BY 3.0 for the database. **Size:** 173,276 recipes with ingredients. It
  has no instructions.
- **Status:** statistics only. Derived statistics ship only if mined swaps pass M5. Its text
  and images never ship.

### RecipeNLG  (research corpus; never ships)
- **Size:** ~2.23M recipes; text-only (small footprint).
- **Why:** ships food-entity NER; large + deduplicated; fits free tier.
- **Access:** HuggingFace `mbien/recipe_nlg`; original at
  `recipenlg.cs.put.poznan.pl`.
- **License:** non-commercial research and education. No text, vocabulary or trained
  artifact ships ([ADR 0003](decisions/0003-licence-clean-recipe-corpus.md)).
- **Schema (raw):** `title`, `ingredients` (free text), `directions`, `NER`
  (extracted food entities), `link`, `source`.
- **Preprocessing (Phase 1):**
  1. Manual download `full_dataset.csv` → `data/raw/` (terms acceptance).
  2. `uv run python scripts/download_data.py --max-rows N --min-count 5`:
     - Pass 1 builds `data/processed/vocab.json` from the `NER` column
       (canonicalized, frequency-filtered at `min_count`).
     - Pass 2 writes `data/processed/recipes.jsonl` (cleaned, deduped by title,
       canonical ingredient sets).
  3. Record `N`, vocab size, and recipe count of each run here.
- **Splits:** assigned at training time (Phase 2+); Phase 1 retrieval eval is
  leave-one-ingredient-out over the full processed set (seed=42).

### Evaluation sets (M2)

| File | What it is | Licence | Rule |
| --- | --- | --- | --- |
| `data/eval/realistic_inputs.v1.json` | 166 pantry phrases from the audit script `b_parser.py` (inputs only; the old acceptance sets are dropped) | MIT | Frozen before M3 table work |
| `data/eval/realistic_inputs.split.v1.json` | Dev/test split, 83 and 83. Seed 42. Sorted by sha256 inside each category, then alternating. Records the sha256 of the input list (`c69c0a04e54a094ef51038033ad6e33e656e5dfabf94501b9aa7e4654f2d89e0`) | MIT | Test stays unread until M3 acceptance. The M1 table has seen the inputs (it lists `evoo`) |
| `data/eval/parser_gold/sheet.v1.json` | 300 Wikibooks ingredient lines. Strata `random`, `hard`, `rare`, 100 each. Dev 150, test 150. Built from `wikibooks/snapshot.2026-11-03.jsonl.gz` | CC BY-SA 4.0 | Labels are model-written (Sonnet and Opus, adjudicated), not human. Test labels stay unscored until M3 acceptance |
| `data/eval/floors.v1.json` | CI floors on the fixture pack | MIT | A guard against code regressions. Not a quality claim |

Rebuild: `uv run python scripts/extract_realistic_inputs.py`, `uv run python scripts/make_parser_gold_sheet.py`, `uv run python scripts/make_floors.py`.

### Ingredient table v2 (M3)

- **File:** `data/ingredients/ingredients.v2.csv`. The M1 table `ingredients.csv` (337 rows) stays as the M1 reference.
- **Columns:** `id,name,synonyms,staple,provenance,is_a,form_of`. `is_a` and `form_of` hold the edges that [ADR 0006](decisions/0006-hybrid-graph-knowledge-base.md) proposed. The ADR is rejected (the M3 spike found no new recipes), so the columns stay as data. The resolver does not read them.
- **Size (MEASURED, counted from the file):** 872 rows. 4 rows are staples. 81 rows have an `is_a` value and 75 have a `form_of` value.
- **Provenance column:** 493 rows say `hand` and 379 rows say `wikibooks-rule`. The code accepts only these two values (`pantrychef/ingredients/table.py`).
- **Who made it:** the M1 rows were written by hand. Implementer agents grew the table in review rounds during M3. Growth mines unread phrases from the Wikibooks snapshot and leaves out every frozen test and extra line. The table only grows: v2 never removes or renames a v1 id. The commit history of the file records each round.
- **Licence:** MIT ([LICENSES.md](../LICENSES.md)). It is not derived from RecipeNLG and never reads `data/processed/vocab.json`.
- **Held out:** no. The table is the thing under test. The held-out data is the test and extra lines, below.

### Word file (M3)

- **File:** `data/ingredients/words.v1.json`. It replaces word lists that lived in code.
- **Keys:** `units` (50 spellings, each mapped to one unit), `size` (3 words), `container` (15), `prep` (94 preparation and filler words), `staple_cue` (`["salt"]`), `bare_pepper` (the rule for a bare "pepper" line: target `black_pepper`, `when` is `staple_cue_or_taste`) and `trailing_ok` (62 words). Counts are MEASURED from the file.
- **Use:** the Python line resolver reads it at pack build. The pack core carries a copy. The browser reads that copy to resolve typed names.
- **Licence:** MIT. **Made by:** hand and implementer agents. **Held out:** no. M3 rounds edited it (for example `trailing_ok`). The file hash is in the pack manifest and in `results/m3_pack_v2.json`.

### M3 evaluation files

All paths are under `data/eval/`. Labels written by models are not human labels. Each model-labelled set says so.

| File | What it is | Made by | Licence | Held out? |
| --- | --- | --- | --- | --- |
| `parser_gold/extra.v1.json` | 100 more Wikibooks lines. Uniform random draw, seed 43, not in `sheet.v1.json` | Script `make_m3_extra_lines.py` on the snapshot | CC BY-SA 4.0 | Yes. Unread until acceptance |
| `parser_gold/labels.test.v2.json`, `labels.extra.v1.json`, `adjudication.m3.v1.json` | Labels for the 150 test lines and the 100 extra lines, and the settled disagreements | Fresh Opus (and Sonnet on the extra lines) blind, then the owner settled them (see the plan, D1) | MIT | Yes. Unread until acceptance |
| `realistic_inputs.labels.v1.json` | Gold ingredient names for the 166 typed inputs | Sonnet and Opus blind, then the owner settled disagreements (plan D4) | MIT | The test entries: yes. Dev entries: no |
| `m3_frozen_lines.v1.json` | sha256 of the `casefold().strip()` text of each of the 250 test and extra lines | Script | MIT | It holds hashes only. Table growth must not read these lines |
| `parser_gold/dev_id_map.v1.json` | Dev gold name to table id (134 names, 14 with no id). Made at commit `b8a76c7` from the dev gold names and the table, with no predictions in view | One Opus model, blind. Nobody edited it | MIT | No. It is a dev file |
| `m3_bare_pepper_labels.v1.json` | 80 bare "pepper" lines, seed 45, labelled `black`, `other` or `unclear`. No frozen line is in it | One Opus model, blind. The owner did not adjudicate | Text CC BY-SA 4.0. Labels MIT | No. It decides the bare pepper rule (see [EVALUATION.md](EVALUATION.md)) |

The acceptance run uses two blind gold-to-id maps for the test data: `data/eval/m3_gold_id_map.v1.json` (206 gold names, 16 map to no table row) and `data/eval/m3_input_gold_id_map.v1.json` (142 gold names). A fresh Opus model made each map from the gold names and the v2 table only, never from a resolver prediction (plan D9). The owner checked every mapping that differs from the plain table-key lookup (15 and 1 rows) and accepted all of them without change. `data/eval/graph_spike/` holds the frozen inputs of the ADR 0006 spike (freeze commit `e33e630`). The spike ended at an empty pool, so nobody rated anything (see [EVALUATION.md](EVALUATION.md)). Its 40 pantries stay dev pantries.

Attribution for Wikibooks text and the label notes are in `data/eval/parser_gold/NOTICE.md`.

### USDA FoodData Central  (Phase 4 — nutrition)
- **Why:** authoritative free nutrition data (macros + micros).
- **Access:** free bulk CSV download (FoodData Central full-download datasets).
- **Bundles used (record release + date):**
  - **SR Legacy** bundle release **2018-04** — 7,793 `sr_legacy_food` entries.
  - **Foundation Foods** bundle release **2025-04-24** — 411 `foundation_food`
    entries. (This bundle also ships ~73.7k lab-sampling metadata rows —
    `sub_sample_food` / `market_acquisition` / `sample_food` /
    `agricultural_acquisition` — which `scripts/fetch_usda.py` filters **out**
    via a `data_type` whitelist; only `sr_legacy_food` + `foundation_food` are
    kept.)
- **Artifact:** combined → `data/processed/usda.json` = **8,204 foods**
  (gitignored — large and regenerable).
- **License:** **public domain** (U.S. Government work, no copyright). FDC is
  freely redistributable; it requests citation of the **release + date**. (Unlike
  the GISMo benchmark below, which is CC BY-NC.) We still gitignore the artifact
  because it is large and regenerable.
- **Use:** join parsed ingredient + quantity → per-recipe nutrition **estimates**
  (no per-serving — RecipeNLG has no servings field).
- **Regenerate:** `uv run python scripts/fetch_usda.py --csv-dir <dir>` (point at
  the unzipped FDC CSV directory). Record release dates + food count of each run
  here.

### Vision test photos  (planned, gated in M8)
- **Status:** not chosen. Record the source and licence here before any use.

### Recipe1M+  (deferred — multimodal)
- **Size:** 1M recipes + 13M images (image dump huge).
- **Status:** not used. It has separate terms and never ships.

### Substitution ground-truth test set  (Phase 2 — eval)
- **Source:** "Exploiting Food Embeddings for Ingredient Substitution" repo.
- **Use:** was planned for evaluation. The repo uses mined gold and GISMo gold instead, and
  neither ships ([LICENSES.md](../LICENSES.md)).

## Reproducibility

- `scripts/download_data.py` cleans a RecipeNLG CSV that you download by hand. It does not
  download anything.
- Raw → `data/raw/`, cleaned → `data/interim/`, final → `data/processed/`.
- Record dataset version + download date + row counts per source here.
