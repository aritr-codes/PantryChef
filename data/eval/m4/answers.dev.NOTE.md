# Dev answers: who made them

The file `answers.dev.v1.csv` is **model-judged**. It is not a human judgement.

- On 2026-11-19 the owner annotated the 329 dev items with another LLM, then reviewed the result.
- The owner described the method like this: the pass treated the pantry plus ordinary staples as available, counted one shopping trip for the missing lines, and scored each recipe for how plausible it is to cook tonight. It used recipe-role weights, an estimated shopping burden, and a weighted aggregation of the five options. Close scores became `tie`. The score margin gave `strength` 1 or 2. Repeated and reversed items were checked for side-consistent outcomes.
- The `judge` column of every row is `judge_model`. The scorer refuses these rows unless `--allow-model-judge` is set, and then every result file says model-judged.
- The `seconds` column is blank. These answers say nothing about human judging time.
- The owner chose to use them as model-labelled data (2026-11-19). Amendment 2 of the plan (section 20) allows this. Before Amendment 2, plan 8.1 kept model judges out of training. Amendment 2 replaced that rule for training only.

Rules that follow (Amendment 2):

- Training on these rows is allowed. The `train` command needs `--allow-model-labels`. The flag `--allow-model-judge` is not enough. Every file that comes from the training says `training_labels: model_judged`: the weights, the training table, `results/m4_cv.json` and the freeze.
- The comparator is `shipped`. `dev-score` records `comparator_source: default (dev answers are model-judged)`. Do not choose the IDF rule from these rows.
- The futility check and the test must be human. The commands refuse model-judged futility and test answers. The freeze refuses a model-judged futility or test file.
- Do not quote these rows as a human preference.

The scoring rule of that pass uses recipe role and shopping burden. Those are close to the model's own features (missing count, mean weight, optional lines). The model may learn the LLM rule and nothing else. The human futility check and the human test decide whether the owner prefers that rule.
