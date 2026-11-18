# Judging protocol

Status: 2026-11-18. The M4 protocol (section "M4 protocol" below) is the live one. The owner approved the M4 rubric on 2026-11-18, and it is now fixed. Nothing in it is MEASURED yet. The older sections are the M2 pilot and are historical. The M2 pilot of 20 pantries ran with two model judges (Sonnet and Opus), each in two sessions. See [results/m2_judging_pilot.json](../results/m2_judging_pilot.json). A model judge cannot time itself, so check 3 (time) was untested there.

**M2 pilot sections (historical).** Everything from "Source" to "Licence note" describes the M2 pilot. Where the M4 section differs, the M4 section wins.

Source: [plan](plans/2026-11-03-m2-eval-baseline.md), decision D3, Task 7.
Rules: [ADR 0005](decisions/0005-honest-claims-and-eval-reset.md). Labels: MEASURED, ESTIMATE, HYPOTHESIS.

## Purpose

The masked-recovery metrics are a sanity check. They leak the answer (ADR 0005). They cannot choose a model.
A person must judge the lists. This protocol collects that judgement. The judgement uses no model feature, so it may select a model in M4.

The pilot compares two arms:

- `shipped`: the order the product shows (make-now first, then by IDF score). IDF means inverse document frequency.
- `overlap`: the no-ML rule. It ranks by the number of lines you have, then by fewer lines in total.

The judge never sees these names.

## What the judge sees

One item shows:

1. A pantry. It is a list of ingredient names. It is built from a real test-split recipe with about a quarter of its lines removed, plus 3 popular extra ingredients.
2. A left list and a right list. Each list has 5 recipe titles. Under each title, the lines you still need to buy.

Each list is the top 5 of one arm. Which arm is left is random.

## Rubric

Write this text down before you see any pair. Do not change it after you see a pair.

> Imagine you own exactly these ingredients, plus the usual staples (salt, oil, water and similar).
> You may make one trip to the shop for the missing lines shown under a title.
> Which list gives you the better choice for tonight?
> A list is better when it holds a dish you would actually cook and eat tonight, and the trip is short.
> Choose A (left list), B (right list), or tie. Choose tie only when you cannot prefer one list.
> Then answer, for each list: "Would I cook any dish from this list tonight?" yes or no.

Do not judge the taste of a recipe in general. Judge the list for this pantry.

## Blinding steps

1. The script `scripts/judging_sheet.py` builds the sheet. The sheet has item ids, pantries, titles and missing lines. It has no arm name, no gold recipe id and no repeat marker.
2. The script draws one pantry for each of 20 different test-split recipes. The draw uses a fixed seed (42) and the hash order of the recipe ids.
3. The script skips a pantry when both top-5 lists are identical. You cannot compare identical lists, so they carry no information. The script also skips a pantry when a list has fewer than 5 recipes.
4. For each item, a seeded random draw puts `shipped` on the left or on the right.
5. The script repeats 4 of the 20 pantries. A repeat has the same pantry. Its sides are drawn again, so they may swap. A repeat sits at least 3 places from its original. Nothing marks it.
6. The script shuffles all 24 items.
7. The script writes the arm for each side into a private key file, `data/interim/judging_key.pilot.v1.json`. Git ignores that folder.
8. The script writes the sha256 of the key into `data/eval/judging/pilot_key_sha256.txt`. We commit that file. The script refuses to write a different key later. This shows the key did not change after you answered.
9. Do not open the key file until you finish both sessions.

Generate the sheet:

```bash
uv run python scripts/judging_sheet.py --pack build/pack
```

## How to answer

Copy the item ids into a CSV file with these columns:

| Column | Values |
| --- | --- |
| `item_id` | for example `item07` |
| `choice` | `A` (left list), `B` (right list) or `tie` |
| `would_cook_left` | `yes` or `no` |
| `would_cook_right` | `yes` or `no` |
| `seconds` | time you spent on the item |

Work in two sessions on two different days. Do items 1 to 12 in session one and items 13 to 24 in session two. Do not look back at earlier answers.

Score the answers:

```bash
uv run python scripts/judging_score.py --answers PATH/answers.csv
```

The scorer reads the key. It prints these numbers for the 20 base items (a repeat never counts twice in a rate):

- Win rate of `shipped` against `overlap`. It is shown with ties excluded and with each tie as half a win.
- Tie rate.
- Share of lists where you would cook something, for each arm.
- Self-consistency: for the 4 repeats, how many times you gave the same outcome (the same winning arm, or tie both times).
- Median seconds over all 24 items.
- The power estimate below.

## Stop rules

All four checks must pass before the 100-pantry set in M4.

| # | Check | Pass when |
| --- | --- | --- |
| 1 | Self-consistency | at least 3 of the 4 repeats give the same outcome |
| 2 | Discrimination | tie rate is 60% or lower |
| 3 | Cost | median time is below 90 seconds |
| 4 | Power | the scorer prints the estimate, and we write it down |

If a check fails, fix the protocol (list length or rubric wording) and pilot 10 more pantries. Do not go on to M4 after a failed pilot.

With only 4 repeats, check 1 is weak. A judge who answers at random still passes it sometimes. Read it as a warning sign, not as proof.

## Power estimate (ESTIMATE)

The goal is a 95% interval of width 0.2 on the win rate, so the half-width is h = 0.1.
The scorer uses the normal approximation.

```text
n_non_tie = ceil( z^2 * p * (1 - p) / h^2 )     z = 1.96, h = 0.1
pantries  = ceil( n_non_tie / (1 - tie_rate) )
```

`p` is the pilot win rate with ties excluded. `tie_rate` is the pilot tie rate.
Ties give no information about the win rate, so we need more pantries when ties are common.

Example by hand: p = 1/3 and tie_rate = 0.25 give n_non_tie = ceil(3.8416 * 0.2222 / 0.01) = ceil(85.4) = 86, and pantries = ceil(86 / 0.75) = 115.

The scorer also prints a worst case at p = 0.5, because p from 20 pantries is noisy: n_non_tie = ceil(96.04) = 97.
Treat both values as an ESTIMATE. The normal approximation is rough at small n, and one judge's pantries are not independent draws of a population.

## Bias limits for one judge

One judge cannot remove taste bias. The judge has one taste, one cooking skill and one kitchen. The result says which list this one person prefers. It does not say which list people prefer.

The protocol limits the other biases:

- **Hidden arms.** The sheet has no arm name.
- **Shuffled sides.** Left and right are random, so a habit of choosing the left list does not favour an arm.
- **Repeats.** 4 unmarked repeats measure how often you contradict yourself.
- **Two sessions on two days.** A mood on one day does not decide the whole set.
- **Rubric before pairs.** You write the rubric first. You cannot tune it to a result you saw.

Open limits:

- A recipe title may reveal an arm by style. The sheet does not hide this.
- Both lists use the same candidate set: recipes with at most 2 missing lines. A first draft used all recipes. Then the `overlap` list showed recipes with 2 to 36 missing lines and the `shipped` list showed 0 to 2, so the judge could name the arm on every item (found by the branch review). With the same set, only the order differs. A judge may still guess the arm from the order. The key stays closed, but a guess may colour the answers.
- The pilot has 20 pantries. Its intervals are wide. We report the interval with the rate.
- A second judge, such as one friend, may help in M4. That is a HYPOTHESIS. We do not claim it until we measure agreement.

## Licence note

The sheet shows recipe titles and ingredient lines from the Wikibooks Cookbook (CC BY-SA 4.0).
Do not commit the sheet until the licence notice for it exists (plan risk R7). The sheet is rebuilt from the same pack with the command above. The committed key hash shows that the draw and the sides did not change. It does not hash the sheet text.

## M4 protocol

Source: [M4 plan](plans/2026-11-18-m4-search-ranking.md), sections 6, 8 and 9. The plan wins if this text and the plan differ.
Labels: MEASURED, ESTIMATE, HYPOTHESIS. A number here is MEASURED only when the plan says so.

### Purpose and judge

M4 asks one question. Does a learned ranker (the model) pick 5 recipes that the owner prefers to the 5 of the IDF rule? IDF means inverse document frequency.

- One person judges: the owner. The claim is one person's preference. It is not what people prefer.
- Model judges may dry-run the tools. Their answers carry the label `judge_model` and the metric `pilot_pairwise_win_rate` (role `sanity`).
- Model-judge answers never enter training, comparator choice, futility checks or the test.

### What the judge sees

One item shows a pantry and two lists. Each list has 5 recipe titles. Under each title, the lines you still need to buy.

- Each list shows its titles in neutral order: by title (case-folded), then by recipe id. The arm decides which 5 recipes are in the list. The arm never decides their order.
- Left and right are random. No sheet shows an arm name.
- Each dev pantry gives 3 items (the 3 pairs of the 3 dev systems). The 3 items sit at least 3 places apart.
- The script skips a pair when the two lists hold the same 5 recipes. Some pantries therefore give fewer than 3 items.
- A repeat is the same item shown again. Nothing marks it.

### Rubric (approved by the owner on 2026-11-18)

The owner approved this text on 2026-11-18, before the first pair. Nobody changes it after that. If you change it, the pilot starts again.

> Imagine you own exactly these ingredients, plus the usual staples (salt, oil, water and similar).
> You may make one trip to the shop for the missing lines shown under a title.
> Which list gives you the better choice for tonight?
> A list is better when it holds a dish you would actually cook and eat tonight, and the trip is short.
> Do not judge a recipe in general. Judge the list for this pantry.
> Choose A (left list), B (right list), or tie. Choose tie only when you cannot prefer one list.
> If you chose A or B, give a strength: 1 means a slight preference. 2 means a clear preference. For a tie, leave strength blank.
> Then answer for each list: "Would I cook any dish from this list tonight?" yes or no.
> Test sheets only: "Which list do you think the new model made?" left, right or unsure.

Read the rubric again at the start of each session.

### Answer file

Copy the item ids into a CSV file. The template that `scripts/judging_sheet.py` writes has these columns, in this order:

| Column | Values |
| --- | --- |
| `item_id` | for example `item07` |
| `choice` | `A` (left list), `B` (right list) or `tie` |
| `strength` | `1` or `2`. Blank for a tie. A strength on a tie fails the scorer |
| `would_cook_left` | `yes` or `no` |
| `would_cook_right` | `yes` or `no` |
| `seconds` | time you spent on the item |
| `session` | any label, for example `dev3` |
| `arm_guess` | test sheets only: `left`, `right` or `unsure` |

The sheet writes the template to `data/interim/answers_template.m4-NAME.csv`. Commit the answers as `data/eval/m4/answers.NAME.v1.csv`.

To answer without typing a CSV, make the judging page: `uv run python scripts/judging_page.py --sheet data/eval/m4/sheet.NAME.v1.json --session N` (add `--arm-guess` for a test sheet). The script writes one local HTML file under `data/interim/`. Open it with a double-click. The page works offline and holds no key data. It shows one item at a time, times each item while the tab is visible (the Pause button stops the clock), saves each answer in the browser and downloads `answers.NAME.sessionN.csv` with the columns above. The `seconds` column is the on-screen time in whole seconds, 1 or more. Merge the session files by hand into the answers file.

### Session rules

- A session lasts at most 45 minutes.
- Sessions run on different days.
- Test sessions start at least 2 days after the last dev session.
- The test needs at least 4 sessions (110 items at about 80 s is about 147 minutes, ESTIMATE).
- Do not look back at earlier answers.

### Keep-blind rule

Until the test answers are committed, do not open these files:

- `data/interim/judging_key.m4-*.json`
- `results/m4_dev_pairs.json`
- `results/m4_cv.json`
- `results/m4_futility.json`
- `data/eval/m4/train_table.v1.json`
- `web/src/rank_model.v1.json`

The lead tells you only "go" or "stop" after each gate. The lead commits these files. Do not read their diffs.

### Timing pilot: four checks

The pilot has 10 dev pantries with 3 items each, plus 4 unmarked repeats: 34 items, one session. The owner judges. A model cannot time itself.

| # | Check | Pass when |
| --- | --- | --- |
| 1 | Self-consistency | at least 3 of the 4 repeats give the same outcome |
| 2 | Discrimination | tie rate is 60% or lower |
| 3 | Cost | median time is below 90 seconds |
| 4 | Power | the scorer prints the exact power table for the observed tie rate, and we write it down |

- Pass: all four checks pass. If the rubric and the list length did not change, the 10 pilot pantries join dev.
- Fail: change the rubric or the list length. Then pilot the 10 reserve pantries. The failed pilot answers never join dev. Do not go on to dev judging after a failed pilot.
- With 4 repeats, check 1 is weak. A judge who answers at random still passes it sometimes. Read it as a warning sign.

### Power method (ESTIMATE)

- Method: exact binomial. Count decided items only. Drop ties.
- Interval: Clopper-Pearson (CP), two-sided 95%, on the win rate `p = W / (W + L)`.
- The test passes when the CP lower bound is above 0.5. This equals a one-sided exact binomial `p <= 0.025`.
- Power uses a random number of decided items, `Binomial(n, 1 - tie_rate)`. You cannot know the tie count in advance.
- The M2 normal approximation (section "Power estimate" above) is historical. Do not use it for M4.

Table copied from plan section 6. Every row is an ESTIMATE. The tie rates (0 and 0.25) come from the M2 model-judge pilot, so they are guesses for a person. MDW means minimum detectable win rate at 80% power, rounded up to the next 0.005.

| Test pantries | Tie rate | Wins needed (at expected decided) | Power at true 0.65 | 0.70 | 0.75 | MDW (80%) |
| --- | --- | --- | --- | --- | --- | --- |
| 40 | 0 | 27/40 | 0.44 | 0.70 | 0.90 | 0.725 |
| 40 | 0.25 | 21/30 | 0.30 | 0.52 | 0.75 | 0.765 |
| 40 | 0.40 | 18/24 | 0.24 | 0.42 | 0.64 | 0.795 |
| 60 | 0.25 | 30/45 | 0.47 | 0.74 | 0.92 | 0.715 |
| 80 | 0.25 | 39/60 | 0.60 | 0.86 | 0.98 | 0.685 |
| 100 (decided) | 0 | 61/100 | 0.83 | 0.98 | 1.00 | 0.650 |
| 100 (decided) | 0.25 | 47/75 | 0.71 | 0.93 | 0.99 | 0.670 |
| 100 (decided) | 0.40 | 39/60 | 0.60 | 0.86 | 0.98 | 0.690 |

Plain statement: 40 test pantries could not show a win rate below about 0.73 to 0.80. With ties, only about 24 to 40 items decide the result. That is too few to separate a moderate gain from chance. The plan uses 100 test pantries, which detect a true win rate of 0.65 to 0.69. Below about 0.65, a null result means "no gain of that size". It does not mean "no gain".

### Bias limits

- One judge. The result says what this person prefers. It does not say what people prefer.
- Neutral order hides the order of the lists. It does not hide how many make-now recipes a list holds. A `shipped` list holds about 4 make-now recipes on average (`overlap` 0.84, `idf_flat` 1.31, MEASURED by the plan reviewer on 1,685 dev pantries). You can see "nothing to buy" under most titles. The blinding is reduced, not removed.
- The test judges which 5 recipes the model picks. It does not judge their order. A passed test supports the model's top-5 set. It says nothing about the order inside the top 5.
- Arm guess: each test item asks which list the model made. We report guess accuracy with a CP interval, the share of `unsure`, and the model win rate among right, wrong and `unsure` guesses. If accuracy is high and the win rate differs by guess, we say the blinding was weak. The ship rule does not change.
- The owner built the product and may recognise its style.
- A second judge is not in use. Agreement with a second judge is a HYPOTHESIS until measured.

### Commands, in order

Run from the repo root. `planned` means the command is not in the code yet. Check before you run.

1. `uv run python scripts/m4_rank.py pantries` builds the committed pantry pools.
2. `uv run python scripts/m4_rank.py variants` runs the label-free IDF variants.
3. Pilot sheet: `uv run python scripts/judging_sheet.py --pantries data/eval/m4/pantries.v1.json --pool pilot --take 10 --repeats 4 --name pilot`. Check the arm flags against the plan.
4. Judge the pilot. Then score it: `uv run python scripts/m4_rank.py pilot-score` (planned). Until then, use `uv run python scripts/judging_score.py --answers PATH --key data/interim/judging_key.m4-pilot.v1.json`.
5. Dev sheet: as step 3, with `--pool dev --take 60 --repeats 18 --name dev`. Judge it in sessions.
6. `uv run python scripts/m4_rank.py dev-score` scores the dev answers.
7. `uv run python scripts/m4_rank.py train` trains the model on dev answers.
8. Futility sheet (`--pool futility --take 20 --model web/src/rank_model.v1.json --name futility`), then `uv run python scripts/m4_rank.py futility`.
9. `uv run python scripts/m4_rank.py freeze` writes `data/eval/m4/freeze.v1.json`. The lead commits it with a clean tree.
10. Test sheet: `--pool test --take 100 --arm-guess --probes 4 --repeats 6 --model web/src/rank_model.v1.json --name test`. The script refuses without the committed freeze.
11. Judge the test in at least 4 sessions. Then run `uv run python scripts/m4_rank.py score`.

All commands except `pilot-score` exist in the scripts today. That does not show that each step works end to end. Tests must show it.

### Licence note (M4)

Each M4 sheet shows recipe titles and ingredient lines from the Wikibooks Cookbook (CC BY-SA 4.0). Do not commit a sheet until [data/eval/m4/NOTICE.md](../data/eval/m4/NOTICE.md) exists. The key hashes show that the sides did not change. They do not hash the sheet text.
