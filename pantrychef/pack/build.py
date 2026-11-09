"""Build the recipe pack: ``core``, ``text`` and ``manifest`` files.

The build reads only the files on the hash allow-list (see ``allowlist.py``) and runs under
the input guard (see ``guard.py``). Every shipped file appears in the manifest with its hash,
size and licence.

Pack format 1:

- ``core.vN.json.gz``: ingredients (id, name, staple, idf), name and synonym keys, the word
  lists (as in ``words.v1.json``, for the typed-name resolver), recipes with their lines as ids
  (and line text, because a missing line shows its text).
- ``text.vN.json.gz``: steps, servings, time, category and attribution per recipe.
- ``manifest.vN.json``: hashes, sizes, licences, input hashes, commit, counts.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
from pathlib import Path
from urllib.parse import urlparse

from pantrychef.ingredients.resolve import resolve_lines
from pantrychef.ingredients.table import IngredientTable
from pantrychef.pack.allowlist import load_allowlist, read_verified
from pantrychef.pack.guard import guarded_build
from pantrychef.sources.types import SourceRecipe
from pantrychef.sources.wikibooks import parse_page

PACK_FORMAT = 1
PACK_LICENCE = "CC BY-SA 4.0"
CHANGES = "Ingredient lines were matched to an ingredient list. The wording is unchanged."
_CODE_ROOT = Path(__file__).resolve().parents[1]


class BuildError(RuntimeError):
    pass


def check_source_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme != "https" or u.hostname != "en.wikibooks.org" or u.username or u.port:
        raise BuildError(f"source link must be https://en.wikibooks.org/: {url!r}")


def _write_gz(path: Path, obj: object) -> None:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf8")
    with open(path, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
        gz.write(raw)


def _file_entry(path: Path, licence: str) -> dict:
    data = path.read_bytes()
    return {
        "name": path.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "licence": licence,
    }


def _core_recipe(r: SourceRecipe, table: IngredientTable) -> dict | None:
    lines = [
        {"t": line.text, "o": list(line.options), "opt": line.optional, "r": line.read}
        for text in r.ingredient_lines
        for line in resolve_lines(text, table)
    ]
    # A recipe needs at least one required line that the default staples do not cover.
    needed = [ln for ln in lines if not ln["opt"] and not any(i in table.staples for i in ln["o"])]
    if not needed:
        return None
    return {
        "id": r.recipe_id,
        "title": r.title,
        "page": r.page,
        "rev": r.revision_id,
        "lines": lines,
    }


def _read_snapshot(data: bytes) -> list[dict]:
    with gzip.open(io.BytesIO(data), "rt", encoding="utf8") as fh:
        return [json.loads(line) for line in fh]


def build_pack(
    allowlist_path: str | Path,
    out_dir: str | Path,
    *,
    repo_root: str | Path,
    commit: str,
    dirty: bool,
    version: str = "v1",
) -> dict:
    """Build the pack into ``out_dir`` and return the manifest.

    ``commit`` and ``dirty`` come from the caller, because the guard forbids starting ``git``.
    """
    repo_root, out = Path(repo_root), Path(out_dir)
    inputs, raw = load_allowlist(Path(allowlist_path), repo_root)
    data = read_verified(inputs)
    retrieved_on = raw["inputs"]["snapshot"]["retrieved_on"]
    out.mkdir(parents=True, exist_ok=True)

    with guarded_build([i.path for i in inputs.values()], out, [_CODE_ROOT]):
        table = IngredientTable.from_text(
            data["table"].decode("utf8"), data["words"].decode("utf8")
        )
        sources = [
            r for rec in _read_snapshot(data["snapshot"]) if (r := parse_page(rec, retrieved_on))
        ]
        for r in sources:
            check_source_url(r.url)
            check_source_url(r.revision_url)
        pairs = [(r, _core_recipe(r, table)) for r in sources]
        kept = [(r, c) for r, c in pairs if c is not None]
        n = len(kept)
        if not n:
            raise BuildError("no recipe survived the build")

        df: dict[str, int] = {}
        for _, c in kept:
            for i in {i for ln in c["lines"] for i in ln["o"]}:
                df[i] = df.get(i, 0) + 1
        core = {
            "format": PACK_FORMAT,
            "info": {
                "version": version,
                "commit": commit,
                "corpus_fingerprint": inputs["snapshot"].sha256,
                "recipes": n,
            },
            "ingredients": [
                {
                    "id": row.id,
                    "name": row.name,
                    "staple": row.staple,
                    "idf": math.log(1 + n / df[row.id]) if row.id in df else 0.0,
                }
                for row in table.rows
            ],
            "keys": {" ".join(k): i for k, i in sorted(table.keys.items())},
            "words": json.loads(data["words"].decode("utf8")),
            "recipes": [c for _, c in kept],
        }
        text = {
            "format": PACK_FORMAT,
            "recipes": {
                r.recipe_id: {
                    "steps": list(r.steps),
                    "servings": r.servings,
                    "time": r.time,
                    "category": r.category,
                    "url": r.url,
                    "revision_url": r.revision_url,
                    "revision_id": r.revision_id,
                    "licence": r.licence,
                    "retrieved_on": r.retrieved_on,
                    "changes": CHANGES,
                }
                for r, _ in kept
            },
        }
        core_path = out / f"core.{version}.json.gz"
        text_path = out / f"text.{version}.json.gz"
        _write_gz(core_path, core)
        _write_gz(text_path, text)
        all_lines = [ln for _, c in kept for ln in c["lines"]]
        manifest = {
            "format": PACK_FORMAT,
            "version": version,
            "commit": commit,
            "dirty": dirty,
            "inputs": {
                name: {"path": i.path.name, "sha256": i.sha256} for name, i in inputs.items()
            },
            "files": [_file_entry(core_path, PACK_LICENCE), _file_entry(text_path, PACK_LICENCE)],
            "counts": {
                "pages": len(sources),
                "recipes": n,
                "dropped_no_required_line": len(sources) - n,
                "ingredients": len(table.rows),
                "lines": len(all_lines),
                "unread_lines": sum(1 for ln in all_lines if not ln["r"] and not ln["opt"]),
            },
        }
        with open(out / f"manifest.{version}.json", "w", encoding="utf8", newline="\n") as fh:
            fh.write(json.dumps(manifest, indent=2) + "\n")
    return manifest
