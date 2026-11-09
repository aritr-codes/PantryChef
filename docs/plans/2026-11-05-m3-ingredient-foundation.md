# M3 ingredient foundation: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan
> task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: DRAFT for owner review, 2026-11-05 (revision 2, after the independent review). No M3 code exists yet.
Branch: `feat/m3-ingredient-foundation` (from `main` at 2896079). Scope source: [DEVELOPMENT_PLAN.md](../DEVELOPMENT_PLAN.md) (M3).
Handoff: [M3_HANDOFF.md](M3_HANDOFF.md). Rules: ADR [0003](../decisions/0003-licence-clean-recipe-corpus.md),
[0004](../decisions/0004-static-first-browser-engine.md), [0005](../decisions/0005-honest-claims-and-eval-reset.md),
[0006](../decisions/0006-hybrid-graph-knowledge-base.md). Labels: MEASURED, ESTIMATE, HYPOTHESIS.

**Goal:** one trusted ingredient table. After M3, at least 90% of held-out Wikibooks mentions and 90% of held-out
typed inputs resolve correctly, at least 60% of pack recipes have every required line read, and ADR 0006 is
accepted or rejected on evidence.

**Architecture:** the table becomes a versioned CSV with `is_a` and `form_of` columns, plus a versioned word file
for units and for size, container and preparation words. Python resolves recipe lines at build time (the boundary
does not change). A new typed-name resolver (exact, split, contained, fuzzy) exists in Python and TypeScript, and
golden cases hold the two together. Evaluation sets are frozen and labelled before any table growth. The table grows
in measured rounds.

**Tech stack:** Python 3.11, TypeScript, Vitest, Playwright, pytest. No new dependency.

## 0. Out of scope for M3

Ranking changes and the judged set (M4). Swaps (M5). The deferred UI items in handoff section 7. Any Kaggle run.
Deploying the new pack (D7). Changes to `normalize.canonicalize`, which the research code and the RecipeNLG
artifacts use. Shipping any graph traversal: the spike runs offline in Python only.

## 1. Architecture review (handoff section 3)

MEASURED by reading the code at bc833f1. The independent review confirmed the first two rows.

| Area | Finding | Consequence for M3 |
| --- | --- | --- |
| Line resolution | `pantrychef/pack/build.py` calls `resolve_lines` at build time. The pack stores ids per line. The browser never reads a recipe line | The line resolver stays Python only. It needs no TypeScript port |
| Typed names | `Engine.resolve` (TS) and `resolve_names` (Python) do one exact key lookup. `suggest` does prefix and word-prefix search. `PantryScreen.tsx` adds only `ids[0]` | The browser part of the resolver is the typed-name resolver. Parity covers this path, `tokens` and quantity/unit parsing. The screen must add every id |
| Tokens | `table.tokens` = `fold` + `canonicalize`. `web/src/normalize.ts` ports it. Golden token cases hold the two together | The singulariser fix goes into `tokens` on both sides. `canonicalize` does not change, so the research code and the RecipeNLG vocab keep their meaning |
| Word lists in code | `_PREP` in `resolve.py`, `UNITS` in `units.py`, ids `"salt"` and `"black_pepper"` in `resolve.py` | Move these to `data/ingredients/words.v1.json`. The pack ships it, so both engines read one list |
| Artifact pipeline | Allow-list with pinned hashes, input guard, manifest with hash and licence per file. `test_pack.py` builds the real pack from the pinned table | Each table change needs `build_pack.py --pin`. The word file becomes an allow-listed input |
| Pack naming | `engine.ts`, `engine.py load_pack`, the fixture pack, `parity.test.ts`, `make_golden.py`, `e2e/smoke.spec.ts`, `public-e2e/` and `web/pack-hashes.json` all name `v1`. `pages.yml` downloads release `pack-v1` | Pack `v2` changes all of these in one task (Task 7). Release and deploy are owner steps (D7) |
| Results flow | `results.py` has a fixed registry. `parser_precision` (role `sanity`) already exists. A test checks every results file | Register each new metric before its first use. Reuse `parser_precision` |
| Eval sets | Parser gold test half (150 lines) is unscored. 100 of its lines are in the `hard` and `rare` strata, which the M1 resolver picked. The realistic inputs have a split but no labels for the new table | Gate on random lines only (D2). Label and freeze before growth (Task 1) |
| Gold-to-id mapping | `parser_gold.to_ids` maps gold names to ids through the table under test. A wrong merge maps gold and prediction to the same id and scores as correct | At acceptance, map gold names to ids blind to predictions (D9) |
| Leakage | Growth mines phrases from the same snapshot that holds the gold lines | Mining excludes every frozen test line, hashed in the same form as the sheet's dedup (`casefold().strip()`) |

No server, no new dependency and no hard-coded ingredient id in code are needed.

## 2. Decisions

Each owner row has my recommendation. I use it unless you say otherwise. Rows marked "my call" settle a detail
that does not change what gets built. You can still overrule them.

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | Wikibooks sample (agreed 2026-11-05) | 150 test lines plus fresh random lines (count: D2). A fresh Opus 5.5 labels all of them blind. On the 150 test lines its labels are compared with the M2 labels (`labels.test.v1.json`, already two-model). Sonnet also labels the fresh lines blind. The owner settles every disagreement and checks 30 random agreed lines. Results go to new files (`labels.test.v2.json`, `labels.extra.v1.json`, `adjudication.m3.v1.json`). No v1 file is overwritten. If the owner finds more than 2 errors in the 30 agreed lines, stop and report. Report as "model-labelled, owner-adjudicated" |
| D2 | **Owner: which lines carry the 90% gate** | M2 decided that only the `random` stratum may give a headline, because the M1 resolver picked the `hard` and `rare` lines. I recommend: gate on random lines only, and raise the fresh draw from 50 to 100 lines. The gate then uses 150 random lines (50 test plus 100 fresh, about ±5 points at 90%). Report `hard` and `rare` separately. Your load rises by about 10 lines |
| D3 | What "resolves correctly" means | Per gold group: correct when some predicted group is a non-empty subset of it (`mention_accuracy`). Gate on `mention_accuracy >= 0.90` and `parser_precision >= 0.90`. The second guards against a greedy resolver that hides wrong reads. Headings are excluded |
| D4 | Realistic-input labels | Sonnet and Opus each label all 166 inputs blind, as ingredient names, with the parser gold guide. The owner settles disagreements (ESTIMATE: 10 to 20). The test entries stay unread by the implementer. At acceptance, score the M1 and M3 resolvers on test once, as a paired comparison |
| D5 | Bare "pepper" in recipe lines | Opus labels 80 bare-pepper lines (no frozen line) blind: black pepper, other, unclear. Adopt "always black pepper" only if at least 75 of 80 are black pepper (Wilson 95% lower bound about 0.86). Otherwise keep the M1 rule, and other bare "pepper" lines stay "check this line". This rests on one model labeller. You may override |
| D6 | Typed "pepper" in the pantry (my call) | Stays as today: not a key, so it shows "Not recognised" with suggestions. The person picks the pepper they hold. A pantry is a claim about what the person has, so we do not guess |
| D7 | New pack (my call on names) | Pack `v2`: new file names (`core.v2.json.gz`, ...), format 2, release tag `pack-v2`. Built and measured locally. Upload and deploy only when you say so |
| D8 | Fuzzy typed names (my call) | Damerau-Levenshtein distance over the whole key string, tokens joined by one space. Accept a unique best at distance 1 (key of 4 to 7 letters) or 2 (8 or more). Only when the exact, split and contained steps miss. The pantry chip shows the table name, so the person sees what was read |
| D9 | **Owner: gold-to-id mapping at acceptance** | Before scoring, a fresh Opus maps every gold name in the frozen sets to a v2 table id or `none`. It sees the gold names and the table only, never a prediction. The owner checks every mapping that differs from the plain table-key lookup (ESTIMATE: 10 to 30). Both arms (M1 and M3) score against this one map. v2 never removes or renames a v1 id, so M1 ids stay valid |
| D10 | Epicure vocabulary | A research agent checks the licence and the provenance. If either is unclear, we do not use it. No data is copied before you agree |
| D11 | ADR 0006 spike | Before the freeze, you confirm or change the ADR thresholds: at least two edge types used, a 95% interval of (correct minus wrong new recipes per pantry) above zero, and at least 90% correct for "make now" and for "one away" each. You are the rater. The sample is capped at 100 new recipes plus 100 decoys (ESTIMATE: about 2 hours). If no person can rate, the ADR stays Proposed |

## 3. Metric definitions

All counts are hand-computable from the label files.

- **`mention_accuracy`**: gold groups with a correct predicted group / gold groups. A predicted group is correct when
  it is non-empty and its ids are a subset of the gold group's ids. Gold ids come from the D9 map at acceptance, and
  from the table-key lookup on dev (dev is for development only).
- **`parser_precision`**: as in M2, unchanged.
- **`input_accuracy`**: an input is correct when every gold group has a predicted id in it and every predicted id is
  in some gold group. An unknown input is wrong.
- **`recipes_fully_read`**: one function, `pack.build.coverage(recipes, table) -> dict`, used by Tasks 4, 5 and 7. It uses the
  pack rules: a recipe counts only if the pack keeps it (at least one required line that the default staples do not
  cover). Numerator: kept recipes with every required line read. In-sample by design: it measures cost, not quality.
- **`agreed_error_rate`**: owner-marked errors among 30 agreed lines / 30.

Rules: Task 1 adds the metrics and scores the **M1** resolver on dev before any resolver change. A metric and a model
never change in the same task. `mention_accuracy` and `input_accuracy` get role `product` with a written reason: they
gate table rounds (a stopping rule), and they never select between models.

## 4. File map

| File | Task | Purpose |
| --- | --- | --- |
| `data/eval/parser_gold/extra.v1.json` | 1 | 100 fresh random lines, seed 43, from snapshot lines not in `sheet.v1.json` |
| `data/eval/parser_gold/labels.test.v2.json`, `labels.extra.v1.json`, `adjudication.m3.v1.json` | 1 | Labels after owner adjudication |
| `data/eval/realistic_inputs.labels.v1.json` | 1 | Gold names per input |
| `data/eval/m3_frozen_lines.v1.json` | 1 | sha256 of `casefold().strip()` of each test and extra line |
| `pantrychef/eval/parser_gold.py`, `pantrychef/eval/realistic.py`, `scripts/realistic_inputs.py` | 1 | Metrics and scoring |
| `pantrychef/eval/stats.py` | 1 | Add `wilson(k, n)` and `mcnemar_exact(b, c)` |
| `data/ingredients/ingredients.v2.csv` | 2, 5 | Copy of `ingredients.csv` plus `is_a`, `form_of`. The v1 file stays as the M1 reference |
| `data/ingredients/words.v1.json` | 2, 3, 6 | `units`, `size`, `container`, `prep`, `staple_cue` (`["salt"]`), `bare_pepper` |
| `pantrychef/ingredients/table.py`, `resolve.py`, `units.py` | 2 | Singulariser, columns, edges, word file |
| `pantrychef/ingredients/names.py`, `web/src/names.ts`, `web/src/units.ts` | 3 | Typed-name resolver and units port |
| `web/src/normalize.ts`, `engine.ts`, `types.ts`, `PantryScreen.tsx` | 2, 3 | TS ports and the screen |
| `scripts/ingredient_coverage.py` | 4 | Extended to write one growth row. No new script |
| `pantrychef/pack/build.py` and every `v1` pack path (section 1) | 7 | Pack `v2` |
| `pantrychef/eval/graph_spike.py`, `scripts/graph_spike.py` | 8 | Offline spike |
| `scripts/m3_acceptance.py` | 9 | The one acceptance run |
| `results/m3_*.json` | all | One file per number |

## 5. Global constraints

- Stage by explicit path. Never `git add .`. Never commit `.claude/`, `.codegraph/`, `CODEX_HANDOFF.md`, `TestRun.md`,
  `scratch_codex_audit_prompt.md`, `temp_pytest/`.
- No RecipeNLG, Recipe1M, GISMo or Open Recipes text in the repo or in a labeller's prompt.
- **Held-out data.** The implementer, the growth agents and the test writers never read: the test or extra parser
  lines, any test label file, the test entries of `realistic_inputs.split.v1.json` and its label file, the owner
  sheet, or the D9 map. Unit tests use dev inputs or invented inputs only. Scripts print only counts for test data
  until Task 9. Disclosure: while planning, I saw four test input texts in a review report. No test in this plan uses them.
- The table only grows. v2 never removes or renames a v1 id.
- Never load `data/processed/recipes.jsonl`. No Kaggle run.
- No new dependency. A new CI job uses read-only permissions and SHA-pinned actions.
- A results file written on a dirty tree is rewritten after the commit.
- Docs change in the same commit as the behaviour. ASD-STE100 style.
- Every task ends with `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, and, for tasks that
  touch `web/`, `cd web && npm run typecheck && npm test`.

## 6. Review focus

The five failure modes most likely to hurt a person. Each one has a test in its owning task.

1. A typed name that is a real table name gets fuzzy-matched to another row. Expected: exact, split and contained
   steps win. Fuzzy runs only when they miss, and only on a unique best. Test in Task 3 (invented pair `pear`/`peas`).
2. A modifier word that changes the food is dropped ("lean ground beef", "whole milk", "dried apricot").
   Expected: the longest table key wins, and only tokens outside every key may be modifiers. Tests in Tasks 2 and 3.
3. The new singulariser breaks a key that used to match. Expected: `molasses`, `asparagus`, `hummus`, `couscous`,
   `bay leaves -> bay leaf`, `knives -> knife`, `cheeses -> cheese`, `chilies -> chili`, `potatoes -> potato`, `glass`
   give the expected singular on both engines. Golden token cases in Task 2.
4. An `is_a` or `form_of` edge points at a missing id or makes a cycle. Expected: the table load fails and names the id.
   Test in Task 2.
5. Python and TS differ on Unicode typed names (`jalapeño`, full-width letters, `½ cup`, `1⁄2 cup`). Expected: the same
   ids on both engines. Golden name cases in Task 3.

---

## 7. Tasks

Order: Task 1 first and alone. Then Task 2. Then Tasks 3 and 4, and the read-only part of Task 8, in parallel
worktrees. Task 5 owns `ingredients.v2.csv` from then on. Then Tasks 6, 7, 8, 9 and 10.

### Task 1: Freeze and label the evaluation sets (me and labelling agents; no product code)

**Files:** the Task 1 rows of the file map. Tests: `tests/eval/test_parser_gold.py`, `tests/eval/test_realistic.py`,
`tests/eval/test_m3_eval_sets.py`, `tests/eval/test_stats.py`.

**Interfaces:**
- Produces: key `mention_accuracy` in the dict from `parser_gold.score(lines, labels, table, id_map=None)`. With
  `id_map: dict[str, str | None]` (gold name to id), gold names map through it and not through the table.
- Produces: `score_inputs(inputs: list[str], labels: dict[str, Label], resolve: Callable[[str], list[str]], table,
  id_map=None) -> dict` in `pantrychef/eval/realistic.py`, returning `{"n", "correct", "input_accuracy"}`.
- Produces: `load_frozen() -> frozenset[str]` and `line_hash(text: str) -> str` in `parser_gold.py`.
- Produces: `wilson(k: int, n: int) -> tuple[float, float]`, `mcnemar_exact(b: int, c: int) -> float` in `stats.py`.

- [ ] **Step 1:** Write the tests. `test_mention_accuracy_counts_subset_reads` (gold `bulgur|cracked wheat`;
  predicted `{bulgur}` counts; `{bulgur, rice}` does not). `test_id_map_overrides_table_keys`.
  `test_input_accuracy_needs_all_groups` (gold `salt;black pepper`; `[salt]` wrong; `[salt, black_pepper]` right;
  `[salt, black_pepper, sugar]` wrong). `test_extra_lines_are_random_and_disjoint_from_sheet`.
  `test_frozen_lines_cover_test_and_extra` (250 hashes). `test_wilson_75_of_80` (lower bound 0.86 ± 0.01).
  `test_mcnemar_exact_symmetric`.
- [ ] **Step 2:** Run them. Expected: FAIL (names missing).
- [ ] **Step 3:** Implement. The extra-line draw uses sha256 order with seed 43, uniform over the distinct snapshot
  lines not in the sheet, with the filters of `make_parser_gold_sheet.py`.
- [ ] **Step 4:** Run. Expected: PASS. Register `mention_accuracy`, `input_accuracy`, `agreed_error_rate` and
  `recipes_fully_read` in the `results.py` registry.
- [ ] **Step 5:** Labelling. All agents are blind, read-only on shared files, one scope each. Each gets only a text
  column and `docs/PARSER_GOLD_GUIDE.md`, and writes one CSV to `data/interim/`:
  Opus 5.5 labels the 150 test lines and the 100 extra lines. Sonnet labels the 100 extra lines.
  Sonnet and Opus each label the 166 realistic inputs.
- [ ] **Step 6:** A script compares the labels (Opus vs `labels.test.v1.json`, Opus vs Sonnet on extra and inputs) and
  writes `data/interim/m3_owner_sheet.csv`: every disagreement, plus 30 agreed parser lines (seed 44). It shows line text
  and labels, never resolver output. It prints only counts. **The owner fills the sheet.**
- [ ] **Step 7:** Merge the answers into the new label files (file map). Stop and report if agreed-line errors exceed 2 of 30.
- [ ] **Step 8:** Score the M1 resolver on dev: `results/m3_m1_dev_baseline.json` (`mention_accuracy`,
  `parser_precision`, dev `input_accuracy` with `resolve_names`). Commit by explicit path.

### Task 2: Table v2, word file, singulariser (lane A, Sonnet, TDD)

**Files:** `data/ingredients/ingredients.v2.csv` (new copy), `data/ingredients/words.v1.json`,
`pantrychef/ingredients/{table,resolve,units}.py`, `web/src/normalize.ts`, `pantrychef/pack/allowlist.json`,
`scripts/make_golden.py`, `tests/test_table.py`, `tests/test_resolve.py`. Also every reference to
`ingredients.csv` that should read the new table (find them with `rg "ingredients\.csv"`). Eval scripts for M2 results
keep the v1 table.

**Interfaces:**
- Produces: `tokens(text: str) -> tuple[str, ...]` with the new singulariser (same name and module).
- Produces: `Row.is_a`, `Row.form_of: tuple[str, ...]`. `Words` frozen dataclass: `units: dict[str, str]`,
  `size`, `container`, `prep: frozenset[str]`, `staple_cue: frozenset[str]`, `bare_pepper: dict`.
- Produces: `IngredientTable.load(path=DEFAULT_TABLE_PATH, words=DEFAULT_WORDS_PATH)` and
  `IngredientTable.from_text(csv_text: str, words_json: str | None = None)`. `None` loads the default word file, so
  `pack/build.py` keeps working until Task 7. `IngredientTable.words: Words`.
- Produces: `is_modifier(token: str, words: Words) -> bool` (size, container, prep, or an `-ed` word as today).

- [ ] **Step 1:** Write tests. Golden token cases from Review focus 3. Edge tests: an unknown `is_a` id fails, a cycle
  fails, a self-edge fails. "1 lb lean ground beef" reads `ground_beef`, not `beef` (if the row exists; add it in the
  fixture). "3 large ripe pears, peeled and diced" reads `pear`. Every M1 resolver test still passes. A test that no
  string literal in `resolve.py` equals a table id.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Singulariser rules: keep words that end in `us`, `ss`, `is`; an exception map for
  `leaves -> leaf`, `halves -> half`, `knives -> knife`, `loaves -> loaf`, `chilies -> chili`, `cheeses -> cheese`;
  then the current rules. Port to `normalize.ts` line for line. `_PREP` and `UNITS` move to `words.v1.json`. The `salt`
  and `black_pepper` literals move to `staple_cue` and `bare_pepper` (M1 behaviour unchanged).
- [ ] **Step 4:** Re-pin the allow-list (`build_pack.py --pin`). Regenerate golden. Run all checks. Expected: PASS, golden
  diff only in token and name cases. Run `scripts/ingredient_coverage.py` before and after and put both lines in the
  commit message. Commit.

### Task 3: Typed-name resolver, Python and TypeScript (lane C, Sonnet, TDD; Opus reviews parity)

**Files:** `pantrychef/ingredients/names.py`, `pantrychef/engine.py`, `pantrychef/pack/build.py` (core gains `words`),
`web/src/{names,units,engine,types,PantryScreen}.ts(x)`, `scripts/make_golden.py`, `tests/fixtures/pack/`,
`tests/test_names.py`, `web/tests/parity.test.ts`.

**Interfaces:**
- Consumes: `tokens`, `Words`, `is_modifier` (Task 2).
- Produces: `resolve_name(text: str, keys: Mapping[str, str], words: Words) -> NameMatch`, where
  `NameMatch(ids: tuple[str, ...], step: Literal["exact", "split", "contained", "fuzzy", "none"])`.
  TS: `resolveName(text: string, keys: Record<string, string>, words: Words): NameMatch`.
- `resolve_names(pack, names)` and `Engine.resolve(names)` keep their signatures. `Engine` accepts a core with no
  `words` (empty lists), so the live `v1` pack still loads.

Steps. The first hit wins.
1. `exact`: `tokens(text)` is a key.
2. `split`: when the text has `and`, `&`, `,` or `/` and is not a key, split and resolve each part with steps 1, 3, 4.
   Every part must resolve, or the input is unknown. Ids are the union, in order.
3. `contained`: strip quantity and unit (`units.ts` ports `parse_quantity` and `parse_unit`, reading `words.units`).
   Find greedy longest key spans, as `_spans` does. Succeed when at least one span exists and every token outside
   the spans is a modifier. Ids are the span ids, in order.
4. `fuzzy`: on the tokens left after dropping modifiers, per D8.

- [ ] **Step 1:** Write tests, on invented or dev inputs only: `chicken thighs, boneless -> chicken_thigh` (dev,
  contained; add the row in the fixture), `s&p -> salt, black_pepper` (dev, split), `half and half -> half_and_half`
  (dev, exact), `cinamon -> cinnamon` (invented, fuzzy), `peas` stays `pea` when `pear` also exists (invented),
  `lean ground beef -> ground_beef` (invented, contained), two keys at equal distance give `none`, the screen adds both
  ids for `s&p` (Vitest component test or Playwright fixture step).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement Python, then the TS port. Add 40 or more name cases and the Unicode cases (Review focus 5)
  to `make_golden.py`. The fixture core and the pack core both gain `words`.
- [ ] **Step 4:** Run all checks, including the Playwright smoke test. Expected: PASS. Commit.

### Task 4: Growth row in the coverage script (lane E, Sonnet)

**Files:** `scripts/ingredient_coverage.py`, `pantrychef/pack/build.py` (`coverage`), `tests/test_coverage.py`.

**Interfaces:** Consumes `load_frozen`, `resolve_lines`, `parser_gold.score`, `score_inputs` (dev only).
Produces `--growth-row results/m3_table_growth.json`, which appends `{commit, resolver, rows, lines_read,
recipes_fully_read, mention_accuracy_dev, parser_precision_dev, input_accuracy_dev, top_unread}`. `resolver` names
the typed-name resolver used (`resolve_names` before Task 3 merges, `resolve_name` after).

- [ ] **Step 1:** Tests: a frozen line (any case variant) never counts in `top_unread` (5-page fixture snapshot).
  `coverage` matches a hand count on the fixture.
- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** PASS. Run row 0 on the real snapshot and
  record peak RAM with `tracemalloc` (must stay under 500 MB). Commit.

### Task 5: Grow the table (lane B, Sonnet writes rows, Opus reviews each round)

**Files:** `data/ingredients/ingredients.v2.csv`, `pantrychef/pack/allowlist.json` (re-pin), `results/m3_table_growth.json`.

Rounds of about 300 rows: 337, then about 640, 940, 1,240, 1,540, 1,840, and more only if needed. In each round:
- [ ] Take the top unread phrases from the last growth row.
- [ ] Write rows. Provenance `wikibooks-rule` for a row added for a counted phrase, `hand` for a UK/US name or a
  synonym. Add UK/US names (aubergine, courgette, rocket, prawn, cornflour, icing sugar, beetroot, mince) as synonyms.
  Add `is_a` and `form_of` where the relation is plain (`unsalted_butter form_of butter`, `cheddar is_a cheese`).
  Never remove or rename an id.
- [ ] Opus reviews 40 random new rows: wrong merges, keys that hide a real ingredient, wrong edges. Fix each
  Required Fix before the next round.
- [ ] Re-pin, run the coverage script with `--growth-row`, and commit the table, the pin and the row together.
- [ ] Stop when `recipes_fully_read >= 0.60` and the last round found fewer than 2 more dev gold groups. Stop and report
  if 2,500 rows do not reach 0.60.

Epicure (D10): a research agent checks in parallel and writes `docs/research/2026-11-m3/epicure.md`.

### Task 6: Bare "pepper" in recipe lines (Sonnet builds, Opus labels)

**Files:** `data/ingredients/words.v1.json` (`bare_pepper`), `pantrychef/ingredients/resolve.py`,
`results/m3_bare_pepper.json`, `tests/test_resolve.py`.

- [ ] Draw 80 bare-pepper lines (seed 45, no frozen line). Opus labels them blind (D5).
- [ ] Count black-pepper labels. Compute `wilson`. Write the results file.
- [ ] Encode the rule as data: `{"target": "black_pepper", "when": "always" | "staple_cue_or_taste"}`. Test both values.
- [ ] Commit.

### Task 7: Pack v2 (Sonnet)

**Files:** `pantrychef/pack/build.py` (`PACK_FORMAT = 2`), `pantrychef/pack/allowlist.json` (word file input),
`scripts/build_pack.py` (default `v2`), `pantrychef/engine.py` (`load_pack` default `v2`), `web/src/engine.ts`,
`tests/fixtures/pack/` and `make_fixture_pack.py`, `web/tests/parity.test.ts`, `scripts/make_golden.py`,
`web/e2e/smoke.spec.ts`, `web/public-e2e/`, `web/pack-hashes.json`, `.github/workflows/pages.yml` (`pack-v2`),
`tests/test_pack.py`.

- [ ] Test: the manifest lists the word file hash. The guard still rejects a file outside the allow-list.
- [ ] Build with `--pin`, then `--out build/pack`. Write `results/m3_pack_v2.json`: recipes (must be at least 2,500),
  `recipes_fully_read` (must be at least 0.60), core size (must be at most 3 MB).
- [ ] Run every check and the Playwright smoke test. Commit. Do not upload or deploy (D7).

### Task 8: ADR 0006 graph spike (Opus designs, Sonnet builds, owner rates)

**Files:** `pantrychef/eval/graph_spike.py`, `scripts/graph_spike.py`, `docs/research/2026-11-m3/graph_spike.md`,
`results/m3_graph_spike.json`, `docs/decisions/0006-hybrid-graph-knowledge-base.md`.

- [ ] Read-only, after Task 2: Opus writes the spike design. Pantries: the 20 M2 pilot pantries plus 20 new dev pantries.
  Traversal: a pantry item X satisfies a line that needs Y when X `is_a`* Y or X `form_of` Y. The design fixes the
  direction. It also checks the FoodOn licence and the literature.
- [ ] Owner confirms the thresholds (D11).
- [ ] After Task 5: freeze the table, edges, pantries and sampling plan in one commit, before any rating.
- [ ] Build the sheet: up to 100 newly surfaced recipes plus 100 decoys, shuffled, with real ingredient lines, and no
  edge or arm shown. The owner rates once.
- [ ] Score against the thresholds. Write the results file and the ADR update (Accepted or Rejected, with evidence). If
  edges change after rating, label the result exploration.

### Task 9: Acceptance (me; one run on the test data)

- [ ] D9 mapping: a fresh Opus maps the gold names to v2 ids, blind. The owner checks the mappings that differ from the
  table lookup. Commit `data/eval/m3_gold_id_map.v1.json`.
- [ ] On a clean tree, run `scripts/m3_acceptance.py` once. It scores `mention_accuracy` and `parser_precision` on the
  random lines (the D2 gate) and on `hard` and `rare` separately. It scores `input_accuracy` for M1 (v1 table,
  `resolve_names`) and M3 on the 83 test inputs, with `mcnemar_exact` and a paired bootstrap 95% interval. It adds the
  pack counts. It writes `results/m3_acceptance.json`.
- [ ] If any target fails, stop and report. Do not lower a target. Do not tune and score again.

### Task 10: Docs and review

- [ ] Update `docs/PROJECT_STATE.md` (section 12), `docs/DEVELOPMENT_PLAN.md` (M3 status), `docs/EVALUATION.md`
  (M3 section and reproduce rows), `docs/DATASET.md` (table v2, word file, labels), and `CLAUDE.md` if a path changed.
  Add a Mermaid diagram of the typed-name steps. It must match `names.py`.
- [ ] An Opus Review Agent that wrote none of the work tries to falsify the branch against real files, test output,
  results files and the held-out rules. Verdict GO, GO WITH FIXES or NO-GO. Resolve each Required Fix. Re-review any
  change to a metric.
- [ ] `superpowers:finishing-a-development-branch`. Commit, push and PR only when the owner asks.

## 8. Acceptance mapping

| Target | Evidence |
| --- | --- |
| At least 90% of Wikibooks mentions correct, hand-checked sample | `results/m3_acceptance.json`: `mention_accuracy` and `parser_precision` on the owner-adjudicated random lines (D1 to D3, D9) |
| At least 60% of recipes fully read, at least 2,500 recipes, unread lines show "check this line" | `results/m3_pack_v2.json`, the existing UI test for unread lines |
| At least 90% of held-out realistic inputs | `results/m3_acceptance.json`: test `input_accuracy`, M1 and M3 paired |
| Bare "pepper" decided | `results/m3_bare_pepper.json`, `words.v1.json` |
| Synonyms, UK/US names, Epicure checked | Task 5 rows, `docs/research/2026-11-m3/epicure.md` |
| Sets of ids, optional and unread flags | M1 behaviour kept. Task 2 and 3 tests |
| ADR 0006 decided, `is_a` and `form_of` columns | ADR update, `results/m3_graph_spike.json`, Task 2 |
| Resolver table, parity and guard tests | pytest, Vitest, the golden file, `test_pack.py` |

## 9. Risks

| Risk | Mitigation |
| --- | --- |
| 60% full-recipe coverage needs more than 2,000 rows (MEASURED before collapse) | Measure each round. Stop and report at 2,500 rows |
| Both labelling models share a family, so their errors correlate | 30 owner-checked agreed lines measure it (D1) |
| A wrong merge in the table scores as correct | D9 blind gold-to-id map |
| Wrong `is_a` edges create false "make now" | The product does not use edges in M3. The spike rates them blind |
| Fuzzy matching reads a wrong food | Exact, split and contained first; unique best only; the chip shows the read name |
| Owner time: about 60 lines (D1), 10 to 20 inputs (D4), 10 to 30 mappings (D9), up to 200 spike items (D11) | ESTIMATE: 3 to 4 hours, in four sittings |
| Low free RAM | The snapshot is 2.4 MB. Task 4 measures peak RAM |
