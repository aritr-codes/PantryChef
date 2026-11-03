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
| `data/eval/parser_gold/sheet.v1.json` | 300 Wikibooks ingredient lines. Strata `random`, `hard`, `rare`, 100 each. Dev 150, test 150. Built from `wikibooks/snapshot.2026-11-03.jsonl.gz` | CC BY-SA 4.0 | Labels come from the owner. Test labels stay unscored until M3 acceptance |
| `data/eval/floors.v1.json` | CI floors on the fixture pack | MIT | A guard against code regressions. Not a quality claim |

Rebuild: `uv run python scripts/extract_realistic_inputs.py`, `uv run python scripts/make_parser_gold_sheet.py`, `uv run python scripts/make_floors.py`.

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
