# PantryChef

A person lists the ingredients they have. PantryChef is being built to show what they can
cook now and the one item that unlocks more. It uses conventional machine learning (ML),
information retrieval and deterministic logic. It uses no large language model (LLM) for
core features ([ADR 0002](docs/decisions/0002-no-llm-substitution.md)).

**Status: research code. The app does not exist yet.** The repo holds a tested Python
library and an audit of its own results. For the full state, read
[docs/PROJECT_STATE.md](docs/PROJECT_STATE.md). Licences: code is MIT, and data rules are
in [LICENSES.md](LICENSES.md).

## Built and planned

| Capability | Built | Planned |
| --- | --- | --- |
| Ingredient parser | Rules plus vocabulary match: [`pantrychef/ingredients/parser.py`](pantrychef/ingredients/parser.py) | Unicode fractions are handled for Wikibooks lines (M1). A model-labelled gold set (M2) |
| Search | Set-overlap baseline and the `cook` command: [`pantrychef/retrieval/`](pantrychef/retrieval/), [`pantrychef/cli.py`](pantrychef/cli.py) | Built (M1): `answer()` in [`pantrychef/engine.py`](pantrychef/engine.py) gives groups by missing items, top unlocks and blockers, and `cook --pack` prints it. A TypeScript copy is in [`web/src/engine.ts`](web/src/engine.ts), checked against golden cases | Hand-judged quality evaluation (M2) |
| Ranking | Research only. A candidate pool and a LambdaMART ranker: [`pantrychef/recommender/`](pantrychef/recommender/). Only tests call its runtime | Ships only if it beats an IDF rule on hand-judged pantries (M4, [ADR 0005](docs/decisions/0005-honest-claims-and-eval-reset.md)) |
| Substitution | Graph and embedding arms, and the `substitute` command: [`pantrychef/substitution/`](pantrychef/substitution/). Mined from RecipeNLG, so it cannot ship | A curated table, and swaps mined from Open Recipes if they pass a blind rating (M5) |
| Dietary filter | Built, but not safe to rely on: [`pantrychef/dietary/`](pantrychef/dietary/). See [audit C2](docs/TECHNICAL_AUDIT.md#c2-the-dietary-filter-is-unsafe-and-its-metric-cannot-fail-verified) | Three-state preference flags from a curated table, with no allergen claim (M5) |
| Nutrition | Built, not fit to show: [`pantrychef/nutrition/`](pantrychef/nutrition/). See [audit C3](docs/TECHNICAL_AUDIT.md#c3-nutrition-output-is-not-fit-to-show-verified) | Stays out unless USDA FNDDS validation passes (M9) |
| Web app | Built (M1, M6 polish): Preact app in [`web/`](web/). One page with the kitchen and the answer side by side, plus a recipe view. It saves the kitchen on the device (ingredient ids and staple switches only). The live site <https://aritr-codes.github.io/PantryChef/> shows this page since 2026-11-10 (the `pages.yml` workflow ran after the pack upload) | Latency and device checks of the new page (M1 follow-up). Remaining polish (M6, [ADR 0004](docs/decisions/0004-static-first-browser-engine.md)) |
| Recipes for display | Built (M1): a pack of 3,712 Wikibooks Cookbook recipes, CC BY-SA 4.0, from [`pantrychef/pack/`](pantrychef/pack/). The pack is not in git. M3 built pack v2 (same 3,712 recipes, 894-row table, hashes in `web/pack-hashes.json`). The Release `pack-v1` holds the M1 pack, and the Release `pack-v2` holds pack v2 ([ADR 0003](docs/decisions/0003-licence-clean-recipe-corpus.md)) | A held-out check of how well lines are read (M3 done, second attempt, see [EVALUATION](docs/EVALUATION.md)) |
| Photo input | None | Tested later, and ships only if it passes a gate (M8) |
| Ingredient and recipe knowledge graph with ML on top | None | Rejected on 2026-11-09 by the M3 spike rule: the spike found no new recipes ([ADR 0006](docs/decisions/0006-hybrid-graph-knowledge-base.md) says what that does and does not show). The product keeps a flat table |

Milestones are in [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md).

## Results

An audit in October 2026 tested the old headline numbers. Many of them did not hold up.
The ledger is in [docs/PROJECT_STATE.md, section 7](docs/PROJECT_STATE.md#7-published-numbers),
and the details are in [docs/TECHNICAL_AUDIT.md](docs/TECHNICAL_AUDIT.md).

| Old claim | Status |
| --- | --- |
| Learned ranker beats the overlap baseline | Retracted as a quality claim. The task leaks the answer, and a no-ML rule scores close to the model ([audit C1](docs/TECHNICAL_AUDIT.md#c1-the-recommender-headline-measures-the-query-generator-verified)) |
| Graph beats food2vec | Retracted as a headline. The 95% interval for the difference includes zero ([audit H1](docs/TECHNICAL_AUDIT.md#h1-the-flagship-graph-model-does-not-yet-beat-its-baseline-verified)) |
| 100% dietary validity | Retracted. The check cannot fail ([audit C2](docs/TECHNICAL_AUDIT.md#c2-the-dietary-filter-is-unsafe-and-its-metric-cannot-fail-verified)) |
| Nutrition coverage | Retracted. It used only the first rows of the file ([audit C3](docs/TECHNICAL_AUDIT.md#c3-nutrition-output-is-not-fit-to-show-verified)) |
| Full-corpus ranker lead, and "saturates at 10k" | Retracted ([PROJECT_STATE, section 7](docs/PROJECT_STATE.md#7-published-numbers)) |
| Parser F1 and retrieval recall | Unsupported. No log exists ([PROJECT_STATE, section 7](docs/PROJECT_STATE.md#7-published-numbers)) |
| A production recommender bundle | False. The only bundle on disk holds 1,000 recipes ([audit H4](docs/TECHNICAL_AUDIT.md#h4-the-production-bundle-does-not-exist-verified)) |

M2 starts the new evaluation. The rule baselines and their intervals are in [docs/EVALUATION.md](docs/EVALUATION.md). Each new number links to a file in [`results/`](results/).

## Quickstart

Install [uv](https://docs.astral.sh/uv/), then run these commands from the repo root:

```bash
uv sync --all-extras
uv run pytest
uv run pantrychef --help
```

The tests need all extras, because some test files import `scipy` at module level.

The `cook` and `substitute` commands need data files that are not in git. For the steps,
read [docs/PROJECT_STATE.md, section 6](docs/PROJECT_STATE.md#6-what-a-person-can-run-today)
and [docs/DATASET.md](docs/DATASET.md).

## Documentation

| Document | Purpose |
| --- | --- |
| [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) | Current state, with evidence |
| [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md) | Milestones and acceptance criteria |
| [docs/ARCHITECTURE_PROPOSAL.md](docs/ARCHITECTURE_PROPOSAL.md) | Target design |
| [ARCHITECTURE.md](ARCHITECTURE.md) | What exists today, and what is planned |
| [docs/decisions/](docs/decisions/) | Architecture decision records (ADRs) |
| [docs/TECHNICAL_AUDIT.md](docs/TECHNICAL_AUDIT.md) | Audit findings |
| [docs/DATASET.md](docs/DATASET.md), [LICENSES.md](LICENSES.md) | Data sources, hashes and licences |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Old evaluation record, with status flags |
| [ROADMAP.md](ROADMAP.md), [CONTRIBUTING.md](CONTRIBUTING.md) | Status summary and development guide |

## Licence

Code: MIT ([LICENSE](LICENSE)). Data and artifacts: [LICENSES.md](LICENSES.md).
