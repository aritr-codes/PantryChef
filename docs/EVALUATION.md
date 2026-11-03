# Evaluation

> **Status, 2026-10-30: historical record. Do not quote these numbers as product quality.**
> An audit tested them ([TECHNICAL_AUDIT.md](TECHNICAL_AUDIT.md),
> [ADR 0005](decisions/0005-honest-claims-and-eval-reset.md)). The prose below is the original
> text, so its confident wording ("crushes", "flagship", "confirmed") no longer stands. New
> evaluation starts in M2. Each new number will link to a results file.
>
> | Section | Verdict |
> | --- | --- |
> | Phase 1 parser F1, retrieval recall@10 | UNSUPPORTED. No log exists. Gold comes from the same data |
> | Phase 2 "graph beats food2vec" | RETRACTED as a headline. Full corpus: the 95% interval for the MRR difference is -0.048 to +0.111. β was tuned on the same 82 queries |
> | Phase 2 hybrid arm | Not a win. Against word2vec, +0.059 with a 95% interval of 0.007 to 0.110, but it was tuned on the same queries |
> | Phase 2 28k tables | STALE. Pre-fix sample run |
> | Phase 2 dietary 100% | RETRACTED. The tagger checks itself, so the metric cannot fail |
> | Phase 2 GISMo table | UNSUPPORTED. Pre-fix, never rerun. GISMo's model was never run |
> | Phase 3 50k table | Sanity test only. The task leaks the answer. A no-ML rule scores 0.975 on a 1,404-query set |
> | Phase 3 full corpus (7.7×, ceiling 0.706) | RETRACTED. Pre-fix. The post-fix run ended in `MemoryError` |
> | "Saturates at 10k" and "~25 minutes" | RETRACTED. The metric sees only the gold slot, and no full production run completed |
> | "What ships" (production bundle) | FALSE. The only bundle on disk has 1,000 recipes, 3 models and an older commit |
> | sub_fill null | STANDS, on the same leaked task |
> | Phase 4 nutrition coverage | RETRACTED. First 5,000 rows only. A random sample gives 0.710 and 0.439. No log exists |

## M2 evaluation baseline (2026-11-03)

M2 measures the ranking rules before any model changes them. Plan: [docs/plans/2026-11-03-m2-eval-baseline.md](plans/2026-11-03-m2-eval-baseline.md).

### What the metrics are for

| Role | Metric | May select a model? |
| --- | --- | --- |
| `selection` | Hand-judged pairwise win rate (M4) | Yes. It uses no model feature |
| `sanity` | Masked recovery: recall@10 and MRR@10 of the source recipe | **No.** The query comes from the gold recipe, so the task leaks (ADR 0005) |
| `product` | Makeable at 10, hit rate, visible rate | **No.** They read the same lines as the rules |

`pantrychef/eval/results.py` holds a fixed registry of roles and dependencies. `assert_selectable` fails when a metric has another role than `selection`, or shares a dependency with the features of an arm. The tests prove both failures. The check guards declarations. It cannot prove that a declaration is complete, so a review reads the metric code.

### Task and arms

MEASURED setup. A gold recipe has at least 3 required lines. The task masks `floor(0.25 × total + 0.5)` of them and removes every ingredient of a masked line from the pantry. It adds 0, 3 or 6 distractor ingredients. Two samplers pick the distractors: `uniform` (even over the ingredients) and `popularity` (by the number of recipes that list the ingredient). Each gold recipe gives 3 pantries. Gold recipes split 50/50 into dev and test by a hash of the normalised title. All numbers below use the test half.

Every arm ranks the same candidate set: all recipes with at least one required line in the pantry. Arms differ only in order.

| Arm | Order | Role in the study |
| --- | --- | --- |
| `random` | seeded shuffle | Floor |
| `overlap` | most lines held, then fewer lines, then id | The no-ML baseline |
| `idf_flat` | IDF score (rare ingredients weigh more), no groups | The shipped score without grouping |
| `shipped` | missing lines (0, 1, 2, more), then IDF score | The product order |

### How to read the first results

The table block at the end of this file is generated. Do not edit it by hand. Run `uv run python scripts/eval_tables.py` to rebuild it, and `--check` to test it. The raw file is [results/m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json).

- MEASURED: `idf_flat` beats `overlap`, and `overlap` beats `random`, in all five (sampler, distractor) groups. Every paired 95% interval excludes 0. On the test half, the MRR gain of `idf_flat` over `overlap` runs from +0.227 to +0.375.
- MEASURED: `shipped` ranks the masked gold recipe low (MRR@10 from 0.014 to 0.098). This is a property of the task. The masked gold always misses at least one line, and `shipped` lists recipes you can make now first. The task does not measure what the product promises. The judged pilot (Task 7) is the test that can.
- MEASURED: `answer()` would show the masked gold recipe for about half of the pantries (`visible_rate` 0.50 to 0.53). The other half has more than 2 missing lines or falls outside the 10 shown per group.
- HYPOTHESIS: the `popularity` sampler hurts `overlap` more than `idf_flat` because it draws common ingredients, and IDF gives them little weight. The sampler and the rule share one quantity (document frequency). So read the `overlap` versus `idf_flat` gap for each sampler. Do not read it as one number.
- Not a quality claim: nothing here says a person prefers one list. That needs the hand-judged pairs.

### Sanity check: old recovery results, with the rule beside them

| Old result | Task | Rule beside it |
| --- | --- | --- |
| P3 recall@10 0.980 (learned) vs 0.746 (overlap), RecipeNLG 50k, n=9,354 | Masked recovery, leaks | Audit: a different no-ML rule ("subset, then closeness to 30% missing") scores 0.975 on a 1,404-query set ([report 01](research/2026-10-stage1/01_recommender.md)). The M2 rules on RecipeNLG at 1.27M recipes are written and not yet run (see the Kaggle section below) |
| P1 retrieval recall@10 0.873 | Leave one ingredient out | UNSUPPORTED. No log exists |

The new task differs from the old one (Wikibooks pack, ingredient ids, distractors, a candidate set with no cap). Do not compare the old and new numbers.

### Reproduce

| Table or file | Command |
| --- | --- |
| `results/m2_baseline_wikibooks.json` | `uv run python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json` (about 8 minutes on the laptop, after `uv run python scripts/build_pack.py`) |
| Table block below | `uv run python scripts/eval_tables.py` |
| CI floors | `uv run python scripts/make_floors.py` (only for a reviewed change) |

## Protocol principles

- Fixed held-out splits (seed recorded in [DATASET.md](DATASET.md)).
- Compare against a **named baseline** (published or naive), never in a vacuum.
- Report >1 metric where the task is multi-faceted.
- Guardrail metrics (e.g. dietary validity) gate "good" scores.

## Leaderboards

> **Phase 1 eval provenance:** RecipeNLG, **50,000-recipe sample**, `min_count=5`
> (vocab = 2,067 canonical ingredients), seed=42. Sample-based by design:
> parser eval is fast (~37s) but retrieval leave-one-out is O(N²) on shared
> postings (see [CHALLENGES.md](CHALLENGES.md)), so it runs on the sample, not
> the full 2.23M corpus. Numbers are a baseline to beat in Phase 2+.

### Phase 1 — Ingredient parser
| Metric | Baseline | Current | Target | Run |
| ------ | -------- | ------- | ------ | --- |
| Canonical-match precision | — | 0.860 | — | 50k, 2026-05-31 |
| Canonical-match recall | — | 0.869 | — | 50k, 2026-05-31 |
| **Canonical-match F1** | — | **0.864** | **≥0.85 ✅** | 50k, 2026-05-31 |

_Counts: tp=315,224 fp=51,379 fn=47,456 (micro-averaged over the sample).
Gold = RecipeNLG `NER` column; both gold and prediction canonicalized via the
same `canonicalize()` path._

### Phase 1 — Retrieval baseline
| Metric | Baseline | Current | Run |
| ------ | -------- | ------- | --- |
| **recall@10** (leave-one-ingredient-out) | — | **0.873** | 50k (n=28,183), 2026-05-31 |

_Protocol: for each recipe with ≥2 canonical ingredients, drop one at random
(seed=42), query with the rest, hit if the source recipe is in top-10. Set-overlap
coverage scoring. This is the number Phase 3's learned ranker must beat._

### Phase 2 — Substitution (flagship)

> **Phase 2 eval provenance:** RecipeNLG **28,273-recipe sample**, seed=42,
> `min_overlap=4`. Gold pairs **mined from the same corpus** (near-duplicate
> recipes differing by exactly one ingredient): 116 directed pairs, 82 evaluated
> query keys. Coverage is 100% **by construction** (an artifact of mining from
> the same corpus — not a quality claim). This is the reproducible fallback;
> comparison against the **published GISMo gold set** is implemented via
> `scripts/fetch_gismo_gold.py` — see the "vs GISMo published benchmark" table
> below. Mined-gold numbers here are **NOT directly comparable to published
> food2vec / GISMo results** (different gold, 100%-by-construction coverage).

#### Ablation (n=82 queries)

| Arm | MRR | P@1 | R@1 | P@5 | R@5 | P@10 | R@10 | Run |
| --- | --- | --- | --- | --- | --- | ---- | ---- | --- |
| emb-only (food2vec baseline) | 0.290 | 0.232 | 0.151 | 0.093 | 0.302 | 0.057 | 0.405 | 28k, 2026-05-31 |
| **graph-only (FLAGSHIP) ★** | **0.339** | **0.256** | **0.189** | **0.105** | **0.395** | **0.063** | **0.475** | 28k, 2026-05-31 |
| hybrid (alpha=0.5) | 0.324 | 0.232 | 0.157 | 0.100 | 0.347 | 0.067 | 0.503 | 28k, 2026-05-31 |

★ **Flagship beats baseline:** graph-only MRR 0.339 vs food2vec 0.290 (+17%);
recall@10 0.475 vs 0.405. Hybrid gives best recall@10 (0.503) but lower MRR/P@1.

#### Ablation — full corpus (1,274,290 recipes, vocab 30,481, n=82)

> **Provenance:** full RecipeNLG 2.23M cleaned (1.27M after title-dedup),
> `min_count=5` → vocab 30,481, seed=42. **Same** mined gold (116 pairs / 82
> query keys) as the 28k row, so the arms are comparable **to each other**.
> Absolute numbers are **not** comparable to the 28k row: the candidate space is
> ~15× larger (a strictly harder ranking task). Overlap-shrinkage support guard
> (β=100) is **on** for graph/hybrid. **Re-run 2026-06-05 after the parser
> doubled-token fix** (see [CHALLENGES.md](CHALLENGES.md) — "Reduplicated NER
> artifacts…"); pair_coverage = 1.0.

| Arm | MRR | R@5 | R@10 | Run |
| --- | --- | --- | ---- | --- |
| emb-only (food2vec baseline) | 0.259 | 0.313 | 0.481 | full, 2026-06-05 |
| **graph-only + overlap-shrink (β=100) ★** | **0.289** | 0.344 | 0.466 | full, 2026-06-05 |
| **hybrid (alpha=0.5) + shrink** | **0.317** | **0.434** | **0.532** | full, 2026-06-05 |

★ **Flagship ordering holds at full scale:** graph-only MRR 0.289 > food2vec
0.259; hybrid best (0.317 / R@10 0.532). The support-guard story (the graph's
lead *reverses* without overlap-shrinkage at this scale, then is restored) is
documented in [CHALLENGES.md](CHALLENGES.md) — "Flagship graph advantage reversed
at full-corpus scale". **These numbers supersede the pre-2026-06-05 full-corpus
row (graph 0.176, hybrid 0.201):** that run was on the doubled-token corpus,
where gold pairs keyed on common single-word ingredients ("butter") silently
missed the model and depressed every arm. The parser fix lifted graph-only MRR
**0.176 → 0.289** (eval *validity* was never broken — gold was canonicalized
through the same path — but the absolute scores were artificially low).
**Caveats:** β=100 was tuned on this same 82-pair gold (small n → mild overfit
risk); the flagship win is a **relative** one (graph > emb at the same scale).

#### Dietary guardrail

| Tag | Substitutes tested | Valid % | Run |
| --- | ------------------ | ------- | --- |
| vegan | 45 | **100%** | 2026-05-31 |

_Tag-coverage is 100% only because the curated set uses common, well-tagged
ingredients. Full-vocab coverage is lower — Phase 4 fixes with an ontology._

#### vs GISMo published benchmark (CC BY-NC 4.0)

> **Source:** Fatemi et al., "Learning to Substitute Ingredients in Recipes"
> (arXiv:2302.07960), facebookresearch/gismo. Gold = their `test_comments_subs.pkl`
> (`subs` source→target name pairs), canonicalized into our ingredient space via
> `scripts/fetch_gismo_gold.py`. Their data is **CC BY-NC 4.0** and is **not
> committed** (regenerate locally; the script + derived CSV are gitignored).
> **Coverage caveat:** their Recipe1M vocab ≠ our RecipeNLG 30,481 vocab, so only
> the covered subset is scored — **pair_coverage = 78.5%** (5,359/6,829 pairs;
> n=1,391 query keys); uncovered pairs are skipped, **not** penalized. Numbers are
> **our arms on their gold**, NOT a reproduction of GISMo's own model.

| Arm | MRR | R@5 | R@10 | Coverage | Run |
| --- | --- | --- | ---- | -------- | --- |
| emb-only (food2vec baseline) | 0.057 | 0.038 | 0.064 | 78.5% | gismo, 2026-06-01 |
| graph-only + overlap-shrink (β=100) | 0.076 | 0.050 | 0.077 | 78.5% | gismo, 2026-06-01 |
| **hybrid (alpha=0.5) + shrink ★** | **0.083** | **0.060** | **0.087** | 78.5% | gismo, 2026-06-01 |

★ **Flagship arm-ordering holds on an independent published benchmark:**
graph-only MRR 0.076 > emb-only 0.057 (+34%); hybrid best at 0.083 / R@10 0.087 —
the **same** ranking as our mined gold, now on Recipe1M-sourced pairs we did not
mine. Absolute values sit far below the mined-gold rows because this gold is
independently sourced (no construction-coverage; a strictly harder task) and only
the covered 78.5% is scored. _GISMo's own headline metric is MRR (arXiv:2302.07960
§4); their model's number is read from the paper, **not** reproduced here — this is
arm-vs-their-gold on the covered subset, a "benchmarked against published gold"
claim, not a head-to-head model reproduction._

### Phase 3 — Recommendation & Ranking (learned reranker)

> **Phase 3 eval provenance:** RecipeNLG **50,000-recipe sample**, seed=13
> (eval mask stream = seed+1=14, distinct from train), mask_fraction=0.3,
> candidate_cap=200. **Task = recipe RECOVERY**, not general relevance: mask a
> random 30% of a real recipe's ingredients, treat the rest as the "pantry",
> and rerank the Phase-1 overlap candidate pool to surface that **exact** masked
> recipe (single gold per query). Labels are **held-out** (leave-ingredients-out)
> and never reference the substitution features, so the sub_fill ablation below
> is non-circular. Train/test split by `recipe_id` md5 hash (~80/20). Train =
> 19,667 kept query-groups (20,000 attempted, 333 dropped: gold unreachable in
> pool); eval = 5,000 test queries (4,914 with gold reachable). All arms scored
> against the **same** prebuilt candidate pools (fairness). **NDCG omitted:**
> with a single gold per query it is a monotone transform of MRR — redundant,
> not independent evidence (see design spec 2026-06-02).
>
> **Re-run 2026-06-06 on the parser-fixed corpus** (doubled-token fix, see
> [CHALLENGES.md](CHALLENGES.md)), **uncapped eval = 9,354 queries** (the
> `--max-eval-queries 5000` cap of the original 2026-06-03 run was dropped, so n
> is larger and the estimate more stable). Numbers below supersede the pre-fix
> 50k row.

| Arm | recall@10 | mrr@10 | recall@10\|in_pool | mrr@10\|in_pool | Run |
| --- | --------- | ------ | ------------------ | --------------- | --- |
| **overlap (P1 baseline)** | 0.746 | 0.414 | 0.754 | 0.418 | 50k, 2026-06-06 |
| linear (numpy logistic) | 0.979 | 0.926 | 0.990 | 0.936 | 50k, 2026-06-06 |
| LambdaMART (+sub_fill) | 0.980 | 0.935 | 0.991 | 0.945 | 50k, 2026-06-06 |
| **LambdaMART −sub_fill ★** | **0.980** | **0.935** | **0.991** | **0.945** | 50k, 2026-06-06 |
| _candidate ceiling_ | _0.989_ | — | — | — | _gold-in-pool rate_ |

★ **Learned reranker crushes the P1 overlap baseline:** recall@10 0.746 → 0.980
(+0.234), MRR 0.414 → 0.935 (+0.521) on the identical candidate pools — the core
Phase-3 claim. The **candidate ceiling is 0.989** (fraction of eval queries where
the gold recipe is even present in the 200-candidate pool); the reranker reaches
0.980 of a possible 0.989, i.e. **0.991 recall conditional on the gold being
reachable** — it nearly saturates what the P1 retriever leaves on the table. (The
parser fix lifted every arm slightly — cleaner tokens improve both candidate
coverage and ranking; the pre-fix row was overlap 0.663 / LambdaMART 0.971.)

**sub_fill ablation = NULL.** Injecting Phase-2 substitution knowledge
(`sub_fill_max`/`sub_fill_mean` = best P2 substitute-similarity of a candidate's
missing ingredients to the pantry) does **not** help: LambdaMART −sub
(0.980/0.9349) ≈ LambdaMART +sub (0.980/0.9347) — a ~0.02pt gap, far **within ~1
SE** → no significant effect, and the null **reproduces on the parser-fixed
corpus**. This is an **honest negative result**, reported as-is and **not**
p-hacked positive. Recovery rewards finding
the *exact* masked recipe; substitutability is an orthogonal recommendation-quality
signal — at best noise here, at worst it pulls non-gold-but-substitutable
candidates up. Details + rationale in
[MODEL_CARD_recommender.md](MODEL_CARD_recommender.md).

#### Full corpus (1,274,290 recipes, vocab 30,481, n=5,000 eval)

> ⚠️ **Pre-parser-fix (2026-06-03) — full leaderboard re-eval pending.** These
> numbers are on the doubled-token corpus. The 50k re-run on the fixed corpus
> (above) lifted every arm, so expect these to move up too; the full all-arms
> re-run is RAM-blocked on the dev box and deferred to a freed/fresh machine.
> A **post-fix** full-corpus datapoint for the production arm now exists — see
> "Production training path" below (unbiased 2,000-query slice: ceiling 0.854,
> mrr@10|in_pool 0.9689). The three findings below (ceiling collapse, reranker
> lead grows, sub_fill null) are structural and expected to hold.
>
> **Provenance:** full RecipeNLG 2.23M cleaned (1.27M after title-dedup),
> seed=13, mask_fraction=0.3, candidate_cap=200 — the **same protocol and the
> same first eval queries** as the 50k row (queries iterate the corpus in file
> order and are capped at 20k train / 5k eval, so they are the same recipes; the
> candidate **pool is drawn from the full 1.27M haystack instead of 50k**). So
> the arms are directly comparable to the 50k row: same task, same queries, a
> 25× larger haystack. Run 2026-06-03 (~65 min on i7-8565U; the
> `candidate_pool` vectorization in [CHALLENGES.md](CHALLENGES.md) made this
> feasible — the naive path projected ~23 h).

| Arm | recall@10 | mrr@10 | recall@10\|in_pool | mrr@10\|in_pool | Run |
| --- | --------- | ------ | ------------------ | --------------- | --- |
| **overlap (P1 baseline)** | 0.089 | 0.028 | 0.127 | — | full, 2026-06-03 |
| linear (numpy logistic) | 0.678 | 0.589 | 0.960 | 0.834 | full, 2026-06-03 |
| LambdaMART (+sub_fill) | 0.690 | 0.632 | 0.977 | 0.896 | full, 2026-06-03 |
| **LambdaMART −sub_fill ★** | **0.690** | **0.632** | **0.977** | **0.896** | full, 2026-06-03 |
| _candidate ceiling_ | _0.706_ | — | — | — | _gold-in-pool rate_ |

★ **The scale-up flips the story from "easy task, saturated" to "retrieval is
the bottleneck, and the reranker is what holds the line."** Three findings, all
honest:

1. **The candidate ceiling collapses 0.983 → 0.706.** A fixed 200-candidate pool
   ordered by coverage now contains the gold recipe only 70.6% of the time
   (was 98.3% at 50k): with 25× more recipes competing for 200 slots, the gold
   is crowded out ~30% of the time. **Candidate generation — not ranking — is
   the dominant error source at full scale.** This is the recovery-task analog
   of the Phase-2 graph reversal: small-sample numbers were optimistic.
2. **The learned reranker's lead grows, and it nearly saturates the (lower)
   ceiling.** LambdaMART recall@10 0.690 vs overlap **0.089 = 7.7×** (the 50k gap
   was 1.46×); MRR 0.632 vs 0.028 ≈ **23×**. Conditional on the gold being in the
   pool, LambdaMART reaches **0.977 recall@10 / 0.896 MRR** — i.e. 0.690 of a
   possible 0.706 (**97.7% of ceiling**). The P1 overlap baseline *collapses* at
   scale (even in-pool it ranks the gold top-10 only 12.7% of the time — tiny
   recipes score coverage 1.0 and bury it); the reranker is exactly what
   recovers it. **The core Phase-3 claim strengthens at full corpus.**
3. **sub_fill ablation stays NULL at full scale** — LambdaMART +sub
   (0.690/0.632) ≈ −sub (0.690/0.632), no significant gap, same as the 50k row.
   The honest "P2 substitution features don't help recipe recovery" result
   holds; not an artifact of the small sample.

_The exposed bottleneck — first-stage candidate recall (ceiling 0.706) — is the
natural next retrieval-quality target (larger/learned candidate generation,
e.g. higher cap or ANN over recipe embeddings); the reranker layer is already
near-saturating what the pool surfaces._

#### Production training path + train-query cap (2026-07-03)

> **Correction, 2026-10-30.** No production bundle exists. Nothing ships from this code.
> The bundle on disk holds 3 models and 1,000 recipes. "Saturates" and "~25 minutes" below
> are retracted (see the status table at the top).
>
> **What ships vs what's studied.** The default training entrypoint
> (`scripts/train_recommender.py`) trains **only** `lambdamart-nosub` on the six
> non-substitution features and never loads Phase-2 artifacts; the runtime
> serves it by default. Rationale: the sub_fill ablation is null (above) **and**
> enabling substitution-backed features collapses example-generation throughput
> ~1000× (259 → 0.25 queries/s on the 50k slice — `ContextGraph.neighbors()`
> cold misses dominate). The full three-arm ablation (linear / lambdamart /
> lambdamart-nosub with sub features) stays available behind
> `--experimental-subs` for research runs. The Phase-2 substitution subsystem
> itself is untouched — it is only excluded as a *ranking feature*.

**Capped-sampling bias fix.** Capped runs (`max_train_queries` /
`max_eval_queries`) previously took the **first N recipes in corpus file
order** — a biased-hard prefix (eval ceiling 0.706–0.79; ~21% of attempted
train queries dropped gold-unreachable). Capped selection now iterates recipes
in `md5(seed:recipe_id)` hash order (`query_sim.sample_order`): unbiased,
reproducible, and **nested** — the 10k sample is a true prefix of the 20k
sample, so learning-curve points are comparable. Uncapped runs keep file order,
so all uncapped historical numbers above are unchanged.

**Train-query learning curve** — full 1.27M parser-fixed corpus, production
arm, one fixed 2,000-query hash-sampled eval slice reused across caps, seed=13
(`scripts/recommender_learning_curve.py`):

| Train cap | Kept groups | recall@10 | mrr@10 | mrr@10\|in_pool | Gen time |
| --------- | ----------- | --------- | ------ | --------------- | -------- |
| 10,000 | 8,694 | 0.8485 | 0.8275 | 0.9689 | 14.1 min |
| 20,000 | 17,472 | 0.8485 | 0.8275 | 0.9689 | 29.3 min |

Metrics are **identical to full float precision** at both caps — the
six-feature model saturates at (or below) 10k query-groups; doubling the
training data changes nothing. The training default is therefore
`--max-train-queries 10000` (`0` restores uncapped), making a full-corpus
production training run **~25 minutes** end to end, versus an extrapolated
~25 h for uncapped example generation (which also exceeds the 16 GB dev box).

_Candidate ceiling on this unbiased slice = **0.854** (parser-fixed corpus,
n=2,000) vs 0.706 in the pre-fix file-order table above; the gap conflates the
2026-06-05 parser fix with the sampling-bias fix. The full all-arms re-run on
the fixed corpus is still pending, but the structural findings hold here: the
production reranker recovers **0.9689 mrr@10|in_pool** — near-saturating what
retrieval surfaces — so first-stage candidate recall remains the bottleneck._

### Phase 4 — Nutrition & Dietary

> **Phase 4 eval provenance:** USDA FoodData Central join — **SR Legacy 2018-04**
> (7,793 foods) + **Foundation Foods 2025-04-24** (411 foods) = **8,204-food**
> artifact (`data/processed/usda.json`, gitignored; regenerate via
> `scripts/fetch_usda.py --csv-dir <dir>`). Evaluated over a **5,000-recipe**
> RecipeNLG raw sample (with quantities), **37,472 ingredient lines**, seed=42.
> Run: `uv run python -m pantrychef.eval.nutrition_main --max-rows 5000`.
> **No recipe-level nutrition gold exists** (RecipeNLG has no macro labels and no
> servings field), so this is a **coverage** evaluation, not a recipe-macro
> accuracy one — see the honesty constraint below.

| Metric | Current | Run |
| ------ | ------- | --- |
| **USDA match coverage** | **0.800** | 5k, 2026-06-03 |
| mass coverage | 0.487 | 5k, 2026-06-03 |
| nutrition completeness (≥50% lines mass-resolved) | 0.560 | 5k, 2026-06-03 |
| median unresolved-mass fraction | 0.50 | 5k, 2026-06-03 |
| dietary accuracy (n=10 hand-labeled) | **1.0** | 5k, 2026-06-03 |

_Match coverage was lifted from a **0.736** baseline to **0.800** by curating 34
high-frequency aliases in `data/nutrition/aliases.json` (the tiered matcher:
curated alias → exact normalized full + before-comma head → token-Jaccard at
threshold 0.34; below threshold is a reported gap, never a guess). Mass coverage
is the honest fraction of lines resolved to grams (mass units by fixed factor;
volume via USDA portion gram-weight else per-class density fallback;
count/portion via USDA "each" or curated per-item grams); anything unresolved is
`(None, False)` and counts toward the coverage gap, never imputed as 0._

**Dietary accuracy is a sanity check, not a robust estimate.** n=10 is a
hand-labeled smoke set (`data/nutrition/dietary_labels.json`); 1.0 means the
ontology engine agrees with all 10 labels, **not** that it is 100% accurate at
scale. Expanding the labeled set to ~100 entries is future work.

**Ontology substring-fix (qualitative).** The Phase-2 flat-substring dietary
tagger was **replaced** (not run side-by-side) by a token-leaf-word ontology with
category inheritance (`animal_product` > `meat`/`fish`/`dairy`/`egg`/`honey`).
This fixes the substring class of false positives — concretely **"eggplant" is no
longer tagged as containing "egg"** — plus curated phrase overrides
(worcestershire / fish sauce → `fish`, soy sauce → `gluten`). Because the old
tagger was removed rather than benchmarked alongside, this is reported as a
**qualitative fix**, not an old-vs-new accuracy delta.

**Impute-gate decision: TRIPPED → macro imputer built.** The gate fires because
`median_unresolved_mass` (0.50) is `> 0.20`; `match_coverage` (0.800) is exactly
at the threshold, so it does **not** satisfy `< 0.80`. In response, a gated macro
imputer (`pantrychef/nutrition/impute.py`: HashingVectorizer + Ridge, MAE measured
on held-out matched ingredients) was built and validated at unit level. **Honesty
note:** the imputer is a standalone gated module; wiring its predictions into
`RecipeNutrition` totals at corpus scale is future work — recipe totals **do not
currently use imputed macros**.

**Honesty constraint.** No recipe-level nutrition gold exists, so Phase 4 is
validated via (1) coverage metrics, (2) per-ingredient unit tests, and (3)
aggregation arithmetic tests — **NOT** recipe-macro accuracy. All recipe macros
are **estimates**. There are **no per-serving values** (RecipeNLG has no servings
field). Absent nutrients are reported as `None` (unknown), never `0.0`. **Not for
medical, clinical, or allergen-safety use.**

### Phase 5 — Detection

Not started. Vision is gated in M8 of [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md).

## M2 leaderboard (Wikibooks pack)

These tables come from `results/*.json` on the test split. Do not edit them by hand.

<!-- BEGIN table:m2-wikibooks -->
### sampler=none, d=0

**Table 1. Recovery sanity check (role: sanity, never selects a model). Test split.**

| Arm | recall@10 | MRR@10 | n |
| --- | --- | --- | --- |
| random | 0.0235 | 0.0070 | 4935 |
| overlap | 0.8588 | 0.5519 | 4935 |
| idf_flat | 0.9439 | 0.8011 | 4935 |
| shipped | 0.2549 | 0.0977 | 4935 |

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

**Table 2. Paired comparisons, a minus b. Test split.**

| a | b | Metric | Diff | 95% interval | Holds |
| --- | --- | --- | --- | --- | --- |
| overlap | random | mrr_at_10 | +0.5449 | [0.5276, 0.5624] | HOLDS |
| overlap | random | recall_at_10 | +0.8353 | [0.8199, 0.8507] | HOLDS |
| idf_flat | overlap | mrr_at_10 | +0.2493 | [0.2364, 0.2621] | HOLDS |
| idf_flat | overlap | recall_at_10 | +0.0851 | [0.0746, 0.0958] | HOLDS |
| shipped | idf_flat | mrr_at_10 | -0.7034 | [-0.7202, -0.6863] | HOLDS |
| shipped | idf_flat | recall_at_10 | -0.6890 | [-0.7096, -0.6677] | HOLDS |
| shipped | overlap | mrr_at_10 | -0.4541 | [-0.4740, -0.4344] | HOLDS |
| shipped | overlap | recall_at_10 | -0.6039 | [-0.6280, -0.5797] | HOLDS |

HOLDS means the interval excludes 0. Clusters: 1645.

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

**Table 3. Product metrics. Test split.**

| Metric | Arm | Value | n |
| --- | --- | --- | --- |
| makeable_at_10 | shipped | 0.5040 | 4935 |
| hit_rate | all arms | 0.8740 | 4935 |
| visible_rate | all arms | 0.5299 | 4935 |

makeable_at_10 is high for `shipped` by construction: the shipped order lists recipes you can make now first.

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

### sampler=uniform, d=3

**Table 1. Recovery sanity check (role: sanity, never selects a model). Test split.**

| Arm | recall@10 | MRR@10 | n |
| --- | --- | --- | --- |
| random | 0.0083 | 0.0024 | 4935 |
| overlap | 0.8132 | 0.4879 | 4935 |
| idf_flat | 0.8987 | 0.7193 | 4935 |
| shipped | 0.2020 | 0.0619 | 4935 |

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

**Table 2. Paired comparisons, a minus b. Test split.**

| a | b | Metric | Diff | 95% interval | Holds |
| --- | --- | --- | --- | --- | --- |
| overlap | random | mrr_at_10 | +0.4854 | [0.4688, 0.5029] | HOLDS |
| overlap | random | recall_at_10 | +0.8049 | [0.7887, 0.8215] | HOLDS |
| idf_flat | overlap | mrr_at_10 | +0.2315 | [0.2200, 0.2431] | HOLDS |
| idf_flat | overlap | recall_at_10 | +0.0855 | [0.0748, 0.0963] | HOLDS |
| shipped | idf_flat | mrr_at_10 | -0.6574 | [-0.6747, -0.6400] | HOLDS |
| shipped | idf_flat | recall_at_10 | -0.6967 | [-0.7177, -0.6756] | HOLDS |
| shipped | overlap | mrr_at_10 | -0.4260 | [-0.4449, -0.4077] | HOLDS |
| shipped | overlap | recall_at_10 | -0.6111 | [-0.6359, -0.5864] | HOLDS |

HOLDS means the interval excludes 0. Clusters: 1645.

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

**Table 3. Product metrics. Test split.**

| Metric | Arm | Value | n |
| --- | --- | --- | --- |
| makeable_at_10 | shipped | 0.5779 | 4935 |
| hit_rate | all arms | 0.9303 | 4935 |
| visible_rate | all arms | 0.5242 | 4935 |

makeable_at_10 is high for `shipped` by construction: the shipped order lists recipes you can make now first.

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

### sampler=popularity, d=3

**Table 1. Recovery sanity check (role: sanity, never selects a model). Test split.**

| Arm | recall@10 | MRR@10 | n |
| --- | --- | --- | --- |
| random | 0.0069 | 0.0020 | 4935 |
| overlap | 0.6578 | 0.3410 | 4935 |
| idf_flat | 0.8829 | 0.6945 | 4935 |
| shipped | 0.1246 | 0.0323 | 4935 |

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

**Table 2. Paired comparisons, a minus b. Test split.**

| a | b | Metric | Diff | 95% interval | Holds |
| --- | --- | --- | --- | --- | --- |
| overlap | random | mrr_at_10 | +0.3391 | [0.3229, 0.3554] | HOLDS |
| overlap | random | recall_at_10 | +0.6509 | [0.6310, 0.6707] | HOLDS |
| idf_flat | overlap | mrr_at_10 | +0.3535 | [0.3411, 0.3658] | HOLDS |
| idf_flat | overlap | recall_at_10 | +0.2251 | [0.2099, 0.2407] | HOLDS |
| shipped | idf_flat | mrr_at_10 | -0.6622 | [-0.6793, -0.6457] | HOLDS |
| shipped | idf_flat | recall_at_10 | -0.7583 | [-0.7753, -0.7406] | HOLDS |
| shipped | overlap | mrr_at_10 | -0.3087 | [-0.3260, -0.2916] | HOLDS |
| shipped | overlap | recall_at_10 | -0.5331 | [-0.5583, -0.5076] | HOLDS |

HOLDS means the interval excludes 0. Clusters: 1645.

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

**Table 3. Product metrics. Test split.**

| Metric | Arm | Value | n |
| --- | --- | --- | --- |
| makeable_at_10 | shipped | 0.7229 | 4935 |
| hit_rate | all arms | 0.9761 | 4935 |
| visible_rate | all arms | 0.5147 | 4935 |

makeable_at_10 is high for `shipped` by construction: the shipped order lists recipes you can make now first.

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

### sampler=uniform, d=6

**Table 1. Recovery sanity check (role: sanity, never selects a model). Test split.**

| Arm | recall@10 | MRR@10 | n |
| --- | --- | --- | --- |
| random | 0.0105 | 0.0031 | 4935 |
| overlap | 0.7574 | 0.4295 | 4935 |
| idf_flat | 0.8626 | 0.6564 | 4935 |
| shipped | 0.1645 | 0.0444 | 4935 |

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

**Table 2. Paired comparisons, a minus b. Test split.**

| a | b | Metric | Diff | 95% interval | Holds |
| --- | --- | --- | --- | --- | --- |
| overlap | random | mrr_at_10 | +0.4264 | [0.4097, 0.4435] | HOLDS |
| overlap | random | recall_at_10 | +0.7469 | [0.7289, 0.7651] | HOLDS |
| idf_flat | overlap | mrr_at_10 | +0.2269 | [0.2159, 0.2383] | HOLDS |
| idf_flat | overlap | recall_at_10 | +0.1052 | [0.0940, 0.1165] | HOLDS |
| shipped | idf_flat | mrr_at_10 | -0.6120 | [-0.6295, -0.5944] | HOLDS |
| shipped | idf_flat | recall_at_10 | -0.6981 | [-0.7183, -0.6776] | HOLDS |
| shipped | overlap | mrr_at_10 | -0.3851 | [-0.4038, -0.3673] | HOLDS |
| shipped | overlap | recall_at_10 | -0.5929 | [-0.6178, -0.5678] | HOLDS |

HOLDS means the interval excludes 0. Clusters: 1645.

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

**Table 3. Product metrics. Test split.**

| Metric | Arm | Value | n |
| --- | --- | --- | --- |
| makeable_at_10 | shipped | 0.6431 | 4935 |
| hit_rate | all arms | 0.9574 | 4935 |
| visible_rate | all arms | 0.5187 | 4935 |

makeable_at_10 is high for `shipped` by construction: the shipped order lists recipes you can make now first.

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

### sampler=popularity, d=6

**Table 1. Recovery sanity check (role: sanity, never selects a model). Test split.**

| Arm | recall@10 | MRR@10 | n |
| --- | --- | --- | --- |
| random | 0.0036 | 0.0014 | 4935 |
| overlap | 0.4883 | 0.2215 | 4935 |
| idf_flat | 0.8107 | 0.5966 | 4935 |
| shipped | 0.0671 | 0.0139 | 4935 |

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

**Table 2. Paired comparisons, a minus b. Test split.**

| a | b | Metric | Diff | 95% interval | Holds |
| --- | --- | --- | --- | --- | --- |
| overlap | random | mrr_at_10 | +0.2201 | [0.2064, 0.2339] | HOLDS |
| overlap | random | recall_at_10 | +0.4847 | [0.4636, 0.5056] | HOLDS |
| idf_flat | overlap | mrr_at_10 | +0.3751 | [0.3621, 0.3880] | HOLDS |
| idf_flat | overlap | recall_at_10 | +0.3224 | [0.3058, 0.3394] | HOLDS |
| shipped | idf_flat | mrr_at_10 | -0.5827 | [-0.6004, -0.5653] | HOLDS |
| shipped | idf_flat | recall_at_10 | -0.7437 | [-0.7615, -0.7256] | HOLDS |
| shipped | overlap | mrr_at_10 | -0.2076 | [-0.2218, -0.1934] | HOLDS |
| shipped | overlap | recall_at_10 | -0.4213 | [-0.4458, -0.3966] | HOLDS |

HOLDS means the interval excludes 0. Clusters: 1645.

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*

**Table 3. Product metrics. Test split.**

| Metric | Arm | Value | n |
| --- | --- | --- | --- |
| makeable_at_10 | shipped | 0.8526 | 4935 |
| hit_rate | all arms | 0.9964 | 4935 |
| visible_rate | all arms | 0.4950 | 4935 |

makeable_at_10 is high for `shipped` by construction: the shipped order lists recipes you can make now first.

*Label: MEASURED. Commit: 185ae8c8. Dirty: yes. Results: [m2_baseline_wikibooks.json](../results/m2_baseline_wikibooks.json). Rebuild: `python -m pantrychef.eval.baseline_main --pack build/pack --out results/m2_baseline_wikibooks.json`.*
<!-- END table:m2-wikibooks -->
