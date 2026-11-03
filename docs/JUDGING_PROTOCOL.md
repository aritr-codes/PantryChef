# Judging protocol

Status: DRAFT, 2026-11-03. No pilot answer exists yet. This file defines the M2 pilot of 20 pantries.
M4 uses the same protocol on about 100 pantries, if the pilot passes.

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
