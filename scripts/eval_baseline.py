"""Thin entry: uv run python scripts/eval_baseline.py --pack DIR --out results/NAME.json"""

from pantrychef.eval.baseline_main import main

if __name__ == "__main__":
    raise SystemExit(main())
