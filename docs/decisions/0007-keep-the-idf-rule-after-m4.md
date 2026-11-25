# 0007. Keep the IDF rule after M4

- **Status:** Accepted
- **Date:** 2026-11-25
- **Deciders:** Project owner, Tech Lead

## Context

M4 asked one question. Does a small learned ranking model pick 5 recipes that the owner
prefers to the 5 of the shipped order? [ADR 0005](0005-honest-claims-and-eval-reset.md)
sets the ship rule. A learned ranker ships only if the paired 95% interval of its gain
over the IDF rule excludes zero on hand-judged test pantries. IDF means inverse document
frequency. The "shipped order" is the engine order today: make-now recipes, then one-away,
then two-away. Inside a group the engine sorts by score, then total lines, then id.

The plan is `docs/plans/2026-11-18-m4-search-ranking.md`, with three amendments. The tools
and the judging protocol are in `docs/JUDGING_PROTOCOL.md`.

This ADR also records a reading of [ADR 0002](0002-no-llm-substitution.md). The model was
trained on labels that an LLM made offline, once. No LLM runs when the app runs. The
owner has not confirmed this reading. It does not matter for the outcome here, because
the model does not ship. A future ranker trained on LLM labels needs the owner to confirm
it first.

## Options considered

1. **Ship the model after the human test.** This was the plan. The test did not run.
2. **Keep the IDF rule and record the evidence (chosen).**
3. **Override the stop and run the human test anyway.** The owner could have asked for
   this. It needs a new amendment after the result is known. The owner did not choose it.

## Decision

The shipped order stays. The model does not ship. The product, the engine, the
browser code and the pack do not change.

The ship rule was not met. The model never reached the human test. Futility check 2
said STOP (below). The "Best for tonight" view was not decided, because the freeze never
came.

### Evidence

All numbers link to a results file. Labels: MEASURED means computed by the code from the
named file. HYPOTHESIS means a reading that no test has checked.

**Human timing pilot** (the owner, 28 usable items, one session;
`results/m4_timing_pilot.json`, MEASURED; the file records a dirty tree: `data/eval/m4/pantries.v1.json` and `m4_pools.py` had uncommitted changes when it was written). Median 30 seconds per item. The plan assumed 75.
Tie rate 3.6%. All 4 repeats were consistent. All four protocol checks passed.

**Dev labels are model-made.** The owner labelled the dev items with another LLM and
reviewed the result (`data/eval/m4/answers.dev.v1.csv`, column `judge = judge_model`;
note in `data/eval/m4/answers.dev.NOTE.md`). Of 329 rows, 140 are ties, 99 are A and 90 are
B. The owner did not judge them by hand. Plan Amendment 2 allowed training on them and
marks every file as model-judged.

**Dev comparison of the three order rules** (model-judged, a dry run that never selects;
`results/m4_dev_pairs.json`, MEASURED; the file records a dirty tree: the M4 code and docs had uncommitted changes when it was written, and the labels did not change). The table shows the win rate among decided items,
with the exact Clopper-Pearson 95% interval.

| Pair | Wins | Losses | Ties | Win rate | 95% interval |
| --- | --- | --- | --- | --- | --- |
| `idf_flat` over shipped | 42 | 20 | 37 | 0.677 | 0.547 to 0.791 |
| `overlap` over shipped | 38 | 24 | 38 | 0.613 | 0.481 to 0.734 |

`idf_flat` is the same score without the "fewest missing lines first" key. Only hand
judgments may choose it (plan 4.3). So the comparator stayed `shipped`.
HYPOTHESIS for a later study: a person may prefer `idf_flat` to the shipped order. No
person has judged this. It is a separate owner decision for a later milestone.

**Model and cross-validation** (`web/src/rank_model.v1.json`, `results/m4_cv.json`,
ESTIMATE, on the model-made labels; the results file carries that label). The model is a pairwise linear model with 8 features,
an L2 penalty and nested cross-validation grouped by pantry. The one-standard-error rule
chose feature set F3 and C = 0.01. Held-out log-loss was 0.655 against 0.693 for chance.
Held-out accuracy was 0.655 on 171 decided items. Futility check 1 passed. The
simplest feature set (F1) had a log-loss of 0.674. So the model learned a weak signal of
the labels. It does not show what the owner prefers.

**The weights lean toward more missing lines** (`web/src/rank_model.v1.json`, MEASURED).
These weights are positive: `missing` +0.049, `miss_frac` +0.110, `unread_missing`
+0.298 and `optional_c` +0.568. The plan treats all four as costs. Nobody tuned the weights
by hand. HYPOTHESIS for the cause: the LLM labelling rule scores recipe role and shopping
effort, so the model copies that rule and not an owner preference.

**Futility check 2** (`results/m4_futility.json`, MEASURED, model-judged under plan
Amendment 3). A separate Opus agent judged the 20 spare dev pantries, model against the
shipped order. It gave 10 wins, 10 losses and 0 ties. The win rate is 0.5, with a 95%
interval of 0.272 to 0.728. The pre-registered rule stops the test when wins are no more
than losses. 10 is no more than 10, so the result is STOP. The owner accepted the stop on
2026-11-25.

### What the result means

- The result is a null with weak evidence. It is not proof that the shipped order is
  better for people. No person has judged a model list. The preference of the owner for
  the model is unknown.
- A tied 10 to 10 on 20 items has a wide interval. At a true win rate of 0.65 the rule
  would still stop about 12% of the time (ESTIMATE, plan review R3, for a human judge;
  a model judge may differ).
- The check was weakened on purpose by Amendment 3, which let a model judge it. See the
  deviations.

### Deviations from the plan

Each one is in the plan file.

1. **Amendment 1.** The dev pool grew from 60 to 100 pantries.
2. **Amendment 2.** The owner labelled the dev items with an LLM. The model trained on
   those labels. The comparator became `shipped`. Futility and test stayed human.
3. **Amendment 3 (2026-11-25).** A model judged futility check 2. It replaces the
   human check that Amendment 2 required. The judge could read a protocol file that names the arms and says a `shipped`
   list holds about 4 make-now recipes. The agent says it did not use it. Nobody can check
   that claim. The sheet had no repeats and no timing. The planned measure of the human tie
   rate of a model-against-rule item is lost. The code now refuses a futility result that
   skipped the commit-order check.
4. **The test was not run.** The freeze, the test sheet and the test scoring exist in
   code and tests, but no real freeze file was written.

## Consequences

- Positive: the public order has no unproven model in it. Every published number
  links to a results file. The tools, tests and protocol stay for a new try. A pinned
  ordering test now guards the shipped order (`tests/golden/rank_pinned.json`,
  `tests/test_rank_pinned.py`, `web/tests/rank-pinned.test.ts`).
- Negative / accepted: about 330 dev items and a trained model gave no ship result. The
  owner's preference between the shipped order and any model stays unmeasured.
- Revisit when: a person (not a model) labels at least 100 dev pantries, or the owner
  wants to test `idf_flat` against the shipped order with the existing sheet tools. A
  new study needs new test pantries and a new freeze. The 1,622 test pantries in
  `data/eval/m4/pantries.v1.json` were never judged and stay unused.
