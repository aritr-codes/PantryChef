# Licences

This file lists the licence of each path and artifact. It is an engineering record, not
legal advice. For sources and hashes, read [docs/DATASET.md](docs/DATASET.md). For the
reasons, read [ADR 0003](docs/decisions/0003-licence-clean-recipe-corpus.md).

## In git

| Path | Licence | Note |
| --- | --- | --- |
| Code and docs, unless listed below | MIT ([LICENSE](LICENSE)) | |
| `data/eval/curated_subs.json`, `data/eval/curated_diets.json` | MIT | Hand-written evaluation lists |
| `data/nutrition/dietary_labels.json` | MIT | Hand-written labels |
| `data/nutrition/aliases.json` | MIT, origin under review | Hand-written map to USDA ids, chosen by frequency in RecipeNLG. Unused in v1. Review at M9 |
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
| Wikibooks Cookbook snapshot (`data/raw/wikibooks_cookbook/`) | CC BY-SA 4.0. Third-party scrape, used for measurement only | Measurement | Not this copy. M1 builds a snapshot from the official MediaWiki API, with revision ids |
| USDA FoodData Central (`data/raw/usda_fdc/`, `data/processed/usda.json`) | Public domain. USDA asks for a citation of release and date | Nutrition research | Only after M9 |

## Planned release artifacts

None of these exist yet. Each one will appear in a manifest with its hash and licence.

| Artifact | Licence | Note |
| --- | --- | --- |
| Web app code | MIT | |
| `text.vN.json.gz`, `core.vN.json.gz` | CC BY-SA 4.0 | Adapted from Wikibooks. Each recipe shows its source link, revision and licence. Changes are recorded |
| `mined.vN.json.gz` | CC BY 3.0 statistics, with credit | Only if mined swaps pass M5 |
| Committed test fixtures with recipe text | CC BY-SA 4.0 | Under a path with its own notice |
