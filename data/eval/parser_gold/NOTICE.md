# Notice for the parser gold set

`sheet.v1.json` holds 300 single ingredient lines from the Wikibooks Cookbook (en.wikibooks.org).
The text is available under the
[Creative Commons Attribution-ShareAlike 4.0 licence](https://creativecommons.org/licenses/by-sa/4.0/).
The authors are listed in the page history on Wikibooks. Each record has the page title and the
revision id. The revision link is `https://en.wikibooks.org/w/index.php?oldid=<revision_id>`.

- Source: MediaWiki API snapshot `snapshot.2026-11-03.jsonl.gz`, made by `scripts/fetch_wikibooks.py`.
  The sha256 of the snapshot is in `sheet.v1.json` and in `docs/DATASET.md`.
- Changes: markup was removed as the source adapter does it (links, templates, emphasis). The words are
  unchanged. The lines are a selection.
- The labels in `labels.dev.v1.json` and `labels.test.v1.json` are hand-written by the project owner.
  They are MIT, like the rest of the repository.
