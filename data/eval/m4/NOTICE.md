# Notice for the M4 judging sheets

The M4 judging sheets (`sheet.NAME.v1.json`) show recipe titles and ingredient lines from the
Wikibooks Cookbook (en.wikibooks.org). The text is available under the
[Creative Commons Attribution-ShareAlike 4.0 licence](https://creativecommons.org/licenses/by-sa/4.0/).
The authors are listed in the page history of each page. A page URL is
`https://en.wikibooks.org/wiki/<title>`.

- What is shown: a pantry (ingredient names) and, for each list, 5 recipe titles with the
  ingredient lines you still need.
- Source: MediaWiki API snapshot `snapshot.2026-11-03.jsonl.gz`, made by `scripts/fetch_wikibooks.py`.
  Its sha256 is in `docs/DATASET.md`.
- Changes: markup was removed as the source adapter does it. The titles and the words of the lines
  are unchanged. The lines are a selection of the missing lines of each recipe. Each list shows its
  titles in alphabetical order (a formatting change).
- Use: the sheets exist only to evaluate the ranking. Share them under the same licence.
- Commit no sheet until this notice exists.

## Files under the MIT licence

Pantry lists (ingredient ids), the training table, answers and the weights file are MIT.
`key_sha256.NAME.txt` holds one hash each.

## What a key hash proves

A key hash proves that the key file (which arm is left or right for each item) did not change after
you answered. It does not prove that the sheet text is the same. It does not hash the sheet. The
sheet is rebuilt from the same pack and the same pantry file.
