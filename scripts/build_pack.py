"""Build the recipe pack from the allow-listed inputs.

Example:
    uv run python scripts/build_pack.py --out build/pack
    uv run python scripts/build_pack.py --pin     # re-pin input hashes after you edit an input
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from pantrychef.pack.allowlist import pin
from pantrychef.pack.build import build_pack

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "pantrychef" / "pack" / "allowlist.json"


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return done.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="build/pack")
    ap.add_argument("--pin", action="store_true", help="Rewrite the pinned input hashes.")
    args = ap.parse_args()
    if args.pin:
        pin(ALLOWLIST, ROOT)
        print(f"pinned {ALLOWLIST}")
        return 0
    commit = _git("rev-parse", "HEAD").strip()
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no").strip())
    manifest = build_pack(ALLOWLIST, args.out, repo_root=ROOT, commit=commit, dirty=dirty)
    print(manifest["counts"])
    for f in manifest["files"]:
        print(f["name"], f["size"], f["sha256"][:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
