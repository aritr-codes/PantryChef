# 0006. Hybrid: a graph knowledge base with ML on top

- **Status:** Rejected on 2026-11-09 by the rule in this ADR: the M3 spike surfaced no new recipe. See "Outcome of the M3 spike". The structure question stays open for a new spike with new pantries.
- **Date:** 2026-10-30
- **Deciders:** Project owner (intent), Tech Lead

## Context

The owner intends a classical ML-backed project, not a recipe search with ML attached.
The direction to investigate is a structured, graph-based ingredient and recipe knowledge
base with carefully designed fast retrieval. ML would enhance retrieval, ranking,
ingredient understanding and recommendations. The owner does not want this forced if
research suggests a better approach, and does not want it lost.

The current plan pulls the other way:

- The ingredient table is "a table, not a true graph" in the worst case
  ([portfolio table](../DEVELOPMENT_PLAN.md#portfolio-coverage-and-its-honest-limit)).
- A deterministic rule ships unless a model wins ([ADR 0005](0005-honest-claims-and-eval-reset.md)).
- If all gates fail, the browser runs no ML.

The evidence so far does not show that a graph or a model helps. It also does not show
that they cannot:

- Graph MRR against word2vec has a 95% interval that includes zero (MEASURED, n=82). The
  hybrid arm's interval against word2vec excludes zero (+0.059, 0.007 to 0.110), but its
  settings were tuned on the same queries, so this is not a win.
- The top result for 50 common ingredients was usually a name variant (MEASURED, one rater,
  not blind).
- On pantries with distractors, an IDF rule led a retrained model on MRR@10 at 10 and 20
  extra items (MEASURED, but the rule's output is not committed, no paired intervals, and the
  distractor sampler favours IDF). The retrained model's recall@10 at those points was 0.986
  and 0.944. No recall figure exists for the rule.
- All of that work used RecipeNLG and a mined or leaked task. None of it tests a curated
  graph on real pantries.
- With about 3,800 recipes, an exact scan is possible (HYPOTHESIS until M1 measures
  latency). "Fast retrieval" therefore does not need approximate search. It needs a good
  index and a measured latency.
- The largest limit on ML depth is labels. The plan has up to about 1,500 human judgments
  (ESTIMATE). That suits a small model, not a large one (HYPOTHESIS).

This ADR does not weaken ADR 0005. It separates two questions, and each has its own test.

1. **Structure:** does a typed graph change results for the better, compared with a flat
   table?
2. **ML:** does a model on that structure beat the no-ML rule?

## What counts as a graph

We use the word "graph" for the product only if both conditions hold:

- The data has typed nodes and at least two typed edges that a query uses.
- The decision rule below shows that traversal improves results, compared with the same
  data used as flat lookups.

Otherwise, the documents keep the word "table".

## Options considered

1. **Flat table and rules (current plan).** Cheapest, and serves users. It gives a weak ML
   story if the gates fail.
2. **Typed graph as a static artifact, with ML under gates (proposed).** Fits ADR 0004.
   Precompute traversals at build time and ship arrays and posting lists. ML runs at build
   time where it can, which avoids a second implementation in TypeScript.
3. **Knowledge graph embeddings or a graph neural network in the product.** Too little data
   and hard to explain. Parity with TypeScript is hard. Keep as a Kaggle research arm only.
4. **Graph database and a server.** Breaks ADR 0004 and needs a host. Rejected.
5. **Embedding-first retrieval (two-tower, approximate search).** No interaction data, and
   the corpus is small enough to scan. Rejected for the product.

## Proposed shape

```mermaid
flowchart TB
  subgraph Planned["All parts are planned. None is built"]
    KB["Knowledge base<br/>nodes: ingredient, class, recipe<br/>edges: is_a, form_of, substitutes_for, requires"]
    RES["Ingredient understanding<br/>rules first, then a small mention classifier"]
    PROP["Edge proposals<br/>mined from Open Recipes, a person accepts each"]
    IDX["Retrieval<br/>precomputed expansion and posting lists"]
    RANK["Ranking<br/>IDF rule, or a small model if it wins"]
    REC["Recommendations<br/>unlocks and swaps with reasons"]
  end
  PROP --> KB
  RES --> KB
  KB --> IDX --> RANK --> REC
  KB --> REC
```

| Layer | Idea | No-ML or flat baseline | Test |
| --- | --- | --- | --- |
| Knowledge base | Add `is_a` and `form_of` edges to the M3 table. Model curated swaps as `substitutes_for` edges | Flat table | Rows and edges carry provenance. Hand review of a sample |
| Retrieval | Expand a pantry through the edges. Direction matters: unsalted butter satisfies butter, and the reverse needs a decision. The bare "pepper" case in M3 is the same problem | No traversal, on the table after collapse and synonyms | The decision rule below |
| Ingredient understanding | A small classifier maps a mention to a node, at build time | Exact, synonym and fuzzy steps from M3 | Hand-labelled gold set, split into dev and test |
| Edge proposals | The existing context graph code proposes candidates from Open Recipes. A person accepts each one | Curated edges only | Acceptance rate. Mined edges without review follow the M5 rule |
| Ranking | Graph features, such as the role of a missing item, in a small model | IDF rule | M4 gate: paired 95% interval of the gain excludes zero, on human judgments |
| Recommendations | Weight `unlocks` by the graph | Count of recipes unlocked | Human judgments on held-out pantries |

Rules that stay in force:

- A metric that selects a model must not be a function of that model's features. Graph
  edges must not define the labels that judge a graph feature.
- Do not tune on the set you report on. Report paired intervals.
- No RecipeNLG-derived node, edge or model ships (ADR 0003). The FoodOn and Epicure data
  licences are unverified. Do not adopt them until someone verifies them.

## Decision rule

Run a spike of 2 to 3 days in M3 (ESTIMATE), after collapse and synonyms are in the table.

- **Pantries:** the 20 pilot pantries from M2, plus 20 written for the spike. All 40 are dev
  pantries. None may enter the M4 test split.
- **Baseline:** the same table with no traversal. Collapse and synonyms may already deliver
  the same effect, so a graph gets no credit for them.
- **Freeze:** fix the table, the edges, the pantries and a sampling plan before any judging.
  Make one pass. If edges change after judging, the result counts as exploration, and a new
  set of pantries is needed for the decision.
- **Measure:** sample up to 200 recipes that traversal newly moves into "make now" or "one
  away", and mix in an equal number of baseline results as decoys. A person judges from the real
  ingredient lines whether the pantry really meets the claim, with no view of the edges or of
  the source of each recipe. The label therefore does not depend on the edges under test. If the
  rater also wrote the edges, or only one rater is available, report that limit.
- **Accept** only if all of these hold. The thresholds are proposals. The owner fixes them
  before the spike starts:
  - A query uses at least two edge types.
  - Correct new recipes minus wrong new recipes, per pantry, has a 95% interval above zero.
    The baseline adds no new recipes, so this is a one-sample interval.
  - At least 90% of newly surfaced recipes are judged correct, for "make now" and for "one
    away", each counted alone.
- **Otherwise:** reject this ADR, keep the table and record the result. Having no newly
  surfaced recipes is a rejection.

ML layers do not depend on this rule. M4 sets the pass criterion for ranking. Each other
layer needs a pass criterion, fixed before its work starts, using the test named above. No new
external research was done for this draft. The spike must check the licences and the
literature.

## Reconciling with current documents

- "A deterministic rule ships unless a model wins" stays true.
- "A table, not a true graph" becomes a testable outcome. It stays the honest worst case.
- ML at build time counts as ML in the product, if it passes its test. A browser with no
  model is no longer the same as a product with no ML.
- ADR 0005 can still leave a product with no shipped model. In that case, the ML work is a
  published research result. This ADR cannot promise more, and the owner should weigh it. The
  private RecipeNLG track on Kaggle could then give more training data for research only.

## Consequences

- Positive: a clear path to the owner's intent, with tests that can fail. The M3 table gains
  columns at a small cost, whichever way the spike goes.
- Negative: more design work in M3. A graph-feature ranker takes a system slot in M4 or grows
  its budget of 3 systems and about 1,500 judgments, so decide that at the end of M3. Wrong edges can create
  false "make now" results. Traversal logic adds parity cases, unless it is precomputed.
- Revisit when: the M3 spike ends, or M4 and M5 results change the balance.

## Outcome of the M3 spike

**Result: Rejected, reason "no newly surfaced recipes".** The decision rule above says that having no newly surfaced
recipes is a rejection. This outcome is narrow. It rejects the tested setup, not the idea of a graph (see
"What this does not show").

Evidence (MEASURED, [results/m3_graph_spike.json](../../results/m3_graph_spike.json); inputs frozen in commit
e33e630, files in `data/eval/graph_spike/`):

- Edge option b: traversal follows only the edges that a blind labeller marked usable, with two owner edits.
  The table has 157 edges (81 `is_a`, 76 `form_of`). Of these, 17 are usable: 16 `is_a` and 1 `form_of`
  (`coffee_powder` to `coffee`). The longest chain has one edge.
- Pool of new recipes: 0 for `is_a` and 0 for `form_of`. No recipe moves into "make now" or "one away" through
  an edge, compared with the same table without traversal.
- Edge-source hits: 0 of 40 pantries. No pantry lists the specific food at the start of a usable edge, such as
  gouda or ciabatta. Decoy candidates exist (733 for "make now", 1,750 for "one away"), but without new items
  no sheet was built.
- No person rated anything. The thresholds T1 to T3 were not tested. The owner confirmed them before the freeze:
  T1 and T2 as written above, T3 as a Wilson lower bound of at least 0.80 with at least 20 rated items per group,
  and "unsure" counts as wrong.

Cause (MEASURED counts, one read-only probe of the pantry file): the pantries name general items, such as
"cheese", "cream cheese" and "cottage cheese". The usable edges run from a specific kind to a general one, so a
pantry that already holds the general name gains nothing. The writer of the 20 new pantries did not see the table
or the edges, and its prompt did not mention kinds.

What this does not show:

- It does not show that traversal fails for a person who types a specific name. That test needs pantries that
  contain specific kinds. HYPOTHESIS: such pantries would surface new recipes.
- It does not show anything about multi-hop traversal. The table has no chain longer than one edge.
- `form_of` rows in the table mostly mean "made from", not "can stand in for". Only 1 of 76 is usable, so the
  spike could not test mixed edge types. T1 needed both types.
- One model labelled the edges. One model wrote the new pantries. No person rated.

Consequences:

- The table keeps its `is_a` and `form_of` columns as data. The documents keep the word "table" and do not call
  the product a graph.
- The 40 spike pantries stay dev pantries. None may enter the M4 test split (the check is in
  `docs/research/2026-11-m3/graph_spike_design.md`, section 2.2).
- A new spike needs new pantries. It would include pantries that name specific kinds, and the owner would confirm
  T1 again, because the table gives only one usable `form_of` edge. The M3 typed-name resolver already covers
  synonyms, split, contained and fuzzy names, so a new spike must show a gain beyond those steps.
- Licence and literature checks are in `docs/research/2026-11-m3/epicure.md` and the design file, section 6.
  The FoodOn and Epicure data stay unadopted.
