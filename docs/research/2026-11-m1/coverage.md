# M1 ingredient table coverage on the Wikibooks snapshot

Date: 2026-11-03. Label: MEASURED, in-sample.

Command: `uv run python scripts/ingredient_coverage.py data/raw/wikibooks/snapshot.2026-11-03.jsonl.gz --top 40`
Snapshot sha256: `a1a076ab0aee385c4e01cdc904342214dfaa6b01dc35d80d32519ea625c597d2` (3,865 pages).
Table: `data/ingredients/ingredients.csv`, sha256 starts `39a22f85` before the last edit of this note.

## Read this first

- The table was grown in one round from this same snapshot: the 288 hand rows came first,
  then 45 rows (`wikibooks-rule`) for the most common unread phrases. The numbers below
  are therefore **in-sample**. They show cost, not quality. M3 owns held-out measurement.
- "Read" means a table row matched. It does not mean the match is right.
- Hand check (ESTIMATE): I read 90 random lines and their ids. 88 were correct or harmless.
  Two were wrong: "peanut or canola oil" gave the option `peanut` (the nut), and
  "Chicken, vegetable, or beef broth" gave three separate lines. The second case is fixed
  and has a test. Two in 90 gives a wide interval, so treat it as a rough signal only.

## Result

- Table rows: 333
- Recipes with an ingredient list: 3713
- Required lines: 30537; optional lines: 2225
- Required lines read: 28362 (92.9%)
- Recipes with every required line read: 2256 (60.8%)

Top 40 unread phrases (count, phrase). The empty phrase is a line with only a quantity and a unit.

- 253	pepper
- 20	berbere spice blend
- 10	barbecue rub
- 10	scotch bonnet pepper
- 7	nuoc mam
- 6	besan
- 6	chop rub
- 6	cocoyam
- 5	of pepper
- 5	rib rub
- 5	stockfish soaked and cleaned
- 4	seasoning to taste
- 4	dried red chile pepper
- 4	groundnut
- 4	fat
- 4	savory
- 4	
- 4	candlenut
- 4	cornbread crumbled finely
- 4	jeera
- 4	poultry shake
- 4	fresh pepper
- 4	stockfish
- 4	green bean trimmed and cut into bite sized piece
- 4	stockfish soaked
- 3	fat for deep frying
- 3	maida
- 3	green chilly split lengthwise
- 3	seasoning
- 3	dried soybean
- 3	topping
- 3	terasi
- 3	spice
- 3	espagnole sauce
- 3	bechamel sauce
- 3	bagoong alamang
- 3	filling as desired
- 3	salam leave
- 3	dried red chilly
- 3	anise seed

## What this means

- The bare "pepper" rule (D4 in the plan) leaves 253 lines unread. M3 decides it fully.
- About 39% of recipes still have at least one unread required line. They show
  "check this line" and cannot be "make now".
- The shipped acceptance target for table coverage belongs to M3, not M1.
