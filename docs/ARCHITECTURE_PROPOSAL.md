# Architecture proposal

Status: proposed on 2026-10-30. Parts built in M1 (2026-11-03) are marked Built in section 3
and in the diagram. Nothing else is built.
Decisions: [ADR 0003](decisions/0003-licence-clean-recipe-corpus.md),
[ADR 0004](decisions/0004-static-first-browser-engine.md),
[ADR 0005](decisions/0005-honest-claims-and-eval-reset.md).

## 1. Summary

PantryChef becomes a static web app. The browser does the search. Python builds the
data files before release. No server runs in the first release.

| Stage | Where it runs | What it does |
| --- | --- | --- |
| Build | GitHub Actions, the laptop, or Kaggle | Parse recipes, resolve ingredients, mine substitutions, evaluate, and write artifacts |
| Release | GitHub Releases | Store versioned artifacts with hashes |
| Serve | GitHub Pages | Serve the app and the data pack as static files |
| Use | The visitor's browser | Search, score, explain, and save the pantry |

## 2. System diagram

```mermaid
flowchart TB
  subgraph Sources["Data sources"]
    WB["Wikibooks Cookbook snapshot<br/>CC BY-SA 4.0: display"]
    OR["Open Recipes snapshot<br/>CC BY 3.0: statistics only"]
    USDA["USDA FoodData Central<br/>public domain: later"]
    RNLG["RecipeNLG<br/>research only: never shipped"]
  end

  subgraph Repo["GitHub repo: source of truth"]
    TABLE["Curated ingredient table"]
    PKG["pantrychef Python package"]
    WEB["web/ TypeScript app and engine"]
    GOLD["Golden test cases"]
    RES["results/ JSON files"]
  end

  subgraph Compute["Build compute"]
    LOCAL["Laptop: small builds and tests"]
    KAGGLE["Kaggle: full-corpus research and vision tests"]
  end

  subgraph CI["GitHub Actions"]
    TEST["Python tests, TypeScript tests, parity, evaluation floor"]
    REL["Publish release assets"]
    DEPLOY["Deploy to Pages"]
  end

  ART["GitHub Release:<br/>recipe pack, ingredient index,<br/>substitution table, manifest"]

  subgraph Browser["Visitor's browser"]
    UI["App on GitHub Pages: built, not deployed"]
    WORKER["Engine module: runs on the main thread in M1"]
    STORE["Planned: saved pantry. M1 stores nothing"]
    VISION["Planned: vision model, on demand"]
  end

  CDN["Planned: model files on Hugging Face"]
  API["Not planned yet: API with the same contract"]

  WB --> PKG
  OR --> PKG
  USDA -.-> PKG
  RNLG -.-> KAGGLE
  TABLE --> PKG
  PKG --> LOCAL
  PKG --> KAGGLE
  LOCAL --> RES
  KAGGLE --> RES
  PKG --> TEST
  WEB --> TEST
  GOLD --> TEST
  TEST --> REL --> ART
  ART --> DEPLOY
  TEST --> DEPLOY
  DEPLOY --> UI
  UI --> WORKER
  UI -.-> STORE
  UI -.-> VISION
  CDN -.-> VISION
  WORKER -.-> API
```

## 3. Component boundaries

| Component | Location | Input | Output | Status |
| --- | --- | --- | --- | --- |
| Source adapters | `pantrychef/sources/` | Snapshot file | `SourceRecipe` records with provenance | Built (M1): Wikibooks fetch and parse |
| Line parser | `pantrychef/ingredients/` | Ingredient line | Quantity, unit, ingredient text | Built; Unicode fractions added in M1 |
| Ingredient table | `data/ingredients/ingredients.v2.csv` | Hand curation | Ids, names, synonyms, staple flag | Built. `ingredients.csv` is the M1 table (337 rows). `ingredients.v2.csv` is the M3 table (872 rows) and the pack reads it. No diet flags yet |
| Resolver | `pantrychef/ingredients/resolve.py` | Text | Lines with option ids, or "unread" | Built (M1) |
| Typed-name resolver | `pantrychef/ingredients/names.py`, `web/src/names.ts` | One typed pantry name, the pack keys and word lists | Ids and the step that matched: exact, split, contained, fuzzy or none | Built (M3 task 3): matches Python on the golden name cases. A bare "pepper" stays unknown |
| Pack builder | `pantrychef/pack/` | Records and table | Recipe pack and manifest | Built (M1): hash allow-list and input guard |
| Reference engine | `pantrychef/engine.py` | Pantry ids, settings | `Answer` | Built (M1) |
| Substitution mining | `pantrychef/substitution/` | Open Recipes as ingredient sets | Top-k table with evidence | Built for RecipeNLG; needs retraining and table export |
| Evaluation | `pantrychef/eval/` | Engine, gold sets | `results/*.json` | Partly built; new protocols planned |
| Browser engine | `web/src/engine.ts` | Pack, pantry | `Answer` | Built (M1): matches Python on 202 golden cases |
| App | `web/src/` | Engine module | Screens | Built (M1): pantry, results and recipe screens. Not deployed |

Rules:

- One function, `answer()`, defines the behaviour. The TypeScript engine must match it.
- The app calls only the engine module. It does not read data files.
- Only the pack builder decides which data ships. It reads only input files on a hash
  allow-list, and a test fails if it opens any other data file. Comparing words cannot
  find derived data, so the control is on inputs and on a provenance column in the
  ingredient table.
- `LICENSES.md` lists the licence of each path and artifact. Committed recipe text, such
  as test fixtures, sits under a path with a CC BY-SA notice.

## 4. Data flow

```mermaid
flowchart LR
  A["Ingredient line"] --> B["Parse quantity and unit"]
  B --> C{"Resolve to an ingredient id"}
  C -- "known" --> D["Recipe ingredient with id"]
  C -- "unknown" --> E["Keep the text, mark as unknown"]
  D --> F["Recipe pack"]
  E --> F
  F --> G["Browser: index"]
  H["Pantry chips"] --> I["Resolver in the browser"]
  I --> J["Candidate recipes"]
  G --> J
  J --> K["Score and group: make now, one away, two away"]
  K --> L["Results with reasons"]
  M["Substitution table"] --> L
```

A recipe has lines. Each line holds a set of acceptable ingredient ids, because 1,517
of about 3,800 recipes have an "or" line. A line also has an `optional` flag and a
`read` flag.

A line that cannot be read counts as missing and appears with its original text as
"check this line". The app never hides it. The share of recipes with unread lines is a
reported metric (see M3). Do not reduce the pack to fully read recipes before you
measure the cost: a table with 2,000 rows fully covered only 53.4% of Wikibooks recipes
before collapsing.

## 5. Contract

Python dataclasses in `pantrychef/engine.py` and hand-written types in
`web/src/types.ts` define this contract. There are about 10 types, and the golden tests
catch drift, so we use no code generation.

```text
AnswerRequest   pantry: ingredient_id[], staples: ingredient_id[], diet: Diet | null, limit: int,
                unknown_names: string[]    (typed names that did not resolve; echoed in unknown_pantry)
Answer          groups: { make_now, one_away, two_away }, each group = { count: int, items: RecipeResult[] },
                unlocks: Unlock[], blockers: Blocker[], unknown_pantry: string[], pack: PackInfo
Unlock          ingredient_id, name, recipes: int    (items that would move the most recipes to make now)
Blocker         kind: clear_diet | add_item, ingredient_id: ingredient_id | null, name, recipes: int
                (shown on zero results)
RecipeResult    recipe_id, title, have: int, total: int, score: float, missing: Missing[], unread: int,
                diet_state, reasons: string[]
Missing         options: ingredient_id[], text, swap: SwapHint | null
SwapHint        ingredient_id, name, source: curated | mined, ratio: string | null, note: string | null
RecipeDetail    recipe_id, title, lines: Line[], steps: string[], servings?, time?, category?, source: Attribution
Line            text, options: ingredient_id[], optional: bool, read: bool
Attribution     url, revision_id, licence, retrieved_on, changes: string | null
Diet            vegetarian | vegan | gluten_free | dairy_free
DietState       fits | does_not_fit | unknown
PackInfo        version, commit, corpus_fingerprint
```

The engine module exports `ready`, `suggest`, `answer`, `recipe` and `swaps`. A base
URL in one config value locates the data files. If an API becomes necessary, only this
module changes. We add a Web Worker only if latency measurements need one.

## 6. Search and scoring

The display corpus has about 3,800 recipes. An exact scan is possible, so approximate
search and the old candidate ceiling do not apply to the product.

1. Treat staple-covered lines as satisfied. A line is staple-covered when any of its options is a staple.
2. For each recipe with a pantry id on a required, non-staple-covered line, count missing
   required lines. A line is satisfied if the pantry holds any id in its set. An unread
   line counts as missing. An optional line never counts. A recipe with no required,
   non-staple-covered line never appears.
3. Group by missing count: 0, 1, 2.
4. Inside each group, sort by length-normalised IDF cosine, then by fewer total lines,
   then by recipe id. IDF means inverse document frequency. It gives rare ingredients
   more weight. This is the one canonical order. Other documents link here.
5. Compute `unlocks`: for each ingredient missing from a one-away recipe, count the
   recipes it completes. Show the top items. This is the core promise, "the one item
   that unlocks more". Sort by count, then by ingredient id.
6. If all groups are empty and the pantry is not empty, compute `blockers`: the single change that returns the most
   results. A change is either clearing the diet filter or adding one item. Removing a pantry
   item never helps, because it cannot reduce a missing count. Until diet flags land in M5,
   only `add_item` applies. Sort by count, with `clear_diet` first on a tie, then by ingredient
   id.

The score in step 4 is `sum(w(line) for lines the pantry satisfies) / sqrt(sum(w(line) for all
lines))`. The name "IDF cosine" is shorthand, because this is not a true cosine.

- `w(line)` is the largest IDF among the line's options. It is 0 for an optional line, an
  unread line and a staple-covered line (any option is a staple).
- `idf(i) = log(1 + N / df(i))`, where `N` is the number of recipes in the pack and `df(i)` is
  the number of recipes with a line that lists `i`.
- If the denominator is 0, the score is 0.

M4 may change this, and the Python and TypeScript engines change together.

### Rules fixed while building M1 (2026-11-03)

The reference engine is `pantrychef/engine.py`. Building it showed gaps in the text above.
These rules are now part of the contract, and the TypeScript engine follows them.

1. **IDF in the pack.** The pack stores `idf(i) = log(1 + N/df(i))` per ingredient. Neither engine
   calls `log`. Both sum in line order, so scores agree bit for bit in practice.
2. **Staple-covered lines.** A line with any staple option is satisfied and weighs 0. Section 6 first
   said "satisfied only by a staple", which depends on the pantry. The new rule keeps the
   denominator independent of the pantry.
3. **`have` and `total`.** `total` counts required lines that are not staple-covered. `have` counts
   the ones the pantry satisfies. "Fewer total lines" in step 4 means this `total`. An unread line
   counts in `total` and never in `have`.
4. **Pantry.** The pantry is the given ids minus the request's staples. Ids unknown to the pack go to
   `unknown_pantry` and never reach scoring.
5. **Candidates.** A candidate has `have >= 1`. Optional and staple-covered lines do not make a
   candidate. The pack builder also rejects recipes with `total == 0` under the default staples.
6. **Unlocks.** For each one-away recipe, each option id of its missing line gets +1. An unread
   missing line adds nothing. The count covers all one-away recipes, not only the listed ones.
   Sort by count, then id. The list holds the top 10.
7. **Blockers.** Only `add_item` exists in M1. For each pack ingredient not in the pantry or the
   staples, count the recipes that would have `have >= 1` and at most 2 missing lines after adding
   it. Sort by count, then id. The list holds the top 5.
8. **Group counts.** Each group holds the full `count`. `items` is cut to `limit`.
9. **Ids.** `recipe_id` is ASCII (`[a-z0-9_-]`) and compares bytewise.
10. **Reasons.** `reasons` stays empty in M1. The card builds its text from `have`, `total` and `missing`.

The diet filter runs before step 3. It removes only `does_not_fit` recipes. When a diet is set,
`fits` sorts before `unknown` inside each group, ahead of the keys in step 4. `groups`, `unlocks`
and their counts include `unknown` recipes. Hiding them in the app is a display choice, and it
does not change the counts.

The learned ranker replaces only the first sort key in step 4, and only if it wins the
test in [ADR 0005](decisions/0005-honest-claims-and-eval-reset.md). Grouping stays,
because it is the product promise and users can understand it.

IDF values come from Wikibooks, or from Open Recipes if an experiment shows they
rank better. The evaluation decides.

## 7. Artifacts and versioning

| Artifact | Format | Size target | Source |
| --- | --- | --- | --- |
| `core.vN.json.gz` | Ingredients, recipe lines as ids, titles, IDF, name keys, word lists (for typed names), curated swaps | Under 3 MB | Table, word file, Wikibooks |
| `text.vN.json.gz` | Full recipe text, CC BY-SA 4.0 | Under 7 MB, so core and text stay under the 10 MB in ADR 0003 (ESTIMATE; a rough trim with steps measured 1.2 MB gzipped) | Wikibooks |
| `mined.vN.json.gz` | Mined swaps with evidence, only if M5 passes | Under 2 MB (ESTIMATE) | Open Recipes |
| `manifest.vN.json` | sha256, size, commit, input hashes and licences (snapshot, table, word file), licence of each file, counts | Small | Pack builder |

Pack format 2 (M3): the pack files are `core.v2`, `text.v2` and `manifest.v2`. The table is `data/ingredients/ingredients.v2.csv`. The core carries a copy of `data/ingredients/words.v1.json`. The Python line resolver reads that file at pack build only. The browser reads the copy in the core, and only to resolve typed names. Format 1 packs had no word lists.

The core file loads first. Full recipe text loads when needed.

- GitHub Releases holds immutable artifacts by tag. Git holds no generated data.
- The Pages build downloads release assets and checks the hashes.
- We do not use DVC. The manifest and tags give enough provenance at this size.
- Each result in `results/` records commit, dirty flag, config, corpus fingerprint,
  seed, metrics and the command.

## 8. Parity between Python and TypeScript

`scripts/make_golden.py` runs `answer()` on about 200 fixed pantries over a small
committed fixture pack. It writes the groups, the order and the scores. A Vitest test
runs the TypeScript engine on the same cases. Scores must match within 1e-9, and the
order must match exactly. CI regenerates the file and fails if it changes without a
commit.

### Typed-name steps (M3)

The typed-name resolver (`pantrychef/ingredients/names.py`, `resolve_name`) turns one typed
pantry name into ids. `web/src/names.ts` runs the same steps, and golden name cases hold the two
together. The diagram follows the Python code. Every step in it exists. The first hit wins.

```mermaid
flowchart TD
  IN["Typed text"] --> CLEAN["Clean: NFKC, lower case,<br/>non-ASCII digits and blanks to one space"]
  CLEAN --> EXACT{"Exact: the canonical tokens<br/>of the whole text are a key?"}
  EXACT -- yes --> HIT1["ids of that key<br/>step: exact"]
  EXACT -- no --> SPLIT{"Split on a comma, an ampersand or a slash (not between digits)<br/>or the word and. More than one part?"}
  SPLIT -- no --> LEAFIN
  SPLIT -- yes --> PARTS["Run the leaf steps on each part, in order"]
  PARTS --> ALL{"Every part found a match?<br/>The first miss stops the loop"}
  ALL -- yes --> HIT2["Union of the ids, in order, no repeats<br/>step: split"]
  ALL -- no --> LEAFIN["Leaf steps on the whole text"]

  subgraph LEAF["Leaf steps (one piece of text)"]
    direction TD
    LEXACT{"1. Exact: the tokens of the piece<br/>are a key?"}
    LEXACT -- yes --> LHIT1["step: exact"]
    LEXACT -- no --> STRIP["Parse quantity and unit off the front.<br/>Lone unit: a unit word with nothing after it,<br/>so the unit word is the name"]
    STRIP --> CONT{"2. Contained:<br/>greedy longest key spans, longest first, left to right.<br/>Every token outside the spans must be a modifier<br/>(size, container, preparation word, or an -ed word).<br/>At least one span is needed"}
    CONT -- yes --> LHIT2["ids of the spans, no repeats<br/>step: contained"]
    CONT -- no --> LONE{"Lone unit?"}
    LONE -- yes --> NONE["no match<br/>step: none"]
    LONE -- no --> FUZZY{"3. Fuzzy on the tokens that are not modifiers.<br/>Name of 4 or more characters, and not only unit words.<br/>Limit: 1 edit under 8 characters, 2 from 8.<br/>Distance: Damerau-Levenshtein over the whole key.<br/>Accept only when exactly one key has the best distance<br/>and that distance is within the limit"}
    FUZZY -- yes --> LHIT3["id of that key<br/>step: fuzzy"]
    FUZZY -- no --> NONE
  end
  LEAFIN --> LEXACT
```

Notes on the diagram:

- A bare "pepper" is not a key. The text stays unknown, and the person picks the pepper they hold.
- A "/" between two digits is a fraction and does not split the text.
- A lone unit word ("2 pints") may reach the exact and contained steps. It never reaches the fuzzy
  step, so "2 pints" does not become "mint".
- The fuzzy step compares only keys whose length is within the limit of the name length. A tie for
  the best distance gives no match.
- The split step runs the leaf steps on each part. If one part finds nothing, the code drops the
  split and runs the leaf steps on the whole text.

## 9. Kaggle

ADR 0003 removes full-corpus processing from the product build. Parsing Open Recipes
and building the pack should fit on the laptop or in CI (HYPOTHESIS: under 20 minutes
on a sample-based estimate). Kaggle remains for:

- Retraining mined substitutions on Open Recipes.
- Research on RecipeNLG: rule baselines at 1.27M recipes, which replace the retracted
  full-corpus claim. No output ships.
- Vision evaluation and quantisation tests.

The flow is: build a wheel at a tagged commit, upload it with the data as a private
Kaggle Dataset, run a thin script with `kaggle kernels push`, pull outputs, and check
hashes. Notebooks hold no logic. No GitHub, Hugging Face or other token enters a
Kaggle kernel. Kaggle quotas come from secondary sources, so check them on the first
run.

## 10. Vision (planned, gated)

- An on-device model, SigLIP2 or OpenCLIP with a permissive licence, matches image
  tiles against precomputed text embeddings for about 150 to 200 visible ingredients.
- The model loads only after the user asks, with a size warning. Files live on Hugging
  Face.
- Output is a checklist. Nothing enters the pantry without user action.
- Photos stay on the device. A Content Security Policy limits connections, and a test
  checks it.
- The feature ships only at a per-photo F1 of 0.5 or more and 5 or fewer edits per
  photo on a test set of 100 to 150 photos. If it fails, it does not ship.

## 11. Security and privacy

- The app has no server, no accounts, no secrets and no analytics in the first release.
- GitHub Pages cannot set response headers, so the Content Security Policy is a meta
  tag. It limits scripts and connections to known hosts. A meta tag cannot set
  `frame-ancestors`, so clickjacking protection is not available. The app has no
  sensitive action, so we accept this.
- All recipe text renders as text. It never renders as HTML. Wikibooks text is
  public input.
- Pack source links must start with `https://en.wikibooks.org/`. The builder rejects
  others, so a page cannot inject a `javascript:` link.
- The app validates and size-limits imported pantry files and shared URLs.
- Pin GitHub Actions by SHA. Use least-privilege permissions. Run `pip-audit` in CI.

## 12. Trade-offs

| Choice | Gain | Cost |
| --- | --- | --- |
| Wikibooks for display | Clear public right and full steps | 3,800 recipes and thin "make now" lists for some pantries |
| Browser engine | Free, private and durable | Two implementations held by parity tests |
| No API | Nothing to host | No heavy models on a server, and free text is limited |
| Curated table | Trustworthy names, flags and roles | Manual work; on Wikibooks before collapsing, 500 rows cover 75.4% of mentions and 16.1% of recipes in full |
| Deterministic scoring first | Explainable, and hard to fool | Less ML in the product until a ranker earns its place |

## 13. What this changes in the current code

| Code | Plan |
| --- | --- |
| `retrieval/`, `recommender/` | Keep as research and history. The new engine reuses ideas, not the runtime |
| `substitution/` | Keep. Retrain on Open Recipes. Export a table |
| `nutrition/`, `dietary/` | Keep nutrition unshipped. Replace the dietary tagger with table flags |
| `vision/`, `serving/` stubs, Hydra configs, MLflow, Docker placeholders | Deleted in M0 |
| `data/nutrition/aliases.json` | Unused in v1. Review its origin at M9 |
| `cli.py` | Change `cook` to call `answer()` |

## 14. Proposed direction: graph knowledge base with ML on top

Status: proposed, not accepted. [ADR 0006](decisions/0006-hybrid-graph-knowledge-base.md)
records it. Nothing in the sections above depends on it.

The owner intends a classical ML-backed project. The idea is a typed ingredient and recipe
graph, shipped as a static artifact, with ML for retrieval, ranking, ingredient
understanding and recommendations. It fits ADR 0004, because traversals can be precomputed
at build time. A spike in M3 decides whether the graph stays. ADR 0005 still decides whether
each model ships. If the spike fails, the design above stands, with a flat table.

## 15. Open questions

These do not block M0 or M1.

- Is 3,800 recipes enough for return visits? User testing will tell.
- How good is mined substitution at 168k recipes? The rating test will tell.
- What is the real latency on a low-end phone? The thin slice will measure it.
