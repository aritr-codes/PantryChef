"""Hash allow-list of the files the pack builder may read as data.

``allowlist.json`` names each input with a repo-relative path and a sha256. The builder
checks the hash before it starts. A changed input needs an explicit ``--pin`` to update it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ("snapshot", "table", "words")


class AllowlistError(RuntimeError):
    pass


@dataclass(frozen=True)
class Input:
    name: str
    path: Path
    sha256: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_allowlist(allowlist_path: Path, repo_root: Path) -> tuple[dict[str, Input], dict]:
    """Return ``(inputs by name, raw json)``. Paths resolve against ``repo_root``."""
    raw = json.loads(allowlist_path.read_text(encoding="utf8"))
    inputs = {}
    for name, entry in raw["inputs"].items():
        p = Path(entry["path"])
        inputs[name] = Input(name, p if p.is_absolute() else repo_root / p, entry["sha256"])
    missing = [n for n in REQUIRED if n not in inputs]
    if missing:
        raise AllowlistError(f"allow-list lacks {missing}")
    return inputs, raw


def read_verified(inputs: dict[str, Input]) -> dict[str, bytes]:
    """Read each input once and check the hash of the bytes that were read.

    The build parses these bytes and never opens the files again, so a file cannot change
    between the check and the use.
    """
    out = {}
    for inp in inputs.values():
        if not inp.path.is_file():
            raise AllowlistError(f"input {inp.name!r} not found: {inp.path}")
        data = inp.path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != inp.sha256:
            raise AllowlistError(
                f"input {inp.name!r} hash changed: pinned {inp.sha256[:12]}, found {actual[:12]}"
            )
        out[inp.name] = data
    return out


def pin(allowlist_path: Path, repo_root: Path) -> None:
    """Rewrite the pinned hashes from the files on disk (explicit opt-in)."""
    raw = json.loads(allowlist_path.read_text(encoding="utf8"))
    for entry in raw["inputs"].values():
        p = Path(entry["path"])
        entry["sha256"] = sha256_file(p if p.is_absolute() else repo_root / p)
    with open(allowlist_path, "w", encoding="utf8", newline="\n") as fh:
        fh.write(json.dumps(raw, indent=2) + "\n")
