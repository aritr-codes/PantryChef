"""Kaggle kernel for the M2 rule baselines. THIN: all logic lives in pantrychef.eval.

Internet off. No token. Reads only inputs mounted under /kaggle/input. Prints no recipe text.
It never uploads RecipeNLG: the CSV is the Kaggle-hosted copy mounted as an input.
Steps: check CSV hash, install wheel(s) offline, clean, run, write results and manifest.sha256.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

INPUT = Path("/kaggle/input")
WORKING = Path("/kaggle/working")
CLEANED = Path(
    "/tmp/recipes.cleaned.jsonl"
)  # outside /kaggle/working: recipe text is never an output
EXPECTED_CSV_SHA256 = "f376ee0bb9f99f323761abf6270d453f4eff2002c3625d04cabcf8b57dca0803"
N_QUERIES = os.environ.get("PC_N_QUERIES", "6000")  # smoke run: set to 200 first (README)
RESULT = WORKING / "m2_rule_baselines_recipenlg.json"


def die(msg: str) -> None:
    print(f"STOP: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(2)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1 << 24):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    csvs = sorted(INPUT.rglob("full_dataset.csv"))
    if not csvs:
        die("full_dataset.csv not found under /kaggle/input. Attach the hosted RecipeNLG dataset.")
    csv_sha = sha256_file(csvs[0])
    print(f"csv sha256 {csv_sha}", flush=True)
    if csv_sha != EXPECTED_CSV_SHA256:
        die(f"csv sha256 differs from the expected {EXPECTED_CSV_SHA256}. Not running.")

    wheels = sorted(INPUT.rglob("*.whl"))
    commits = sorted(INPUT.rglob("commit.txt"))
    if not any(w.name.startswith("pantrychef-") for w in wheels):
        die("pantrychef wheel not found under /kaggle/input.")
    if not commits:
        die("commit.txt (git rev-parse HEAD at build time) not found next to the wheel.")
    lines = commits[0].read_text().split()
    if len(lines) != 2 or lines[1] not in ("clean", "dirty"):
        die("commit.txt must hold two words: the commit and clean|dirty (see README).")
    commit, tree = lines
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--no-index", "--quiet",
         *map(str, wheels)],
        check=True,
    )  # fmt: skip

    missing = []
    for mod in ("numpy", "pandas", "pydantic", "pydantic_settings"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        die(f"missing packages {missing}: add their wheels to the wheel dataset (see README).")

    from pantrychef.eval import rule_baselines_main as rb

    WORKING.mkdir(parents=True, exist_ok=True)
    n = rb.clean_csv(csvs[0], CLEANED)
    print(f"cleaned {n} recipes", flush=True)
    rb.main(["--corpus", str(CLEANED), "--out", str(RESULT), "--csv-sha256", csv_sha,
             "--commit", commit, "--tree", tree, "--n-queries", N_QUERIES])  # fmt: skip
    CLEANED.unlink()

    manifest = WORKING / "manifest.sha256"
    files = sorted(p for p in WORKING.rglob("*") if p.is_file() and p != manifest)
    lines = [f"{sha256_file(p)}  {p.relative_to(WORKING).as_posix()}\n" for p in files]
    manifest.write_text("".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {len(files)} files and manifest.sha256", flush=True)


if __name__ == "__main__":
    main()
