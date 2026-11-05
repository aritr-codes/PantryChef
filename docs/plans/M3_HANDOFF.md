# M3 handoff: ingredient foundation

Written 2026-11-05 at the end of M2. M2 is merged (PR #9). Read this file first in the new session.
Then read, in order: `CLAUDE.md`, `docs/PROJECT_STATE.md` (sections 10 and 11), `docs/DEVELOPMENT_PLAN.md`
(M3 and M4), `docs/EVALUATION.md`, `docs/decisions/0006-hybrid-graph-knowledge-base.md`.

## 1. Start state (MEASURED unless marked)

- `main` holds M0, M1 (live app, 3,712-recipe Wikibooks pack) and M2 (evaluation baseline).
- Ingredient table: `data/ingredients/ingredients.csv`, 337 rows. Code: `pantrychef/ingredients/`
  (`parser.py`, `resolve.py`, `table.py`, `units.py`, `normalize.py`). The resolver is deliberately small ("M3 owns the full resolver").
- Browser engine: `web/src/engine.ts`, with Vitest parity tests against the Python engine (`pantrychef/pack/`, `tests/test_engine.py`, `tests/golden/`).
- Parser gold set: `data/eval/parser_gold/` (150 dev, 150 test). Labels are model-written. The owner checked 30 lines (28 right, 2 fixed in dev).
  **Dev baseline to beat:** precision 0.891, recall 0.809, F1 0.848 (`results/m2_parser_gold_dev.json`).
  **The test half is unscored.** M3 acceptance scores it once. Never tune on it.
- Realistic inputs: `data/eval/realistic_inputs.split.v1.json` (dev/test split). Combined baseline is 0.82 to 0.86 (plan).
- Results helper and registry: `pantrychef/eval/results.py`. Rule baselines: `pantrychef/eval/rule_baselines_main.py`.
- Kaggle rule baselines on RecipeNLG: `results/m2_rule_baselines_recipenlg.json`. See `kaggle/rule_baselines/README.md` for the flow.

## 2. What M3 must deliver (plan, `docs/DEVELOPMENT_PLAN.md`)

1. Rule-based collapse of size, container and preparation words. Fix the singulariser.
2. Grow the table from 337 rows in measured steps. About 1,700 rows reach 90% of mentions. 60% full-recipe coverage needs more than 2,000 rows.
3. Synonyms and UK/US names. Epicure vocabulary only if licence and provenance are both clear.
4. Resolver with exact, synonym and fuzzy steps, plus a matching browser version (parity tests).
5. Sets of ids per line, optional and unread flags (partly in M1 already).
6. Decide the bare "pepper" rule (510 lines; M1 rule is provisional).
7. Rebuild the pack with the new table and measure coverage.
8. Graph spike for ADR 0006. Then accept or reject the ADR. Allow `is_a` and `form_of` columns in the table.

**Acceptance (stop and report if a target fails; never lower it silently):**
- At least 90% of Wikibooks mentions resolve correctly, on a hand-checked test sample.
- At least 60% of recipes have every required line read, and the pack keeps at least 2,500 recipes. Unread lines show as "check this line".
- At least 90% of held-out realistic inputs resolve correctly.

Open question for the owner: the "hand-checked test sample" needs a human. The parser gold labels are model-written. Ask the owner how many lines they will check before you claim the 90% target.

## 3. Architecture review first (important correction)

The brief asked to review "the existing API service". **There is no API service.** M0 deleted the Docker placeholders, the `serving` stub and `make serve`
(PROJECT_STATE section 2). The architecture is a static app with a TypeScript engine in the browser (ADR 0004). Python builds artifacts before release.
Review these instead, before you design anything:

- The artifact pipeline: `scripts/build_pack.py`, `pantrychef/pack/` (`build.py`, `guard.py`, `allowlist.py`), the manifest with hash and licence per file.
- The Python/TS parity pattern: golden cases in `tests/golden/`, `scripts/make_golden.py`, Vitest in `web/`. Any resolver change needs both sides and a golden update.
- The results flow: `pantrychef/eval/results.py` (schema v1, registry, dirty flag, `assert_selectable`). Every number you publish needs a results file.
- The Kaggle flow for anything heavy (thin kernel, pinned wheel, hashed output).
- Reuse these patterns. Do not add a server. Do not add a dependency without a reason in an ADR.
- Make the table and resolver extensible: versioned table files, columns for `is_a` and `form_of`, no hard-coded ids in code.

Record the review as a short section in the M3 plan before coding.

## 4. How to work (owner's instructions)

**Process.** Use `superpowers:brainstorming`, then `superpowers:writing-plans` (plan at `docs/plans/<date>-m3-ingredient-foundation.md`, same shape as the M1 and M2 plans).
The owner approves the plan before you build. Then use `superpowers:subagent-driven-development`.

**Skills.** Use every relevant one. At least: `superpowers:test-driven-development` for resolver and parser code, `superpowers:dispatching-parallel-agents`,
`superpowers:using-git-worktrees`, `superpowers:systematic-debugging` for failures, `superpowers:verification-before-completion` before any claim,
`superpowers:requesting-code-review` and `superpowers:finishing-a-development-branch` at the end.

**Models** (project table in `CLAUDE.md`). Switch by task:
- Haiku: file discovery, lookups, simple checks.
- Sonnet: most implementation, tests, docs, table-growth work, ordinary research.
- Opus: architecture, hard debugging, the ADR 0006 spike design, independent review, conflict resolution.
- Parser-gold style labelling or adjudication: one Sonnet and one Opus working alone, then reconcile (used in M2). Say in the docs that the labels are model-written.

**Subagents and worktrees.**
- One scope per agent. Give it the files to read and the required output. Treat its report as a claim until you check the files.
- Do not send two agents to the same question. Research agents do not edit shared files.
- Code changes go in isolated git worktrees (`isolation: "worktree"`). Merge in order. Run the full suite after each merge.
- Parallel lanes that fit M3 (independent): (A) collapse words plus singulariser, (B) table growth data and synonyms, (C) resolver Python plus TS parity (depends on A's interface), (D) ADR 0006 spike (read-only research first), (E) coverage measurement script and results files.
- Lanes A and B touch the ingredient table or parser: run them in sequence or define the file ownership first. `pantrychef/ingredients/` changes ripple everywhere.
- CodeGraph exists. For broad questions, spawn an Explore agent and tell it to use `codegraph_explore` first.

**Review.** Before work is final, an independent agent (Opus) tries to falsify it against real files and test output. Verdict: GO, GO WITH FIXES or NO-GO. Resolve each Required Fix or state the disagreement. Re-review any change to a metric or contract.

## 5. Rules that bind M3 (from `CLAUDE.md` and the ADRs)

- Stage by explicit path. Never `git add .`. Do not commit `.claude/`, `.codegraph/`, `CODEX_HANDOFF.md`, `TestRun.md`, `scratch_codex_audit_prompt.md`, `temp_pytest/`.
- Feature branch from the current `main`. Small Conventional Commits. Commit, push, merge only when the owner asks. No force-push. Commit messages end with `Co-Authored-By: Claude <model> <noreply@anthropic.com>` as the session reminder gives it.
- ADR 0003: no RecipeNLG, Recipe1M, GISMo or Open Recipes text ships. Add no RecipeNLG quotes to the repo.
- ADR 0005: do not quote old recovery metrics as quality. A metric that selects a model must not be a function of that model's features. Never tune on the set you report on (test gold, test realistic inputs). Do not change a metric and a model in the same step. Add a no-ML baseline for each learned model. Use paired CIs.
- ADR 0006 is Proposed. Run the spike to decide it. Build graph features only as the spike, and write the accept or reject decision as an ADR update.
- A results file written on a dirty tree must be rewritten after you commit.
- Laptop: about 1 GB free RAM. Never load `data/processed/recipes.jsonl` (610 MB). Never run a full-corpus job locally. Use Kaggle for that, with owner approval stating purpose, resources and outputs first. Never read `~/.kaggle/credentials.json`. No token in any kernel, notebook, log or frontend.
- Kaggle CLI: `uvx --with six --with python-slugify kaggle ...`. Dataset upload on Windows needs `dist/.gitignore` removed and `mkdir -p "$TEMP/.kaggle-uploads/dist"`.
- Windows: run `git` and `uv` from the repo root. Files may use CRLF; CI uses LF. Use the scratchpad dir for temp files.
- Docs: ASD-STE100 style. Label results MEASURED, ESTIMATE or HYPOTHESIS. Update docs in the same change as behaviour. Mermaid diagrams must match the code. Do not claim a feature works without code and tests.
- Any new CI job: read-only permissions, actions pinned by SHA.
- Verify runtimes at the target scale. Do not background multi-hour jobs on the laptop.

## 6. Checks to run

```bash
uv sync --all-extras
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
cd web && npm run typecheck && npm test      # and the Playwright smoke test where the plan says
```

## 7. Deferred and open (not M3 scope unless the owner says)

- App issues from the phone probe (`results/m2_device_ui_probe.json`): focus stays on the body after a recipe opens; source and licence links on the recipe page are small tap targets. The owner deferred these: "its own feature".
- Human judging pass: belongs to M4, on the post-M3 pack (100 pantries, 60 dev / 40 test). Protocol in `docs/JUDGING_PROTOCOL.md`.
- Adjudication inconsistencies in `data/eval/parser_gold/adjudication.v1.json` (Observation from the M2 review).
- The UI probe records the repo HEAD commit, not the deployed bundle's build.
- Kaggle kernel rerun policy: ask the owner before another run.

## 8. First steps in the new session

1. `git status`, `git checkout main`, `git pull --ff-only`, then `git checkout -b feat/m3-ingredient-foundation`.
2. Read the files listed at the top. Run the checks in section 6 to confirm a green start.
3. Commit this file on the new branch (it is untracked now).
4. Write the architecture review (section 3), then brainstorm, then the plan. Ask the owner to approve the plan.
5. Then dispatch the lanes in section 4.
