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
- The labels in `labels.dev.v1.json` and `labels.test.v1.json` were written by two models (Claude Sonnet and
  Claude Opus). Each model labelled all 300 lines alone, with `docs/PARSER_GOLD_GUIDE.md` and no parser output.
  The implementer settled the 26 disagreements. They are in `adjudication.v1.json`. No human labelled these
  lines. The labels are MIT, like the rest of the repository.

On 2026-11-05 the owner checked 30 random lines (seed 7) from the 300. 28 were right and 2 were wrong. The
2 were in the dev split. The owner fixed them in `labels.dev.v1.json`: `wb-104638#2` (the name now keeps
"pork-flavored") and `wb-211843#2` (a list of optional sweeteners, no longer a non-ingredient line; the
implementer set `optional` to true by guide rule 7). This is a sample, not a full human pass: 28 of 30 is
93% with a wide interval, so the other 270 lines may hold errors.
