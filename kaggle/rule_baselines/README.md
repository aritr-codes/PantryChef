# Kaggle kernel: rule baselines on RecipeNLG (M2, Lane D)

Status: written, NOT run. Nothing here runs before the owner approves
(plan `docs/plans/2026-11-03-m2-eval-baseline.md`, section 7).

## Purpose

Replace the retracted 7.7x full-corpus claim with rule baselines on RecipeNLG at 1.27M
recipes (title-deduplicated). Arms: `random`, `overlap`, `idf_flat` (not shipped: RecipeNLG has
no groups). Metrics: `recall_at_10`, `mrr_at_10` (sanity role, ADR 0005). Paired cluster
bootstrap: `overlap` vs `random`, `idf_flat` vs `overlap`, per sampler and distractor count.
Research only. Nothing ships (ADR 0003).

Task: 20,000 fixed gold recipes (first 20,000 eligible by `sha256(f"42:{recipe_id}")`;
eligible = at least 3 ingredients). Dev/test is a 50/50 cut of that hash order. The result
reports the test half. Mask `m = (n + 2) // 4`. Distractors 0, 3, 6 with `uniform` and
`popularity` samplers. 3 draws per gold. Every arm ranks the exact set of recipes that share
at least one pantry ingredient. Code: `pantrychef/eval/rule_baselines_main.py`.

## Resources (ESTIMATE)

- CPU kernel, internet off, no GPU.
- Cleaning: two passes over the 2.2M-row CSV. The earlier full clean took 31 to 42 minutes
  on the laptop. Expect 1 to 2 hours for both passes.
- Query count: the kernel asks for 6,000 golds (3,000 per split), not 20,000. At 20,000 the
  extrapolated run is 4 to 8 hours, and this project does not start an unmeasured multi-hour job.
  Step 1 is a smoke run with `--n-queries 200`: it measures the real time per pantry at 1.27M
  recipes. Step 2 is the full run, with the count set from that measurement. The owner approves
  both. The plan section 2 (D1) named 20,000 golds. This is a recorded change.
- Scoring at 20,000 golds: 300,000 pantries (20,000 golds x 3 draws x 5 configs). At 6,000 golds:
  90,000 pantries, about a third of the time. A synthetic benchmark of
  300,000 invented recipes (Zipf ingredient use) gave 14 ms per pantry with 140k mean
  candidates. Scaling linearly to 1.27M gives about 60 ms per pantry, so about 5 hours.
  Real postings may be longer. Total ESTIMATE: 4 to 8 hours. Kaggle's CPU limit is 12 hours.
  The kernel logs progress every 500 golds, with no recipe text.
- Peak RAM ESTIMATE, 1.27M recipes, about 9 to 12M ingredient postings (P):
  recipe id strings 90 MB; CSR indptr 10 MB and indices 4P = 48 MB; inverted postings 48 MB;
  build transients (owner array 48 MB, argsort 96 MB, freed after build); idf, den, total
  25 MB; per-pantry transients (bincounts 20 MB, masks, candidate arrays) under 150 MB.
  Run phase about 0.5 GB. The cleaning phase is the larger one: title set about 200 MB,
  vocabulary Counter about 200 MB, pandas chunk of 10k rows. Overall under 2 GB.
  A 16 GB Kaggle CPU kernel is enough with a wide margin. Not measured at 1.27M.

## Inputs

1. Kaggle-hosted RecipeNLG dataset containing `full_dataset.csv`. Slug: TO-CONFIRM.
   The kernel checks its sha256 equals
   `f376ee0bb9f99f323761abf6270d453f4eff2002c3625d04cabcf8b57dca0803` (docs/DATASET.md)
   and stops with exit code 2 otherwise. We never upload RecipeNLG.
2. Private dataset holding the wheel `pantrychef-*.whl` and `commit.txt` (the build commit).
   Slug: TO-CONFIRM.

## Packages the Kaggle image must have

The wheel installs with `--no-deps`. Imports used by the cleaner and the scorer:
`numpy`, `pandas`, `pydantic` (v2) and `pydantic_settings`. The last one is a DESIGN RISK:
`pantrychef.data.loaders` imports `pantrychef.config`, which imports `pydantic_settings`, and
the Kaggle image may lack it. The kernel checks all four imports and stops with a clear
message. Fallback: add offline wheels to the wheel dataset (the kernel installs every
`*.whl` it finds with `--no-index --no-deps`):

```bash
uvx pip download pydantic-settings python-dotenv --no-deps -d dist/
```

Check the versions match the image's pydantic v2 before you upload.

## Outputs

`/kaggle/working/m2_rule_baselines_recipenlg.json` (schema v1, validated by `write_result`)
and `/kaggle/working/manifest.sha256`. Only aggregate numbers. The cleaned corpus is written
to `/tmp`, not `/kaggle/working`, so no recipe text becomes an output. The result `raw`
holds `csv_sha256`, `cleaned_sha256`, `query_ids_sha256`, counts and dev numbers marked
debug only. `corpus_fingerprint` is the CSV sha256. The commit comes from `commit.txt` and
is recorded as caller-supplied (the kernel has no git).

## Failure plan

- Hash mismatch, missing CSV, missing wheel or missing package: the kernel stops, exit 2.
- Out of memory or timeout: halve `--n-queries` (edit `kernel.py`), record the failure
  in the result notes. Do not retry in a loop.
- A number may enter a public doc only when the owner says so.

## Commands (written, NOT run)

Build the wheel from a clean tree at the pinned commit (run from the repo root):

```bash
git status --porcelain            # must print nothing
git rev-parse HEAD > dist/commit.txt
uv build --wheel
```

Create the wheel dataset. Needs a `dataset-metadata.json` in `dist/` with the slug. Known
issue: `uvx kaggle` fails with `ModuleNotFoundError: No module named 'six'`. Workaround:
`uvx --with six kaggle ...`. No token goes in any file here.

```bash
uvx --with six kaggle datasets create -p dist/        # first time
uvx --with six kaggle datasets version -p dist/ -m "wheel at <sha>"   # later
uvx --with six kaggle kernels push -p kaggle/rule_baselines/
uvx --with six kaggle kernels status <user>/pantrychef-rule-baselines
uvx --with six kaggle kernels output <user>/pantrychef-rule-baselines -p out/
(cd out && sha256sum -c manifest.sha256)
```

Then copy only `m2_rule_baselines_recipenlg.json` to `results/` after you check it.

## Local dry run (synthetic data only, not a result)

```bash
uv run pytest tests/eval/test_rule_baselines.py -q
```

The test writes a result on 40 invented recipes and validates it with `load_result`.
Do not point `--corpus` at `data/processed/recipes.jsonl` on this laptop (610 MB, about
1 GB free RAM).
