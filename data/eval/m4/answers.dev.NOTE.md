# Dev answers: who made them

The file `answers.dev.v1.csv` is **model-judged**. It is not a human judgement.

- On 2026-11-19 the owner annotated the 329 dev items with another LLM, then reviewed the result.
- The owner described the method like this: the pass treated the pantry plus ordinary staples as available, counted one shopping trip for the missing lines, and scored each recipe for how plausible it is to cook tonight. It used recipe-role weights, an estimated shopping burden, and a weighted aggregation of the five options. Close scores became `tie`. The score margin gave `strength` 1 or 2. Repeated and reversed items were checked for side-consistent outcomes.
- The `judge` column of every row is `judge_model`. The scorer refuses these rows unless `--allow-model-judge` is set, and then every result file says model-judged.
- The `seconds` column is blank. These answers say nothing about human judging time.
- The owner chose to use them as model-labelled data only (2026-11-19). The plan allows model judges for development work and says they never enter training, comparator choice, futility or the test (plan 8.1).

Rules that follow:

- Do not train the pairwise model on these rows.
- Do not choose the IDF rule from them.
- Do not quote them as a human preference.
- The freeze refuses a gate file that is model-judged.

The scoring rule of that pass uses recipe role and shopping burden. Those are close to the model's own features (missing count, mean weight, optional lines). A model trained on these rows would learn that rule. That would be circular, and it is the reason for the rules above.
