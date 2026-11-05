# Parser gold labelling guide

This guide tells a labeller how to fill `names`, `optional` and `not_an_ingredient` for each line in
`data/interim/parser_gold_labelling.csv`. The scorer is `pantrychef/eval/parser_gold.py`.

## Rules

1. Read only the `text` column. Do not run the resolver. Do not open the ingredient table. Do not copy
   any program output. The gold must stay independent of the parser it scores.
2. `names` holds what a shopper would buy, in lower case, singular, with no quantity, unit, size,
   preparation word or brand.
   - Drop: numbers, units, "fresh", "chopped", "large", "to taste", "for garnish", "as needed".
   - Keep a word when it changes what the food is: `ground beef`, `brown sugar`, `baking soda`,
     `olive oil`, `soy sauce`, `black pepper`, `cream cheese`.
   - Use the common English name. Keep a foreign name only if the line gives no English one.
3. A line with two foods joined by "and" or a comma list that means separate items is two groups.
   Separate groups with `;`. Example: `salt and pepper` becomes `salt;black pepper`.
4. A line with a real choice ("A or B", "A (B may be substituted)", "A, or similar") is one group.
   Separate the alternatives with `|`. Example: `1 cup bulgur or cracked wheat` becomes
   `bulgur|cracked wheat`.
5. A line with a compound food (`bouquet-garni (parsley, thyme, bay leaf)`) is one group named by the
   head noun, here `bouquet garni`. Do not list the contents.
6. A line that names no food (a heading, a note, "Equipment", "For the sauce:") is
   `not_an_ingredient=1` and `names` stays empty.
7. `optional` is 1 only when the line says so: "optional", "if desired", "if you like", "if available".
   "To taste", "as needed" and "for garnish" are 0.
8. A water line ("water", "1 cup warm water") is an ingredient. Name it `water`.
9. When a line is truly unclear, choose the most natural reading. Do not leave `names` blank.
10. One row per line. Keep the `id` and `text` columns unchanged.
