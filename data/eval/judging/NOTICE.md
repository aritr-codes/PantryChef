# Notice for the judging pilot sheet

`pilot_sheet.v1.json` holds recipe titles and ingredient lines from the Wikibooks Cookbook
(en.wikibooks.org). The text is available under the
[Creative Commons Attribution-ShareAlike 4.0 licence](https://creativecommons.org/licenses/by-sa/4.0/).
The authors are listed in the page history of each page. A page URL is
`https://en.wikibooks.org/wiki/<title>`.

- Source: MediaWiki API snapshot `snapshot.2026-11-03.jsonl.gz`, made by `scripts/fetch_wikibooks.py`.
  Its sha256 is in `docs/DATASET.md`.
- Changes: markup was removed as the source adapter does it. The words are unchanged. The lines are
  a selection of the missing lines of each recipe.
- `pilot_key_sha256.txt` is MIT. It holds one hash.
