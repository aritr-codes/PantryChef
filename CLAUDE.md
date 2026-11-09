# PantryChef engineering handbook

## Product

A person lists the ingredients they have. PantryChef shows what they can cook now and
the one item that unlocks more. It also suggests swaps and explains its results. It
uses conventional ML, information retrieval and deterministic logic. It uses no LLM for
core features ([ADR 0002](docs/decisions/0002-no-llm-substitution.md)).

Read these first: [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md),
[docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md),
[docs/ARCHITECTURE_PROPOSAL.md](docs/ARCHITECTURE_PROPOSAL.md).
`CODEX_HANDOFF.md` is historical and partly stale.

## Architecture

Static app on GitHub Pages with a TypeScript engine in the browser. Python builds the
artifacts before release ([ADR 0004](docs/decisions/0004-static-first-browser-engine.md)).

- Display corpus: Wikibooks Cookbook, CC BY-SA 4.0.
- Statistics corpus: Open Recipes, CC BY 3.0. Only derived statistics ship.
- RecipeNLG and GISMo data: research only. They never ship
  ([ADR 0003](docs/decisions/0003-licence-clean-recipe-corpus.md)).
- Rejected on 2026-11-09 by the M3 spike rule (no new recipes): a graph knowledge base with ML on top
  ([ADR 0006](docs/decisions/0006-hybrid-graph-knowledge-base.md)). The ADR says what this does and does not
  show. The table keeps its `is_a` and `form_of` columns as data. A new spike needs new pantries.

## Module boundaries

| Path | Purpose |
| --- | --- |
| `pantrychef/ingredients/` | Parsing and normalisation. Changes ripple everywhere |
| `pantrychef/retrieval/`, `recommender/` | Research code from the RecipeNLG phases |
| `pantrychef/substitution/` | Mined swaps. Artifact boundary is the bundle |
| `pantrychef/dietary/`, `nutrition/` | Deterministic logic. Nutrition does not ship yet |
| `pantrychef/eval/` | Evaluation harnesses |
| `scripts/` | Thin entry points |
| `docs/decisions/` | ADRs. Add one for each lasting decision |

Planned paths are in the architecture proposal. Check that a path exists before you
rely on it.

## Environment

The laptop has 16 GB RAM with about 1 GB free, and an MX150 GPU. It is for development
and small tests. Check free RAM before you load `data/processed/recipes.jsonl` (610 MB).
Never run a full-corpus job here.

Windows note: run `git` and `uv` from the repo root. Files in the working copy may use
CRLF. CI uses LF.

## Kaggle

Use Kaggle for full-corpus research, large training and vision tests.

```bash
uvx kaggle --version
uvx kaggle kernels list --mine --page-size 5
```

- Core logic stays in `pantrychef/`. Kernels are thin scripts at a pinned commit.
- Before a long job, state its purpose, resources and outputs, and get approval.
- Never put a token in a kernel, a notebook, a log or the frontend.

## Commands

```bash
uv sync --all-extras                  # install
uv run pytest                         # tests
uv run ruff check .                   # lint
uv run ruff format --check .          # format
uv run pantrychef --help              # CLI
```

## Evaluation and reproducibility

- Old recovery metrics do not measure recommendation quality. Do not quote them as
  quality ([ADR 0005](docs/decisions/0005-honest-claims-and-eval-reset.md)).
- Every published number links to a results file with commit, dirty flag, config,
  corpus fingerprint, seed, metrics and command.
- Add a no-ML rule as a baseline for each learned model.
- Report paired confidence intervals when comparing arms.
- A metric that selects a model must not be a function of that model's features.
- Never tune on the set you report on.
- Do not change a metric and a model in the same step.

## Documentation

- Use ASD-STE100-inspired writing: short sentences, common words, one instruction per
  sentence, active voice and consistent terms. Define terms and acronyms on first use.
- Use Mermaid when a diagram explains a flow, a state or a boundary better than prose.
  Every diagram must match the code. Mark planned parts.
- Label results as MEASURED, ESTIMATE or HYPOTHESIS.
- Do not claim that a feature works unless code and tests support the claim.
- Update docs in the same change as the behaviour.

## Models and agents

| Model | Use for |
| --- | --- |
| Haiku | File discovery, simple lookups and checks |
| Sonnet | Most implementation, tests, documentation and ordinary research |
| Opus | Architecture, hard debugging, independent review and conflict resolution |

- Give each agent one scope, the files to read and the required output.
- Ask for evidence. Treat agent reports as claims until checked.
- Do not send two agents to the same question.
- Research agents do not edit shared files. Use isolated worktrees for code changes.
- Run independent tasks in parallel. Run dependent tasks in order.
- CodeGraph exists. Spawn an Explore agent for broad questions, and tell it to use
  `codegraph_explore` first.

## Code review

Before work is final, an agent that did not write it attempts to falsify it. It checks
real files and test output, and returns Required Fix, Recommended Improvement or
Observation, with a verdict of GO, GO WITH FIXES or NO-GO. The implementer resolves each
Required Fix or states the disagreement.

## Git

- Inspect `git status` and the branch before work. Preserve existing changes.
- Use a feature branch for substantial changes. Make small, logical commits with
  Conventional Commit messages.
- Commit, push, merge or publish only when the owner asks.
- Do not force-push or rewrite history.

## Deployment constraints

- GitHub Pages only for the first release: no server, no secrets, no analytics.
- Render all recipe text as text, never as HTML.
- Keep each shipped file listed in a manifest with its hash and licence.
- Show the source and licence on each recipe.

## Never

- Never ship RecipeNLG, Recipe1M or GISMo data, or Open Recipes text or images.
- Never use Ultralytics YOLO or YOLO-World weights in the MIT project.
- Never present a dietary result as allergen or medical advice.
- Never show nutrition before it passes validation.
- Never fabricate a result, or claim success without evidence.
- Never expose credentials or read `~/.kaggle/credentials.json`.
- Never delete data or models without checking what depends on them.
