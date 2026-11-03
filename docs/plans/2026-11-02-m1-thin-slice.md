# M1 thin slice: task-level plan

Status: DRAFT for owner review, 2026-11-02. No code exists for M1 yet.
Branch: `feat/m1-thin-slice`. Source of truth for scope: [DEVELOPMENT_PLAN.md](../DEVELOPMENT_PLAN.md) (M1).
Contract: [ARCHITECTURE_PROPOSAL.md](../ARCHITECTURE_PROPOSAL.md) sections 3 to 8 and 11.
Labels: MEASURED, ESTIMATE, HYPOTHESIS.

**Goal:** a hosted page where a person lists ingredients and sees grouped results (make now, one away, two away)
and the top items that unlock more. All recipes come from Wikibooks Cookbook. No server.

**Architecture:** Python fetches Wikibooks through the official API, parses it, resolves lines against a small
ingredient table, and builds a versioned pack. `answer()` in Python is the reference. A TypeScript engine in
`web/` returns the same results from the same pack. Parity tests hold the two together.

**Tech stack:** Python 3.11 (existing), Vite, TypeScript, Preact, Vitest, Playwright, GitHub Actions and Pages.

## 0. Out of scope for M1

Diet filter and `clear_diet` blockers (M5). Nutrition. Swap hints and the swap panel (M5). Saved pantry, export,
shared links (M6). Resolver fuzzy step and table growth (M3). Graph columns `is_a`, `form_of` (M3, ADR 0006).
Engine `reasons` text (the card shows "You have N of M" and the missing names; the field stays empty). Learned ranking (M4).
Open Recipes (M5). Any Kaggle job.

## 1. Decisions for the owner (please answer before code)

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | Contact in the Wikimedia User-Agent. I will not insert an email myself | Use the repo URL `https://github.com/aritr-codes/PantryChef-`. Wikimedia accepts a URL as contact. No personal email in git. Fetch is serial, with `maxlag=5`, about 100 requests in total |
| D2 | Where the snapshot lives | Working copy: `data/raw/wikibooks/` (git ignores it). Hash and revision count go in `docs/DATASET.md`. Release copy: a GitHub Release asset `wikibooks-snapshot-<date>`, uploaded only when you approve (it publishes content) |
| D3 | Default staples | `water`, `salt`, `black pepper`, plus a "cooking oil" group (vegetable, canola, sunflower, plain "oil"; not olive, sesame or palm). Each is a flag in the table and the person can switch each off (PRODUCT_VISION 11.1) |
| D4 | Bare "pepper" line | A line that says only "pepper" resolves to `black_pepper` when the line also names salt, or says "to taste", "ground" or "freshly ground". Otherwise it is unread ("check this line"). Reason: "salt and pepper" is the common case, and an unread line blocks make-now. M3 decides fully (510 such lines) |
| D5 | Deploy | I write `.github/workflows/pages.yml` with `workflow_dispatch` only. It does nothing until you enable Pages and run it. Pages needs `pages: write` and `id-token: write` on the deploy job only. All test jobs stay `contents: read` |
| D6 | Pack delivery to Pages | Pack files go to a GitHub Release (tag `pack-v1`), and the Pages build downloads them and checks them against **expected hashes committed in git** (a manifest downloaded from the same place proves nothing). Uploading the release also needs your approval |
| D7 | Recipe detail | The acceptance line "each recipe shows source link, revision and licence" needs a view. M1 builds a minimal detail view (ingredients, steps, attribution block). M6 makes it polished |

## 2. Contract gaps found while planning

The architecture says to record a change in the same commit as the code and update both engines together.
These are my proposals. The Review Agent should attack them.

1. **Pre-computed IDF.** The pack ships `idf` per ingredient (computed in Python). Both engines only add, take
   `sqrt` and divide. This avoids `Math.log` against C `log` differing in the last bit and flipping a tie order.
   Both engines sum in line order. Scores are then bit-identical in practice, and the 1e-9 test is a safety margin.
2. **Staple lines.** A line is *staple-covered* when any option is in the request's `staples`. It counts as
   satisfied and has `w = 0`. This makes the denominator independent of the pantry. A staple never appears as a missing item.
   This changes section 6, which gives `w = 0` only when a line is satisfied *only* by a staple (pantry-dependent).
   So "butter or oil" scores 0 even if the person has butter. Recorded in ARCHITECTURE_PROPOSAL section 6.
   Optional overrides unread: an optional line is never required, read or not.
3. **`have` and `total`.** `total` is the count of required lines that are not staple-covered. `have` is how many of
   those the pantry satisfies. "Fewer total lines" in the sort key means this `total`. An unread line counts in `total`, never in `have`.
4. **Candidates.** "Pantry" means resolved pantry ids minus the request's staples. A recipe is a candidate if the
   pantry holds at least one id from a *required, non-staple-covered* line (optional and staple lines do not make a
   candidate). `answer()` itself drops any recipe with `total == 0`, because a person can add staples such as flour
   that turn a valid recipe into total 0. The builder also rejects recipes with `total == 0` under the default staples.
5. **Unlocks.** For each one-away recipe, the missing line is read. Each option id of that line gets +1. An unread
   missing line adds nothing, because the person cannot add it. Sort by count, then id.
6. **Add-item blockers.** Runs only when all three groups are empty and the pantry is non-empty. For each
   candidate item, count the recipes that would have 2 or fewer missing lines after adding it (any group). The recipe
   must share one id with the new pantry. Top item wins; ties by id. Removing items never helps (kept from the architecture).
7. **Group counts.** `groups.X` is `{count, items}`. `count` is the full count and `items` is cut to `limit`. The UI
   needs the true count for "Make now (2)".
8. **"or" and "and" lines.** "A or B" gives one line with two options. "A and B", where every part resolves alone,
   gives one line per part. If any "and" part does not resolve, the whole line is unread, so a missing ingredient
   cannot be hidden. An "or" line is `read` if at least one option resolves, and unresolved options keep their text in `Line.text`.
9. **Pack contents.** `core` also holds line text and `page` + `revision` per recipe, because `Missing.text`
   needs the text. Core therefore carries CC BY-SA text, and the manifest says so. Size is measured against the 3 MB target.
   Steps and long text stay in `text`.

10. **Parity keys.** `recipe_id` is a string of ASCII `[a-z0-9_-]`, compared bytewise (builder-enforced; "10" < "9"
    in both engines). `limit` applies per group. `unlocks` and `blockers` return the top 10 and count over *all* one-away
    recipes, not only the listed ones. Blocker trial items are pack ingredient ids minus pantry and staples. `df(i)` counts
    recipes with any line that lists `i`, optional or unread lines included (they only get `w = 0`). The blocker
    "pantry non-empty" test uses resolved ids. Unknown typed names go to `unknown_pantry` and never reach scoring.
11. **Contract commits.** Each gap is written into ARCHITECTURE_PROPOSAL sections 5 and 6 in the Task 6 or Task 7 commit
    that implements it, not in Task 10.

## 3. File map

| Path | Action | Responsibility |
| --- | --- | --- |
| `scripts/fetch_wikibooks.py` | create | Thin entry point for the fetcher |
| `pantrychef/sources/wikibooks_fetch.py` | create | API client: category listing, batched wikitext, UA, maxlag, serial, resumable |
| `pantrychef/sources/wikibooks.py` | create | Wikitext to `SourceRecipe`; provenance per recipe |
| `pantrychef/sources/__init__.py`, `types.py` | create | `SourceRecipe`, `Attribution` |
| `pantrychef/ingredients/units.py` | modify | Unicode fractions inside lines, fraction slash after NFKC |
| `data/ingredients/ingredients.csv` | create | `id,name,synonyms,staple,provenance` |
| `pantrychef/ingredients/table.py`, `resolve.py` | create | Load table; resolve a line to options, `optional`, `read` |
| `pantrychef/pack/` (`build.py`, `guard.py`, `manifest.py`, `allowlist.json`) | create | Build `core`, `text`, `manifest`; input guard |
| `pantrychef/engine.py` | create | Dataclasses and `answer()` |
| `pantrychef/cli.py` | modify | `cook` calls `answer()` |
| `scripts/make_golden.py` | create | Writes `tests/golden/answer_cases.json` |
| `tests/fixtures/pack/` | create | Synthetic fixture pack: invented recipes, MIT, no Wikibooks text |
| `tests/fixtures/wikibooks/` + `NOTICE.md` | create | Real lines and pages for parser tests, CC BY-SA |
| `web/` | create | Vite, TypeScript, Preact app, `engine.ts`, `types.ts`, tests |
| `.github/workflows/ci.yml` | modify | Add `web` and `e2e` jobs, SHA-pinned, read-only |
| `.github/workflows/pages.yml` | create | Manual deploy (D5) |
| `results/m1_latency.json` | create | One measured latency record (the M2 helper does not exist yet) |
| `README.md`, `ARCHITECTURE.md`, `docs/PROJECT_STATE.md`, `docs/DATASET.md`, `LICENSES.md`, `.gitignore` | modify | Same change as the behaviour (see each task) |

`.gitignore` ignores `*.csv`. The table commit adds `!data/ingredients/*.csv`.

## 4. Tasks

Every task: write the failing test, run it, implement, run all tests plus `ruff`, update the docs it touches, commit.
Commit messages follow Conventional Commits. I stage by explicit path and never use `git add .`.
Before any heavy step (Vite build, Playwright) I check free RAM; below 1.5 GB I run it in CI instead.

### Task 1: Wikibooks fetcher
Consumes: nothing. Produces: `fetch_snapshot(out_dir, user_agent, *, transport) -> SnapshotInfo`; snapshot file
`data/raw/wikibooks/snapshot.<date>.jsonl.gz` (one line per page: `page_id`, `title`, `revision_id`, `timestamp`, `wikitext`); a sidecar with the sha256.
- Tests (offline, a fake transport): sends the given User-Agent and `maxlag=5`; follows `cmcontinue`; stops and waits on a `maxlag` error; requests are serial; re-run skips pages already stored; output is sorted by `page_id` so the hash is stable.
- API details: list `Category:Recipes` (namespace 102, `Cookbook:`), walk subcategories once with a visited set, then fetch with `prop=revisions&rvprop=ids|timestamp|content&rvslots=main&formatversion=2`, 50 titles per request. Follow both `cmcontinue` and `rvcontinue`, and honour `Retry-After` on a maxlag error. Tests cover both continuations.
- The run against the live API needs D1. I will do a 20-page dry run first, then the full run (about 100 requests, ESTIMATE).
- Commit: `feat(sources): fetch Wikibooks Cookbook through the MediaWiki API`.

### Task 2: Source adapter and parser fixtures
Consumes: snapshot lines. Produces: `parse_page(record) -> SourceRecipe | None` with `title`, `page`, `revision_id`, `url`, `licence="CC BY-SA 4.0"`, `retrieved_on`, `ingredient_lines: list[str]`, `steps: list[str]`, `category | None`, `servings | None`, `time | None`.
- Fixture files are `.json` (git ignores `*.jsonl` and `*.csv`). Fixtures: about 40 real lines and 3 whole pages from the fetched snapshot, under `tests/fixtures/wikibooks/` with `NOTICE.md`. `LICENSES.md` lists the path.
- Tests: Unicode fractions (`½`, `1½`), ranges, "or" lines, section headings inside the ingredient list, links and templates stripped to text, a page with no ingredient list returns `None`, URL is built from the title and starts with `https://en.wikibooks.org/`.
- Wikitext first. If infobox parsing proves weak, I record it and fall back to rendered HTML. Servings and time are optional (about 33% have them).
- Commit: `feat(sources): add Wikibooks source adapter with provenance`.

### Task 3: Line parsing fixes
Modify `units.py` so `½` and `1½` work after NFKC, and so a leading quantity or unit never leaks into the name.
- Tests: the fixture lines from Task 2 give the expected quantity, unit and rest.
- Commit: `fix(ingredients): parse Unicode fractions in real recipe lines`.

### Task 4: Ingredient table and resolver
Produces: `IngredientTable.load(path)`; `resolve_line(text, table) -> ResolvedLine(options: tuple[str, ...], optional: bool, read: bool, text: str)`.
- Table: I write about 400 rows by hand from general cooking knowledge (`provenance=hand`), plus rows from rules over Wikibooks lines (`provenance=wikibooks-rule`). I do not open `data/processed/vocab.json`. A test fails if the table loader or resolver imports or reads it. Columns stay `id,name,synonyms,staple,provenance`, so M3 can add `is_a` and `form_of`.
- Resolver: `canonicalize` (reuse), then longest contiguous table name or synonym; "or"/"and" rules (gap 8); `optional` for "optional", "for serving", "for garnish", "to taste" on a staple; D4 pepper rule (marked provisional in code and docs; M3 decides). PRODUCT_VISION section 9 says a typed "pepper" is Ambiguous and the app asks, so Task 8 shows a pick list for ambiguous suggestions.
- Tests: table rows unique and canonical; the adversarial cases from the audit as unread or correct (egg noodle is not egg, peanut butter is not butter); unread lines keep their text.
- Measure and report (MEASURED, not hidden): share of lines read, share of recipes with every required line read, top 50 unread phrases. Write it to `docs/research/` as a note, and mention it in PROJECT_STATE.
- Commit: `feat(ingredients): add first ingredient table and line resolver`.

### Task 5: Pack builder, guard, manifest
Consumes: snapshot, table. Produces: `build_pack(allowlist, out_dir) -> Manifest`; `core.v1.json.gz`, `text.v1.json.gz`, `manifest.v1.json`.
- Guard: `guard.py` registers ONE process-wide audit hook (hooks cannot be removed) that acts only while a ContextVar switch is on. While on, reads are **denied by default**. Allowed: the interpreter and site-packages, the repo's own code files, allow-listed inputs, and writes into `out_dir`. Paths are normalised with `realpath` and `normcase` (Windows case, relative, bytes and fd opens). Allow-listed files are hashed once before the build, so the hook never recurses. The hook also denies `subprocess.Popen`, `os.system`, `os.exec*`, `socket.connect` and `ctypes.dlopen` during a build. Known remaining escape: C libraries that call `fopen` directly. The docs list it. The guard is a tripwire for accidents, not a sandbox. A violation raises `GuardViolation`. The allow-list holds the snapshot and `ingredients.csv`, each with its sha256.
- Tests: (a) the real build opens only allow-listed files; (b) a stub builder that opens a temp copy of `vocab.json` **outside the repo** fails (deny by default); (c) a changed hash fails; (d) a source URL that does not parse with `URL` to scheme https and host `en.wikibooks.org` fails the build; (e) the manifest lists every shipped file with sha256, size, licence, input hashes, commit and dirty flag; (f) `core` gzipped is under 3 MB, a **local** check on the real pack (CI has no snapshot); (g) a recipe with `total == 0` is rejected; (h) a stub that spawns a subprocess or opens a socket fails.
- The guard test lands before any workflow can deploy. D6 release upload waits for approval.
- Commit: `feat(pack): add pack builder with input allow-list and guard test`. Independent review runs after this task.

### Task 6: Reference engine and `cook`
Produces in `pantrychef/engine.py`: `AnswerRequest`, `Answer`, `RecipeResult`, `Unlock`, `Blocker`, `Missing`, `PackInfo`, `load_pack(path) -> Pack`, `answer(pack, request) -> Answer` (contract section 5, gaps 1 to 7).
- Tests, with hand-computed values on the fixture pack: score formula (`sum w / sqrt(sum w_all)`) on a 3-recipe case; denominator 0 gives score 0; optional, unread and staple-covered lines have `w = 0`; "or" line satisfied by any option; an unread line counts as missing; sort keys (score, fewer total, recipe id); unlocks ordering; blockers only when all groups are empty; `diet` not null raises `NotImplementedError` in M1; group `count` is independent of `limit`; empty pantry gives empty groups and no blockers.
- `pantrychef cook --have eggs,flour --pack <dir>` resolves names with the table and prints groups, unlocks and blockers. The old `cook --recipes` path (RecipeNLG) is removed from `cook`, and its test is rewritten.
- Commit: `feat(engine): add answer() with groups, unlocks and blockers`, then `feat(cli): cook uses answer()`.

### Task 7: Golden file and TypeScript engine
Produces: `scripts/make_golden.py` (about 200 pantries: seeded random plus hand edge cases, over the fixture pack); `web/src/types.ts`; `web/src/engine.ts` exporting `ready`, `suggest`, `answer`, `recipe` (`swaps` is a stub that returns `null` until M5).
- Vitest: for every golden case, order is exact and each score is within 1e-9. TypeScript `canonicalize` has its own golden cases (hand-written plus fixture-pack names, nothing from RecipeNLG-era tests), generated by Python, because pantry text is resolved in the browser.
- CI regenerates the golden file and fails on a diff (files written with LF).
- Commit: `feat(web): add TypeScript engine with golden parity tests`.

### Task 8: Screens, security, smoke test
Pantry screen (labelled input, combobox suggestions, chips, quick add, staples panel, live count button) and results screen (groups, "Add X to move N recipes to make now", "Show more", "check this line"). Minimal detail view per D7.
- The CSP meta tag comes before any script and sets `default-src 'self'; base-uri 'none'; object-src 'none'; form-action 'none'` (`default-src` does not cover the last three). Links are parsed with `URL` and need scheme https and host `en.wikibooks.org`. Titles are percent-encoded.
- All recipe text renders as text (Preact escaping). A test fails if `dangerouslySetInnerHTML` or `innerHTML` appears in `web/src`. Source links render only if they start with `https://en.wikibooks.org/`, and open in a new tab with `rel="noopener noreferrer"`.
- CSP meta tag limits scripts and connections to `self`. A test checks the tag. No analytics, no cookies.
- Playwright smoke runs in CI on the **fixture pack** (CI has no real pack). Steps: open the built page, add 4 ingredients, see a result group and an unlock line, open a recipe and see the link, revision and licence.
- Commit: `feat(web): add pantry and results screens`, then `test(web): add Playwright smoke test`.

### Task 9: CI and latency
New jobs `web` (npm ci, `npm audit --omit=dev`, tsc, Vitest, parity) and `e2e` (Playwright, fixture pack). Actions pinned by SHA, `permissions: contents: read`. I also check whether the Node 20 deprecation warnings need new pins.
- Latency: a **local** run (and a CI run after D6 makes the real pack available) measures `answer()` time on the real pack with a 6x CPU throttle through the Chrome DevTools Protocol, and writes `results/m1_latency.json` (commit, dirty flag, config, pack fingerprint, seed, metrics, command). Under 100 ms passes. Above it, I record the number and add a Web Worker plan to PROJECT_STATE. The 6x throttle is an ESTIMATE of a low-end phone, not a measurement of one.
- Commit: `ci: add web and e2e jobs`, `perf(web): record throttled latency`.

### Task 10: Docs and deploy workflow
README Built and Planned table, `ARCHITECTURE.md` (diagram matches code), `docs/PROJECT_STATE.md` (M1 measurements, labelled), `docs/DATASET.md` (snapshot hash), `LICENSES.md` (fixture path, pack files), contract changes in ARCHITECTURE_PROPOSAL sections 5 and 6 (gaps 1 to 9), `pages.yml` (D5).
- Deploy does not run. I stop and ask you before enabling it or uploading a release.
- Commit: `docs: record M1 behaviour and measurements`, `ci: add manual Pages deploy workflow`.

## 5. Independent review points

A Review Agent that did not write the code tries to falsify the work, with real files and test output:
1. This plan, now, before you see it.
2. After Task 5 (guard and licence boundary).
3. After Task 7 (contract and parity; re-review if rules change).
4. Whole branch before I report M1 complete.
Required Fixes are resolved, or I state the disagreement.

## 6. Acceptance mapping

| Acceptance | Evidence |
| --- | --- |
| Hosted page returns grouped results and unlocks | Playwright smoke on the built page (hosted page only after D5 approval) |
| Parity on golden cases | Task 7 Vitest plus CI regenerate check |
| Guard fails on an out-of-list open | Task 5 test (b) and (c) |
| Core under 3 MB | Task 5 test (f), size in manifest |
| Latency under 100 ms or a Worker plan | Task 9 `results/m1_latency.json` |
| Source link, revision, licence per recipe | Task 8 smoke and manifest check |

## 7. Risks

- **Many unread lines.** A 400-row table will leave many lines unread. I report the share and the top unread phrases. M1 has no coverage target. M3 owns 60% of recipes fully read.
- **Few results.** With many unread lines, make-now lists may be thin. The result counts on 10 sample pantries are reported, not tuned.
- **Wikitext variety.** Templates and nested lists may break the simple parser. Pages that fail to parse are counted and listed, not dropped silently.
- **Memory.** Free RAM was 1.8 GB at the start of this session. The snapshot is under 100 MB in memory, and I do not touch `recipes.jsonl`.
- **Unicode versions.** Python 3.11 and Node ICU may normalise rare characters differently under NFKC. The golden cases include Unicode fractions and accents, and CI pins the Node version.
- **Float order.** Mitigated by gap 1. The golden test covers exact ties.
- **Commit 3bbe624** holds three RecipeNLG quotes. I add none, and no fixture or table row comes from RecipeNLG.
