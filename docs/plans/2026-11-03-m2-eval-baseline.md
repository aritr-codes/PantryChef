# M2 evaluation baseline: task-level plan

Status: DRAFT for owner review, 2026-11-03. No M2 code exists yet.
Branch: `feat/m2-eval-baseline` (from `main`). Scope source: [DEVELOPMENT_PLAN.md](../DEVELOPMENT_PLAN.md) (M2).
Contract: [ARCHITECTURE_PROPOSAL.md](../ARCHITECTURE_PROPOSAL.md) sections 5 to 7.
Rules: [ADR 0005](../decisions/0005-honest-claims-and-eval-reset.md). Labels: MEASURED, ESTIMATE, HYPOTHESIS.

**Goal:** measure before changing anything. After M2, every number we publish links to a results file. The
leaderboard shows a no-ML rule and the IDF rule with paired confidence intervals. We know what the Wikibooks
pack does on a real phone.

**Architecture:** one results-file schema (JSON Schema) with a Python writer and a Node writer. A pure-Python
evaluation package builds distractor pantries, scores ranking arms on the Wikibooks pack, and computes paired
bootstrap intervals. A render script rebuilds the tables in `docs/EVALUATION.md` from `results/*.json`. A thin
Kaggle kernel runs the same rule arms on RecipeNLG at 1.27M recipes. No ML model is trained in M2.

**Tech stack:** Python 3.11 (existing, numpy is already a dependency), Node 22 and Playwright (existing), pytest.

## 0. Out of scope for M2

Training any learned ranker (M4). Graph features and ADR 0006 work (M3). Table growth and resolver changes (M3).
The 100-pantry judging set (M4; M2 pilots 20). Open Recipes statistics (M5). Any change to `answer()` or the pack.
Shipping any Kaggle output. Running the Kaggle job before you say yes.

## 1. What M2 measures, and what it must not claim

There are three kinds of metric. Each has one role, and the code enforces the role.

| Role | Metric | May select a model? | Why |
| --- | --- | --- | --- |
| `selection` | Hand-judged pantry preference (pairwise win rate, M4 uses it) | Yes | It comes from a person. It uses no model feature |
| `sanity` | Masked recovery: recall@k, MRR@k of the source recipe | **No** | The query comes from the gold recipe, so the task leaks (ADR 0005). It checks that nothing is broken |
| `product` | Makeable at k, make-now hit rate | **No** | It reads the same lines the IDF rule reads. It describes the product and does not rank models |

`results.py` holds a fixed **registry**: every metric name maps to its `role` and its `depends_on` list, and every arm name maps to its `features_used`.
Callers cannot pass their own values (review fix 5). A metric that is not in the registry cannot be written. `assert_selectable(metric, arms)` fails when
the registry role is not `selection`, or when the metric's `depends_on` shares an item with any arm's features. A unit test proves both failures, and a third test
fails if a new metric is added to the registry with an empty `depends_on` and the role `selection` without a written justification string. This turns the rule
"a metric that selects a model must not be a function of that model's features" into a check. It is a guard on honest declarations. It cannot prove the declarations are
complete, so the metric-definition review (section 9) still reads the code.

No model is selected in M2. The check exists so that M4 cannot skip it.

## 2. Decisions for the owner

Each row has my recommendation. I will use it unless you say otherwise.

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | RecipeNLG sample for the 1.27M baseline, and its hash | Use the full title-deduplicated corpus (1,274,290 recipes, the same cleaning code as before) as the **index**. Score a **fixed query set** of 20,000 recipes, chosen by `sha256(f"{seed}:{recipe_id}")` order, seed 42. Hashes recorded: sha256 of the Kaggle copy of `full_dataset.csv` (must equal `f376ee0b…ca0803` from DATASET.md), sha256 of the cleaned file, sha256 of the query-id list. Use the Kaggle-hosted RecipeNLG copy only if its hash matches, so we upload no third-party data. **We never upload RecipeNLG** (ADR 0003 allows sharing only under the same terms). If the copy is missing or the hash differs, we stop and ask you (review fix 3) |
| D2 | Two distractor samplers | (a) **uniform**: distractors drawn evenly from the non-staple ingredients. (b) **popularity**: drawn with probability proportional to document frequency. Together they bracket a careless user and a typical user. A third, **sibling** (distractors taken from a different random recipe's lines), is optional and costs one function. It is off by default because it can accidentally build a pantry for another real recipe. Distractor count: 0, 3 and 6 per pantry |
| D3 | Judging protocol | Pairwise, blind. For one pantry, show the top 5 of arm A and arm B in random order and random left/right position. You pick A, B or tie, then answer "would I cook anything here?" yes/no per list. One judge (you), so bias is limited by: hidden arm names, shuffled order, 4 of the 20 pantries repeated unmarked to measure your own consistency, and two sessions on different days. Details in section 5, Task 7 |
| D4 | The 300 gold lines | Lines come from the **Wikibooks snapshot** (not RecipeNLG: ADR 0003). 100 random lines, 100 hard-case lines (fractions, "or", parentheses, "salt and pepper", unread, multi-ingredient), 100 spread over the table's rare ingredients. Split **150 dev / 150 test**, stratified by those three groups, cut by sorted hash within each stratum so sizes are exact. The "hard" and "rare" strata use the M1 resolver to pick lines, so I report results **per stratum** and pool only the random stratum for any headline. Test labels stay unread by me until M3 acceptance. Labelling is yours: I give you a blank sheet with no resolver output, so my output cannot anchor your labels. See risk R3 |
| D5 | Where the helper lives and how CI reads it | `pantrychef/eval/results.py` (writer, validator, `assert_selectable`), schema at `results/schema.v1.json`. Node scripts write the same shape through `web/scripts/result.mjs`. CI reads `data/eval/floors.v1.json` and runs the fixture-pack evaluation in an ordinary pytest test. No new CI job is needed. If a new job is added later it uses `contents: read` and SHA-pinned actions |
| D6 | The 166 realistic inputs | They exist only inline in `docs/research/2026-10-stage1/evidence/b_parser.py` (166 pairs of input and acceptable names). I extract the inputs into `data/eval/realistic_inputs.v1.json` (committed; MIT; short phrases, no recipes). Split **83 dev / 83 test**, seeded (seed 42), sorted by hash inside each stratum and cut, stratified by a category tag (plain, plural, typo, UK/US synonym, abbreviation, multiword, with quantity). The split file stores seed, method and the sha256 of the input list. The old acceptance sets use the old RecipeNLG vocabulary and are **not** carried over. Dev expectations are re-derived against the new table in M3 |
| D7 | Real-device run | The phone must be unlocked, on USB debugging, with Chrome open. I will check Chrome's version first. If the phone is under 25% battery or in battery saver, I record it and ask you before measuring |
| D8 | Python 3.11 / `uvx kaggle` | `uvx kaggle --version` fails here with `ModuleNotFoundError: No module named 'six'`. I propose `uvx --with six kaggle` as a documented workaround, and I record the working command in the kernel README. No credentials are read |

## 3. Metric definitions (hand-computable)

Pantry `P` is a set of ingredient ids. A recipe `r` has required lines. `have(r)` and `total(r)` follow the
engine rules in ARCHITECTURE_PROPOSAL section 6 (staple-covered lines are satisfied, unread lines count as missing).

**Masked recovery (sanity).** Fixed rules (review fix 2). Staples are the pack default staples.
1. Eligible gold: a recipe with `total >= 3`. `total` counts required, non-staple-covered lines (engine rules).
2. Masked lines: `m = max(1, floor(0.25 * total + 0.5))` (round half up, so Python, Node and Kaggle agree; no `round()`).
   Choose `m` lines at random from the required, non-staple-covered **read** lines, with `random.Random(f"{seed}:{recipe_id}:{draw}")`.
   Optional, staple-covered and unread lines are never masked. If fewer than `m` such lines exist, the recipe is not eligible.
3. Pantry ids: for each **unmasked** required read line, add the **first** option id (lowest id in sort order). Adding all options would inflate the pantry.
   Add no staples. Then add `d` distractors from a sampler. A distractor is never an option id of any line of the gold recipe.
4. `draw` runs 0, 1, 2: three mask draws for each gold, so a cluster holds three pantries.
5. **Candidate set (review fix 1).** Every arm ranks the same set: all pack recipes with `have >= 1`. Arms differ only in order.
   `shipped` uses the engine's order key (missing count, then score, then fewer `total`, then id) applied to this full set. It is not a call to
   `answer()`, because `answer()` drops recipes with more than 2 missing lines and cuts each group to `limit`. A parity test shows that, for the
   recipes `answer()` returns, `shipped` gives the same order (see B3). The result also reports `visible_rate`: the share of golds that `answer()` would
   show at all (missing at most 2 and inside the group limit). That is a product number and it is not mixed into the arm comparison.
6. Metrics: `recall@k` and `MRR@k` for `k = 10`. Reciprocal rank is 0 outside the top `k`.

Hand example: `total = 6`, so `m = floor(1.5 + 0.5) = 2`; the pantry holds the first option of 4 lines plus `d` distractors; `have` for the gold is 4, missing 2.

**Makeable at k (product).** For a pantry, take the top `k` recipes in the arm's order. `makeable@k` is the share
of those that have `have == total`. `hit_rate` is 1 if any recipe in the whole list has `have == total`. Both are
means over pantries. They are product metrics: they say what a person sees. They do not choose a model.
(Note: the shipped ordering puts make-now first by design. So `makeable@k` is high for it by construction.
It matters for the flat arms. The doc says so.)

**Arms.**

| Arm | Order | `features_used` |
| --- | --- | --- |
| `random` | seeded shuffle | none |
| `overlap` (no-ML rule) | `have` descending, then fewer `total`, then id | `have`, `total` |
| `idf_flat` | the engine score (sum of `w` over satisfied lines over sqrt of sum of `w`), no grouping | `idf`, `have`, `total` |
| `shipped` | the real `answer()` order (groups by missing count, then score) | `idf`, `have`, `total`, `group` |

`overlap` is the no-ML baseline that each learned model must beat (CLAUDE.md). `idf_flat` and `shipped` together
show whether grouping changes the sanity numbers.

**Paired confidence interval.** For arms A and B, per-pantry difference `d_i = metric_A(i) - metric_B(i)`.
Pantries from the same gold recipe (3 mask draws) form a cluster. The interval is a **cluster bootstrap** over gold recipes:
10,000 resamples, seeded, percentile 95% interval of the mean of `d`. The result stores the interval and `n` clusters.
A difference "holds" only when the interval excludes 0. Tests use a tiny case where the interval is known by hand.
Every comparison is reported **per sampler** (and per distractor count). The popularity sampler draws by document frequency, which is the same quantity as
IDF. Popular distractors weigh little for `idf_flat` and fully for `overlap`, so part of the `overlap` vs `idf_flat` gap comes from the sampler. The doc says this (review fix 6).

**Splits for pantries.** Gold recipes are grouped by normalised title (lowercase, no punctuation, trailing "(variant)"-style words dropped) so variant pages stay together.
Groups are sorted by `sha256(f"{seed}:{group_key}")` and cut at 50/50, so sizes are exact (review fixes 8 and 10).
Config choices (such as `m` and `d`) are fixed here, in this plan, before any run. We report on test.
We read dev for debugging only. If a number moves after a config change, the new config gets a new results file.

## 4. File map

Create:

| Path | Purpose |
| --- | --- |
| `results/schema.v1.json` | JSON Schema for a results file |
| `pantrychef/eval/results.py` | `write_result`, `load_result`, `validate`, `assert_selectable`, git facts (commit, dirty) |
| `pantrychef/eval/metrics.py` | `recall_at_k`, `mrr_at_k`, `makeable_at_k`, `hit_rate` (pure, hand-tested) |
| `pantrychef/eval/stats.py` | `paired_cluster_bootstrap` |
| `pantrychef/eval/pantries.py` | masked-pantry builder, `uniform` and `popularity` (and `sibling`) samplers, dev/test assignment |
| `pantrychef/eval/arms.py` | `random`, `overlap`, `idf_flat`, `shipped` over a `Pack` |
| `pantrychef/eval/baseline_main.py` | CLI `python -m pantrychef.eval.baseline_main` |
| `scripts/eval_baseline.py` | thin entry point |
| `scripts/eval_tables.py` | renders the tables in `docs/EVALUATION.md` from `results/*.json`; `--check` fails if the doc is stale |
| `scripts/extract_realistic_inputs.py` | one-off extraction of the 166 inputs, plus the split |
| `scripts/make_parser_gold_sheet.py` | builds the blank 300-line sheet and the split |
| `data/eval/realistic_inputs.v1.json`, `data/eval/realistic_inputs.split.v1.json` | the 166 inputs and the split |
| `data/eval/parser_gold/` | sheet, labels and split (Wikibooks text, CC BY-SA, with `NOTICE.md`) |
| `data/eval/floors.v1.json` | CI floors for the fixture pack |
| `data/eval/judging/` | protocol, pilot pantries and answer sheet |
| `docs/JUDGING_PROTOCOL.md` | the protocol (ASD-STE style) |
| `kaggle/rule_baselines/` | `kernel.py` (thin), `kernel-metadata.json`, `README.md` |
| `web/scripts/result.mjs` | Node writer for the same schema |
| `web/scripts/latency-device.mjs` | CDP run on the phone |
| `tests/eval/test_*.py` | unit tests for each module above |
| `tests/test_results_links.py` | every `results/*.json` link in `docs/` resolves and validates |
| `results/m1_latency_*.json` | rewritten into the schema (old content kept under `raw`) |
| `results/m1_latency_device.json`, `results/m2_baseline_*.json` | new results |

Modify: `web/scripts/latency*.mjs` (use `result.mjs`), `docs/EVALUATION.md`, `docs/PROJECT_STATE.md`,
`docs/DEVELOPMENT_PLAN.md` (mark M2 status), `docs/DATASET.md`, `LICENSES.md`, `README.md` (table).
`.gitignore` needs no change: `git check-ignore` shows JSON files under `data/eval/` are not ignored (`*.csv` is, so new eval data uses JSON).

Not touched: `pantrychef/engine.py`, `web/src/`, the pack builder, `data/processed/`, `.codegraph/`,
`CODEX_HANDOFF.md`, `TestRun.md`, `scratch_codex_audit_prompt.md`, `temp_pytest/`.

## 5. Tasks

Order: Task 0 first. Then lanes run as shown. Each code task is test-first (hand-computed expected values written
before the implementation). Each task ends with `uv run pytest`, `ruff check` and `ruff format --check`.

### Task 0. Interface (me, no agents, about 1 hour)

Write `results/schema.v1.json` and the signatures of `results.py`, `metrics.py`, `stats.py`, `pantries.py`, `arms.py`
as stubs with docstrings. Agree the shape of a result:

```
{ schema: 1, label: MEASURED|ESTIMATE|HYPOTHESIS, what, command, commit, dirty, dirty_paths,
  config, seed, corpus_fingerprint, arms: [{name, features_used}],
  metrics: [{name, role, depends_on, arm, split, n, value, ci?: {lo, hi, level, method, n_clusters}}],
  comparisons: [{metric, a, b, split, diff, ci}], environment: {python, platform, ...}, raw?: {} }
```

`dirty` is true when `git status --porcelain` shows tracked changes or untracked non-ignored files, **excluding**
the result file being written and `results/` files written in the same command. `dirty_paths` lists what made it
dirty (up to 20). This fixes the M1 note where `dirty` was true only because of an unrelated delete.

### Lane A (Sonnet, worktree `m2-a`): results helper and metrics

- A1 `results.py` and `result.mjs`. **No new dependency** (review fix 4): `jsonschema` and `ajv` are not installed. The schema file is the documented contract.
  Each language has a small hand validator for the same required keys and types. A committed sample, `tests/fixtures/results/node_sample.json`, is written by
  `result.mjs` in a Vitest test (the `web` CI job has Node) and read by a pytest test (the `quality` job has no Node). Both must validate it, and a Vitest test checks that
  the sample has not drifted from what `result.mjs` writes. TDD.
- A2 `metrics.py`: `recall_at_k`, `mrr_at_k`, `makeable_at_k`, `hit_rate`. Hand-computed cases, including
  `k` larger than the list, a missing gold, ties and an empty list.
- A3 `assert_selectable` and its two failing tests (wrong role; shared dependency).
- A4 Rewrite the three M1 latency scripts to call `result.mjs`. Convert the four existing `results/m1_latency_*.json`
  files to the schema with the original body under `raw` and `label: MEASURED`. Keep the original numbers.
- A5 `tests/test_results_links.py`: every `results/*.json` link in `docs/*.md` points to an existing, valid file.

Output: a branch with commits. I review the diff and run the tests before merging.

### Lane B (Sonnet, worktree `m2-b`, starts after Task 0): samplers, arms, bootstrap

- B1 `stats.py` `paired_cluster_bootstrap`. Test: two arms with known per-cluster differences give the hand-computed
  mean. A constant difference gives a zero-width interval. Same seed gives the same interval.
- B2 `pantries.py`: masking rule, `uniform` and `popularity` samplers, dev/test assignment. Tests: a distractor is never a
  gold line; counts are exact; a fixed seed gives the same pantries; dev and test do not overlap; sampler
  frequencies match the stated distribution on a hand-made table (chi-square free: exact counts on a tiny pack).
- B3 `arms.py` over the fixture pack. Test that, on the 202 golden pantries (`tests/golden/answer_cases.json`), the `shipped` order restricted to the recipes
  `answer()` returns equals the `answer()` order. This shows `shipped` is the same order key as the product. It does not show the candidate sets match, which differ by design (section 3, rule 5).
- B4 `baseline_main.py` and `scripts/eval_baseline.py`: run all arms on a pack, write one result file.
- B5 CI floor: `tests/eval/test_floor.py` runs B4 on `tests/fixtures/pack/core.v1.json` and checks
  `data/eval/floors.v1.json`. The floors are set from the first fixture run minus a stated margin. They guard
  against regressions in the code. They are not a quality claim, and the doc says so.

Lanes A and B touch different files. B waits for Task 0 and, for `write_result`, for A1. B writes against the stub.

### Lane C (Sonnet for tooling, **you** for labels; worktree `m2-c`): gold sets and splits

- C1 `extract_realistic_inputs.py`: parse the 166 inputs from `b_parser.py` (read the file as text and use `ast.literal_eval` on
  the list; do not import it, because it loads `vocab.json`). Tag categories. Write the split with the seed.
  Test: 166 inputs, no overlap, split sizes 83/83, each category in both halves when it has two or more members, the
  file hash matches. I commit this **before any table work** (M3).
- C2 `make_parser_gold_sheet.py`: draw 300 lines from `data/raw/wikibooks/snapshot.*.jsonl.gz` using the strata
  in D4. Write a blank sheet (line id, text, source page, revision id) and the split. Test: stratum counts, no duplicate text,
  the split is stable, the sheet has no resolver columns.
- C3 A label format and a checker (`label_check.py`): each line gets `names` (free text, one per ingredient), `optional`,
  and `not_an_ingredient`. The checker rejects blanks and flags names that are not in the table as `out_of_table` (kept, not
  dropped, so M3 can score growth). You do the labelling. I do not fill labels.
- C4 `parser_gold_eval.py` (the existing `pantrychef/eval/parser_eval.py` is the circular RecipeNLG-NER scorer; I leave it and mark it historical): scores the current resolver against dev labels (exact set match, and per-line precision/recall).
  Test: hand-made 5-line gold. The first run on the dev half goes into `results/` as a baseline. Test labels are not run.

### Lane D (Sonnet, after A and B merge): Kaggle kernel (write, do not run)

- D1 `kaggle/rule_baselines/kernel.py`: installs the wheel built at the pinned commit, verifies the input hash, cleans (same
  code as `pantrychef.data`), builds the inverted index with rarest-token bucketing, runs `random`, `overlap`, `idf_flat` on the
  20,000 queries with 0/3/6 distractors under both samplers, writes `results/*.json` and a manifest of sha256 for each output.
  No network calls, no secrets. The kernel prints no recipe text.
- D2 `kernel-metadata.json` (private, internet off, CPU), `README.md` with the exact commands and the `six` workaround.
- D3 A local dry run of the **same code** on 2,000 recipes of the 50k sample only if free RAM is over 3 GB. Otherwise
  the dry run runs on the fixture pack. This checks that the kernel writes a valid results file. It is not a result.
- D4 Approval request to you (section 7). Nothing runs before your yes.

### Lane E (me, main tree, one heavy process at a time): real device

See section 8. It needs the browser and the phone, so it runs when no other heavy process runs.

### Task 7. Judging protocol and 20-pantry pilot (Opus designs; Sonnet builds the sheet)

- `docs/JUDGING_PROTOCOL.md`: the rubric ("would I cook this tonight with these items plus a trip for the missing ones listed?"),
  the A/B/tie rule, the blinding steps, the repeat check, and the stop rules.
- `scripts/judging_sheet.py`: draws 20 pantries from the **test** gold recipes (masking as in section 3, `d = 3` popularity
  distractors, so they look like a person's pantry), builds blinded A/B pairs for `shipped` vs `overlap`, repeats 4 pantries,
  shuffles, writes a sheet and a private key (arm per side). The key is in a separate file that you do not open until you finish.
- The pilot must show (all before the 100-pantry set in M4):
  1. **Self-consistency:** you give the same answer on at least 3 of the 4 repeats.
  2. **Discrimination:** not more than 60% of pairs are ties.
  3. **Cost:** median time per pantry under 90 seconds. If higher, M4 uses fewer pantries or a shorter list.
  4. **Power:** from the observed non-tie pairs, an estimate (labelled ESTIMATE) of how many pantries M4 needs for a 95% interval
     of width 0.2 on the win rate.
- If a check fails, I fix the protocol (list length, rubric wording) and pilot 10 more pantries. I do not proceed to M4 on a failed pilot.
- Bias limits for one judge: blind arms, random side, repeats, two sessions on different days, and a written rubric before you see any pair.
  A single judge cannot remove taste bias. The doc says so. M4 may add one friend as a second judge if you can find one (HYPOTHESIS that it helps).

### Task 9. Docs (Sonnet, last; I review)

`docs/EVALUATION.md`: add "M2 leaderboard" with auto-generated tables between markers, the old recovery results as a "sanity check" table
with the rule beside them (the audit's 0.975 is a different rule, "subset, then closeness to 30% missing", from `01_recommender.md`; it is linked and named as such, not as `overlap`; the Kaggle numbers when they exist), and the reproduction command
for each table. `docs/PROJECT_STATE.md` (section 11), `docs/DATASET.md` (new files and hashes), `LICENSES.md` (parser gold set under
CC BY-SA 4.0 with a `NOTICE.md`; realistic inputs MIT), `README.md` table, `docs/DEVELOPMENT_PLAN.md` (M2 status). Mermaid: one diagram of the
eval flow, marked with what is planned.

## 6. Kaggle

Facts (checked): `uvx kaggle --version` fails here with a missing `six` module. `~/.kaggle/credentials.json` is not read. Not yet checked: the Kaggle
quota, and whether a Kaggle-hosted RecipeNLG copy has the same sha256 as ours. The kernel verifies the hash and stops on a mismatch. The earlier
full clean took 31 to 42 minutes on the laptop. Kaggle is the place for the 1.27M run. I will state the expected runtime from a measured
2,000-recipe run before I ask.

Flow: `uv build` at a tagged commit, private Kaggle Dataset holding the wheel only, `kaggle kernels push`,
`kaggle kernels output`, then `sha256sum` against the manifest the kernel wrote. The kernel has no token in it, and it runs with internet off.
The wheel installs with `--no-deps`. D1 checks first that the Kaggle image already has numpy and the other imports the kernel needs (review fix 13). If not, the kernel imports from the wheel's
source folder and avoids the missing package, or we stop and ask.

## 7. Approval request that I will send you before any run (draft)

- **Purpose:** replace the retracted "7.7x" full-corpus claim with rule baselines on RecipeNLG at 1.27M recipes. Research only. Nothing ships.
- **Resources:** CPU kernel, 16 GB RAM class, about N hours (N from the measured small run). No GPU. Internet off.
- **Inputs:** RecipeNLG `full_dataset.csv` (sha256 must be `f376ee0b…`), wheel at commit `<sha>`, query-id list (sha256 recorded).
- **Outputs:** `results/m2_rule_baselines_recipenlg.json` and a manifest of sha256 values. Only aggregate numbers. No recipe text.
- **Failure plan:** hash mismatch stops the run. Out-of-memory or timeout: halve the query set and record the failure in the result. I do not retry in a loop.
- **Sync:** I pull outputs, check hashes, and commit the result file only. You decide whether any number appears in a public doc.

## 8. Real device (Lane E)

1. Load the adb tools with ToolSearch. `get-devices`. Use `C:\Program Files\platform-tools\adb.exe` (version 1.0.41) for `forward`, because the MCP
   tools do not list a forward command (I will check this first).
2. Record: model, Android version, Chrome version, battery level, battery saver state, thermal status (`dumpsys thermalservice`, `dumpsys battery`).
3. `adb forward tcp:9222 localabstract:chrome_devtools_remote`. Playwright `chromium.connectOverCDP`. No CPU throttle. Reuse the scenario and the seeded
   list in `latency-live.mjs`: sizes 3, 5, 8, 12; at least 15 runs per size; drop 2 warm-ups; cache off; time the click on "See recipes" to the painted results.
4. Write `results/m1_latency_device.json` through `result.mjs`. Label MEASURED. Update PROJECT_STATE section 10 and compare with 510 to 630 ms
   from headless Chromium. If the phone is faster, say the headless number overstated it. If the phone is slow, take a Chrome performance trace over CDP,
   write down the cause, and propose a fix. I do not change the app before you see the proposal. An app fix is its own commit and needs the Playwright suite to pass.
5. Manual pass: tap targets (44 px minimum, measured with `getBoundingClientRect` over CDP), keyboard (an on-screen keyboard and a Bluetooth keyboard if one exists),
   the suggestion list, and focus after each screen change. Report findings. Edit the app only for a small, tested fix.
6. Risks: the phone can throttle itself. I record thermal state before and after and rerun if it moved. The headless runs were noisy because of RAM pressure on the laptop.
   The laptop does only the connection here, so I close other heavy processes first.

## 9. Independent review points (Opus Review Agent, did not write the work)

1. This plan, before you see it (done as step 0 below).
2. After Task 0 and Lane B: **metric definitions and leakage** (section 3). Re-review if any metric or contract changes.
3. After Lane C: the splits (leakage between dev and test, and between M1's table and the 166 inputs).
4. After Lane D: the kernel (secrets, network, licence boundary).
5. Whole branch, before I report M2 complete. Also run `/code-review` and `/security-review`.

Required Fixes are resolved, or I state the disagreement.

## 10. Acceptance mapping

| Acceptance | Evidence |
| --- | --- |
| One documented command rebuilds each table in `docs/EVALUATION.md` | `scripts/eval_tables.py --check` in a pytest test. Each table has its command under it |
| Old recovery results appear only as a sanity check, with the rule beside them | EVALUATION.md "sanity check" table, test that the string "flagship" and "7.7" appear only in the historical block |
| The metric that picks a ranker is not a function of its own features | `assert_selectable` and its two failing tests |
| Kaggle flow runs at a pinned commit and returns hashed results | Kernel written and reviewed in M2. Run after your approval. Not claimed before |
| Metric unit tests with hand-computed values | `tests/eval/test_metrics.py`, `test_stats.py` |
| Small-fixture floor as a CI gate | `tests/eval/test_floor.py` in the existing `quality` job |
| Leaderboard has no-ML rule and IDF rule with paired CIs | `results/m2_baseline_wikibooks.json` and the rendered table |
| 166 inputs split before table work | `data/eval/realistic_inputs.split.v1.json`, committed first |
| 300-line gold, dev/test | Sheet, split and checker are mine. **Labels are yours** (blocks the first parser score) |
| Judging protocol piloted on 20 pantries | Section 5, Task 7. **The pilot needs your time** |
| Real device measured | `results/m1_latency_device.json` |

## 11. Risks

- **R1. Leaky sanity task.** The pantry comes from the gold recipe, so recall is high for any sane rule. I report it as a sanity check, put distractors
  in, and never use it to choose between arms. The arm gap with its interval is the only comparison I show.
- **R2. Self-referential arms.** `shipped` uses the same IDF the sanity task is built on. That is why it cannot select a model. `assert_selectable` enforces this.
- **R3. Labelling load.** 300 lines is about 2 hours of your time, plus the 20-pantry pilot (about 30 minutes, two sessions). If you cannot do it soon, M2 closes
  without those two items and I list them as open. I will not label them myself, because the gold would then be a function of my own parser reading.
- **R4. The M1 table has seen the 166 inputs.** `data/ingredients/ingredients.csv` contains synonyms such as `evoo`, and the inputs were in the audit. So the
  dev/test split is not clean for the table. I label this in the split file. The test half stays a fair check of the **M3 growth**, not of M1. HYPOTHESIS: the
  M1 table was tuned toward these inputs. I can measure this: count how many test inputs already resolve exactly.
- **R5. Memory.** About 1 GB free now. The Wikibooks pack evaluation is small (3,712 recipes). The Kaggle dry run on 50k needs a free-RAM check. I do not load `recipes.jsonl`.
- **R6. Few recipes.** The pack has 3,712 recipes. Intervals will be wide for rare strata. I show `n` beside every interval.
- **R7. Wikibooks lines are CC BY-SA.** The gold sheet is a committed copy of Wikibooks text. It needs `NOTICE.md` with page, revision and licence, and a
  `LICENSES.md` entry. Without that, I do not commit it.
- **R8. Phone variance.** One phone is one device. I label the result as one device, and I do not extend it to "phones".
