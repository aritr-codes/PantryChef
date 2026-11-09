# Licences

This file lists the licence of each path and artifact. It is an engineering record, not
legal advice. For sources and hashes, read [docs/DATASET.md](docs/DATASET.md). For the
reasons, read [ADR 0003](docs/decisions/0003-licence-clean-recipe-corpus.md).

## In git

| Path | Licence | Note |
| --- | --- | --- |
| Code and docs, unless listed below | MIT ([LICENSE](LICENSE)) | |
| `data/eval/curated_subs.json`, `data/eval/curated_diets.json` | MIT | Hand-written evaluation lists |
| `data/eval/realistic_inputs.v1.json`, `data/eval/realistic_inputs.split.v1.json` | MIT | 166 short pantry phrases from the audit, with a seeded dev/test split. They hold no recipes |
| `data/eval/parser_gold/sheet.v1.json` | CC BY-SA 4.0 | 300 ingredient lines copied from Wikibooks, with page and revision. See the `NOTICE.md` in that folder |
| `data/eval/parser_gold/labels.*.v1.json`, `data/eval/parser_gold/adjudication.v1.json`, `data/eval/floors.v1.json`, `data/eval/judging/pilot_key_sha256.txt` | MIT | Model-written labels (not human), CI floors and one hash |
| `data/eval/judging/pilot_sheet.v1.json` | CC BY-SA 4.0 | Wikibooks titles and ingredient lines for the judging pilot. See the `NOTICE.md` in that folder |
| `results/*.json` | MIT | Aggregate numbers with provenance. They hold no recipe text |
| `data/nutrition/dietary_labels.json` | MIT | Hand-written labels |
| `data/nutrition/aliases.json` | MIT, origin under review | Hand-written map to USDA ids, chosen by frequency in RecipeNLG. Unused in v1. Review at M9 |
| `data/ingredients/ingredients.csv`, `data/ingredients/ingredients.v2.csv`, `data/ingredients/words.v1.json` | MIT | Hand-written ingredient tables (names, synonyms, staple flag) and word lists. Not derived from RecipeNLG. Each row records its provenance |
| `tests/fixtures/pack/`, `tests/golden/` | MIT | Synthetic fixture pack and golden parity file. The recipes are invented. They hold no Wikibooks text |
| `tests/fixtures/wikibooks/` | CC BY-SA 4.0 | Whole Wikibooks Cookbook pages and lines, copied unchanged for parser tests. See the `NOTICE.md` in that folder |
| `docs/research/2026-10-stage1/` | MIT | Audit record. It holds counts, metrics and short ingredient phrases from RecipeNLG, and no recipes. `evidence/subs_out.json` is withheld, and git ignores it |

## Not in git

Git ignores `data/raw/`, `data/processed/` and `models/`.

| Item | Licence or terms | Use | May ship? |
| --- | --- | --- | --- |
| RecipeNLG (`data/raw/full_dataset.csv`) | Non-commercial research and education. Some rows are tagged `Recipes1M`, which has separate terms | Research only | **Never**, including text, vocabulary and trained artifacts |
| `data/processed/recipes.jsonl`, `vocab.json` | RecipeNLG terms | Research only | **Never** |
| `models/recommender/`, `models/substitution/` | Derived from RecipeNLG | Research only | **Never** |
| Recipe1M | Separate terms | Not used | **Never** |
| `data/eval/subs_gold.csv` | Mined from RecipeNLG | Research only | **Never** |
| GISMo gold files (`data/raw/gismo/`, `data/eval/subs_gold_gismo.csv`) | CC BY-NC 4.0 | Research only | **Never** |
| Open Recipes snapshot (`data/raw/openrecipes/`) | CC BY 3.0, database licence. This does not clear each publisher's rights | Statistics only | Text and images **never**. Derived statistics only if mined swaps pass M5, with a credit on the About page |
| Wikibooks Cookbook third-party scrape (`data/raw/wikibooks_cookbook/`) | CC BY-SA 4.0. Third-party scrape with no revision ids, used for measurement only | Measurement | Not this copy |
| Wikibooks Cookbook official snapshot (`data/raw/wikibooks/`) | CC BY-SA 4.0. Built by `scripts/fetch_wikibooks.py` from the MediaWiki API, with a revision id per page | Source of the display pack | Only as the adapted pack below. The release copy of the snapshot is not published yet |
| USDA FoodData Central (`data/raw/usda_fdc/`, `data/processed/usda.json`) | Public domain. USDA asks for a citation of release and date | Nutrition research | Only after M9 |

## Planned release artifacts

The pack builder writes `core` and `text` and `manifest` into `build/pack` (git ignores it). No release exists yet. The Pages workflow reads the pack from the GitHub Release `pack-v2` and checks it against the hashes in `web/pack-hashes.json`. The hosted site then serves the pack files under CC BY-SA 4.0. Each file appears in the manifest with its hash and licence.

| Artifact | Licence | Note |
| --- | --- | --- |
| Web app code | MIT | |
| `text.vN.json.gz`, `core.vN.json.gz` | CC BY-SA 4.0 | Adapted from Wikibooks. Each recipe shows its source link, revision and licence. Changes are recorded |
| `manifest.vN.json` | MIT | Counts, hashes, sizes, licences and input hashes. No recipe text |
| `mined.vN.json.gz` | CC BY 3.0 statistics, with credit | Only if mined swaps pass M5 |
| Committed test fixtures with recipe text | CC BY-SA 4.0 | Under a path with its own notice |
