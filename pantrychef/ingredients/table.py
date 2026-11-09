"""The ingredient table: ids, names, synonyms, staple flag and provenance.

The table is a hand-curated CSV (``ingredients.csv`` is the M1 table, ``ingredients.v2.csv``
adds the optional ``is_a`` and ``form_of`` columns of ADR 0006). It is not derived from
RecipeNLG and never reads ``data/processed/vocab.json`` (ADR 0003).

The word lists (units, size, container and preparation words, the salt cue and the bare
pepper rule) live in ``data/ingredients/words.v1.json``. Both engines read that one file.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pantrychef.ingredients.normalize import normalize, singularize

_DATA = Path(__file__).resolve().parents[2] / "data" / "ingredients"
DEFAULT_TABLE_PATH = _DATA / "ingredients.csv"  # the M1 table
TABLE_V2_PATH = _DATA / "ingredients.v2.csv"
DEFAULT_WORDS_PATH = _DATA / "words.v1.json"
_ID = re.compile(r"^[a-z0-9_]+$")
PROVENANCE = {"hand", "wikibooks-rule"}


def fold(text: str) -> str:
    """Remove accents so "jalapeño" and "jalapeno" match."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


_IRREGULAR = {
    "leaves": "leaf",
    "halves": "half",
    "knives": "knife",
    "loaves": "loaf",
    "chilies": "chili",
    "cheeses": "cheese",
    # Plurals that end in "is". The "is" rule below would keep them whole.
    "chilis": "chili",
    "chillis": "chilli",
    "zucchinis": "zucchini",
}


def _singular(word: str) -> str:
    """Singular of one token. Port line for line to ``web/src/normalize.ts``."""
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if len(word) > 3 and word.endswith(("us", "ss", "is")):
        return word  # asparagus, hummus, glass, swiss
    return singularize(word)


def tokens(text: str) -> tuple[str, ...]:
    """Canonical tokens of a name or a line: accent-free, lower case, singular.

    This differs from ``normalize.canonicalize`` in the singulariser only. ``canonicalize``
    stays as it is, because the research code and the RecipeNLG artifacts depend on it.
    """
    spaced = fold(text).replace("-", " ")
    return tuple(_singular(t) for t in normalize(spaced).split())


@dataclass(frozen=True)
class Words:
    units: dict[str, str]
    size: frozenset[str]
    container: frozenset[str]
    prep: frozenset[str]
    staple_cue: frozenset[str]
    bare_pepper: dict[str, str]

    @classmethod
    def from_json(cls, text: str) -> Words:
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_dict(cls, raw: dict) -> Words:
        return cls(
            units=dict(raw["units"]),
            size=frozenset(raw["size"]),
            container=frozenset(raw["container"]),
            prep=frozenset(raw["prep"]),
            staple_cue=frozenset(raw["staple_cue"]),
            bare_pepper=dict(raw["bare_pepper"]),
        )


# Read once at import, so a guarded pack build never opens this file.
DEFAULT_WORDS = Words.from_json(DEFAULT_WORDS_PATH.read_text(encoding="utf8"))


def is_modifier(token: str, words: Words) -> bool:
    """A size, container or preparation word, or an "-ed" word ("-seed" words are food)."""
    return (
        token in words.size
        or token in words.container
        or token in words.prep
        or (token.endswith("ed") and len(token) > 4 and not token.endswith("seed"))
    )


@dataclass(frozen=True)
class Row:
    id: str
    name: str
    synonyms: tuple[str, ...]
    staple: bool
    provenance: str
    is_a: tuple[str, ...] = ()
    form_of: tuple[str, ...] = ()


def _check_edges(by_id: dict[str, Row]) -> None:
    graph: dict[str, tuple[str, ...]] = {}
    for r in by_id.values():
        for target in (*r.is_a, *r.form_of):
            if target not in by_id:
                raise ValueError(f"{r.id} points at unknown id {target!r}")
            if target == r.id:
                raise ValueError(f"{r.id} points at itself")
        graph[r.id] = (*r.is_a, *r.form_of)
    state: dict[str, int] = {}  # 1 = on the current path, 2 = done

    def visit(node: str, path: list[str]) -> None:
        if state.get(node) == 2:
            return
        if state.get(node) == 1:
            cycle = [*path[path.index(node) :], node]
            raise ValueError(f"cycle in is_a/form_of edges: {' -> '.join(cycle)}")
        state[node] = 1
        for nxt in graph[node]:
            visit(nxt, [*path, node])
        state[node] = 2

    for node in graph:
        visit(node, [])


def _edges(cell: str | None) -> tuple[str, ...]:
    return tuple(e.strip() for e in (cell or "").split("|") if e.strip())


class IngredientTable:
    def __init__(self, rows: list[Row], words: Words = DEFAULT_WORDS):
        self.rows = tuple(rows)
        self.words = words
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
        _check_edges(self.by_id)
        self.max_key_len = max(len(k) for k in self.keys)
        self.staples = frozenset(r.id for r in rows if r.staple)

    @classmethod
    def load(
        cls, path: str | Path = DEFAULT_TABLE_PATH, words: str | Path = DEFAULT_WORDS_PATH
    ) -> IngredientTable:
        with open(path, encoding="utf8", newline="") as fh:
            text = fh.read()
        return cls.from_text(text, Path(words).read_text(encoding="utf8"))

    @classmethod
    def from_text(cls, csv_text: str, words_json: str | None = None) -> IngredientTable:
        """Build from CSV text. ``None`` means the default words, which load at import."""
        words = DEFAULT_WORDS if words_json is None else Words.from_json(words_json)
        rows = []
        for rec in csv.DictReader(io.StringIO(csv_text, newline="")):
            syn = tuple(s.strip() for s in rec["synonyms"].split("|") if s.strip())
            rows.append(
                Row(
                    id=rec["id"].strip(),
                    name=rec["name"].strip(),
                    synonyms=syn,
                    staple=rec["staple"].strip() == "1",
                    provenance=rec["provenance"].strip(),
                    is_a=_edges(rec.get("is_a")),
                    form_of=_edges(rec.get("form_of")),
                )
            )
        return cls(rows, words)
