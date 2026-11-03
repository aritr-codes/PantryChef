# Notice for Wikibooks fixtures

The files in this folder hold text from the Wikibooks Cookbook (en.wikibooks.org).
The text is available under the
[Creative Commons Attribution-ShareAlike 4.0 licence](https://creativecommons.org/licenses/by-sa/4.0/).
The authors are listed in each page history on Wikibooks.

- `pages.json` holds whole wikitext pages, copied without change. Each record has the page
  id, title, revision id and timestamp. The page URL is
  `https://en.wikibooks.org/wiki/<title>`, and the revision is
  `https://en.wikibooks.org/w/index.php?oldid=<revision_id>`.
- `lines.json` (if present) holds single ingredient lines copied from the same snapshot.

Source: MediaWiki API snapshot made by `scripts/fetch_wikibooks.py` on 2026-11-03.
Changes: none to the text. The records are selected pages and lines.
