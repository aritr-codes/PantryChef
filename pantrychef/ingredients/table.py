"""The ingredient table: ids, names, synonyms, staple flag and provenance.

The table is a hand-curated CSV (``data/ingredients/ingredients.csv``). It is not derived
from RecipeNLG and never reads ``data/processed/vocab.json`` (ADR 0003). Columns stay
simple so that M3 can add ``is_a`` and ``form_of`` (ADR 0006).
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pantrychef.ingredients.normalize import canonicalize

DEFAULT_TABLE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "ingredients" / "ingredients.csv"
)
_ID = re.compile(r"^[a-z0-9_]+$")
PROVENANCE = {"hand", "wikibooks-rule"}


def fold(text: str) -> str:
    """Remove accents so "jalapeño" and "jalapeno" match."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def tokens(text: str) -> tuple[str, ...]:
    """Canonical tokens of a name or a line: accent-free, lower case, singular."""
    return tuple(canonicalize(fold(text)).split())


@dataclass(frozen=True)
class Row:
    id: str
    name: str
    synonyms: tuple[str, ...]
    staple: bool
    provenance: str


class IngredientTable:
    def __init__(self, rows: list[Row]):
        self.rows = tuple(rows)
        self.by_id = {r.id: r for r in rows}
        if len(self.by_id) != len(rows):
            raise ValueError("duplicate ingredient id")
        self.keys: dict[tuple[str, ...], str] = {}
        for r in rows:
            if not _ID.match(r.id):
                raise ValueError(f"bad ingredient id {r.id!r}")
            if r.provenance not in PROVENANCE:
                raise ValueError(f"bad provenance for {r.id}: {r.provenance!r}")
            for text in (r.name, *r.synonyms):
                key = tokens(text)
                if not key:
                    continue
                owner = self.keys.setdefault(key, r.id)
                if owner != r.id:
                    raise ValueError(f"key {' '.join(key)!r} is used by {owner} and {r.id}")
        self.max_key_len = max(len(k) for k in self.keys)
        self.staples = frozenset(r.id for r in rows if r.staple)

    @classmethod
    def load(cls, path: str | Path = DEFAULT_TABLE_PATH) -> IngredientTable:
        rows = []
        with open(path, encoding="utf8", newline="") as fh:
            for rec in csv.DictReader(fh):
                syn = tuple(s.strip() for s in rec["synonyms"].split("|") if s.strip())
                rows.append(
                    Row(
                        id=rec["id"].strip(),
                        name=rec["name"].strip(),
                        synonyms=syn,
                        staple=rec["staple"].strip() == "1",
                        provenance=rec["provenance"].strip(),
                    )
                )
        return cls(rows)
