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

## Extra lines (M3)

`extra.v1.json` holds 100 more single ingredient lines from the same snapshot (seed 43). They are a
uniform random draw of distinct lines that are not in `sheet.v1.json`, with the same filters as the
sheet (see `scripts/make_m3_extra_lines.py`). The text is available under CC BY-SA 4.0, like the
sheet. The sha256 of the snapshot is in `extra.v1.json`. Each record has the page title and the
revision id, and the revision link is built as above. The extra lines are frozen with the test half
of the sheet: `data/eval/m3_frozen_lines.v1.json` holds the sha256 of each of the 250 lines. The
labels are in `labels.extra.v1.json`, written after M3 Task 1 by two models and settled by the
owner (`adjudication.m3.v1.json`). They are model-labelled and owner-adjudicated.

## Fresh lines (M3 acceptance round 2)

`fresh.v1.json` holds 200 single ingredient lines from the same snapshot (seed 47). The first
acceptance run failed one target, so its test lines are spent. These lines are a new held-out set.
They are a uniform random draw of distinct lines that are in neither `sheet.v1.json` nor
`extra.v1.json` (see `scripts/make_m3_fresh_lines.py`). The text is available under CC BY-SA 4.0, like
the sheet. Each record has the page title and the revision id, and the revision link is built as
above. `data/eval/m3_frozen_lines.v2.json` holds the sha256 of each line. The draw happened before
any table change that followed acceptance run 1. Nobody reads the file until the second run.

## Bare pepper labels (M3 Task 6)

`data/eval/m3_bare_pepper_labels.v1.json` holds 80 single ingredient lines from the same snapshot (seed 45),
each with a label (`black`, `other` or `unclear`). The text is Wikibooks Cookbook text, available under CC BY-SA 4.0
on the same terms as the sheet. The labels are MIT. One model (Claude Opus) labelled the lines blind. The owner
did not adjudicate them. Each record has the page title, the revision id and the revision link, as in the sheet.
`scripts/m3_bare_pepper.py score` reads the file.

## Dev id map (M3 Task 5)

`dev_id_map.v1.json` maps each dev gold name (134 names, 14 with no id) to an ingredient id of the v2 table. One model
(Claude Opus) made it blind from the dev gold names and the table at commit b8a76c7. Nobody edited it by hand. It
is frozen: `scripts/ingredient_coverage.py --id-map` uses it so that a dev score does not move when table keys
move. The labels are MIT.
