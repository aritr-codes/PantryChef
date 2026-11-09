"""Reference engine: ``answer()`` turns a pantry into grouped recipe results.

This is the behaviour the TypeScript engine in ``web/src/engine.ts`` must match (ADR 0004).
The contract is in ``docs/ARCHITECTURE_PROPOSAL.md`` sections 5 and 6. In short:

- A recipe has lines. A line holds a set of acceptable ingredient ids, an ``optional`` flag
  and a ``read`` flag. An unread line has no ids and always counts as missing.
- A line is *staple-covered* when any option is a staple. It is satisfied and weighs 0.
- ``total`` counts required lines that are not staple-covered. ``have`` counts those the
  pantry satisfies. A recipe with ``total == 0`` never appears.
- A candidate has ``have >= 1``. Groups are by missing lines: 0, 1 or 2.
- Score: ``sum(w of satisfied lines) / sqrt(sum(w of all needed lines))``. ``w`` is the largest
  ``idf`` among the line's options. The pack stores ``idf``, so both engines only add, take a
  square root and divide.
- Order inside a group: higher score, fewer ``total``, then ``recipe_id`` (compared bytewise).
"""

from __future__ import annotations

import gzip
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from pantrychef.ingredients.names import resolve_name
from pantrychef.ingredients.table import Words

GROUPS = ("make_now", "one_away", "two_away")
UNLOCK_LIMIT = 10
BLOCKER_LIMIT = 5
NO_WORDS = Words({}, frozenset(), frozenset(), frozenset(), frozenset(), {})


@dataclass(frozen=True)
class Line:
    text: str
    options: tuple[str, ...]
    optional: bool
    read: bool


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    title: str
    page: str
    revision_id: int
    lines: tuple[Line, ...]


@dataclass(frozen=True)
class PackInfo:
    version: str
    commit: str
    corpus_fingerprint: str


@dataclass(frozen=True)
class Ingredient:
    id: str
    name: str
    staple: bool
    idf: float


@dataclass(frozen=True)
class Pack:
    info: PackInfo
    ingredients: dict[str, Ingredient]
    keys: dict[str, str]
    recipes: tuple[Recipe, ...]
    words: Words = NO_WORDS  # a pack core from before pack v2 has none

    @classmethod
    def from_core(cls, core: dict) -> Pack:
        info = core["info"]
        return cls(
            info=PackInfo(info["version"], info["commit"], info["corpus_fingerprint"]),
            ingredients={
                i["id"]: Ingredient(i["id"], i["name"], i["staple"], i["idf"])
                for i in core["ingredients"]
            },
            keys=dict(core["keys"]),
            recipes=tuple(
                Recipe(
                    r["id"],
                    r["title"],
                    r["page"],
                    r["rev"],
                    tuple(Line(ln["t"], tuple(ln["o"]), ln["opt"], ln["r"]) for ln in r["lines"]),
                )
                for r in core["recipes"]
            ),
            words=Words.from_dict(core["words"]) if "words" in core else NO_WORDS,
        )

    @property
    def default_staples(self) -> list[str]:
        return [i.id for i in self.ingredients.values() if i.staple]


def load_pack(path: str | Path, version: str = "v2") -> Pack:
    """Load ``core.<version>.json.gz`` (or the plain ``core.<version>.json``) from a folder."""
    folder = Path(path)
    gz = folder / f"core.{version}.json.gz"
    if gz.exists():
        with gzip.open(gz, "rt", encoding="utf8") as fh:
            return Pack.from_core(json.load(fh))
    return Pack.from_core(json.loads((folder / f"core.{version}.json").read_text(encoding="utf8")))


@dataclass
class AnswerRequest:
    pantry: list[str]
    staples: list[str]
    diet: str | None = None
    limit: int = 10
    unknown_names: list[str] = field(default_factory=list)  # typed names that did not resolve


@dataclass
class Missing:
    options: list[str]
    text: str
    swap: None = None


@dataclass
class RecipeResult:
    recipe_id: str
    title: str
    have: int
    total: int
    score: float
    missing: list[Missing]
    unread: int
    diet_state: str | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class Group:
    count: int
    items: list[RecipeResult]


@dataclass
class Unlock:
    ingredient_id: str
    name: str
    recipes: int


@dataclass
class Blocker:
    kind: str
    ingredient_id: str | None
    name: str
    recipes: int


@dataclass
class Answer:
    groups: dict[str, Group]
    unlocks: list[Unlock]
    blockers: list[Blocker]
    unknown_pantry: list[str]
    pack: PackInfo


def _weight(pack: Pack, line: Line) -> float:
    return max(
        (pack.ingredients[o].idf for o in line.options if o in pack.ingredients), default=0.0
    )


def _needed(recipe: Recipe, staples: set[str]) -> list[Line]:
    return [
        ln for ln in recipe.lines if not ln.optional and not any(o in staples for o in ln.options)
    ]


def resolve_names(pack: Pack, names: list[str]) -> tuple[list[str], list[str]]:
    """Map typed names to ingredient ids. Return ``(ids, unknown)``.

    A name is unknown when no step of ``resolve_name`` matches. Ids keep the order of the names.
    """
    ids, unknown = [], []
    for name in names:
        match = resolve_name(name, pack.keys, pack.words)
        if match.step == "none":
            unknown.append(name)
        ids.extend(i for i in match.ids if i not in ids)
    return ids, unknown


def answer(pack: Pack, request: AnswerRequest) -> Answer:
    if request.diet is not None:
        raise NotImplementedError("diet flags arrive in M5")
    staples = set(request.staples)
    unknown_ids = sorted({i for i in request.pantry if i not in pack.ingredients})
    pantry = {i for i in request.pantry if i in pack.ingredients} - staples

    grouped: dict[int, list[RecipeResult]] = {0: [], 1: [], 2: []}
    one_away_lines: list[Line] = []
    all_empty_scan: list[tuple[list[Line], int, int]] = []  # needed lines, total, have
    for recipe in pack.recipes:
        needed = _needed(recipe, staples)
        total = len(needed)
        if total == 0:
            continue
        satisfied = [any(o in pantry for o in ln.options) for ln in needed]
        have = sum(satisfied)
        all_empty_scan.append((needed, total, have))
        if have == 0 or total - have > 2:
            continue
        weights = [_weight(pack, ln) for ln in needed]
        num = 0.0
        den = 0.0
        for w, ok in zip(weights, satisfied, strict=True):
            den += w
            if ok:
                num += w
        score = num / math.sqrt(den) if den > 0 else 0.0
        missing_lines = [ln for ln, ok in zip(needed, satisfied, strict=True) if not ok]
        if len(missing_lines) == 1:
            one_away_lines.append(missing_lines[0])
        grouped[len(missing_lines)].append(
            RecipeResult(
                recipe_id=recipe.recipe_id,
                title=recipe.title,
                have=have,
                total=total,
                score=score,
                missing=[Missing(list(ln.options), ln.text) for ln in missing_lines],
                unread=sum(1 for ln in missing_lines if not ln.read),
            )
        )

    groups = {}
    for name, n in zip(GROUPS, (0, 1, 2), strict=True):
        items = sorted(grouped[n], key=lambda r: (-r.score, r.total, r.recipe_id))
        groups[name] = Group(count=len(items), items=items[: max(request.limit, 0)])

    counts: dict[str, int] = {}
    for ln in one_away_lines:
        for o in ln.options:
            counts[o] = counts.get(o, 0) + 1
    unlocks = [
        Unlock(i, pack.ingredients[i].name, c)
        for i, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:UNLOCK_LIMIT]
    ]

    blockers: list[Blocker] = []
    if all(g.count == 0 for g in groups.values()) and pantry:
        gains: dict[str, int] = {}
        for needed, total, have in all_empty_scan:
            per_item: dict[str, int] = {}
            for ln in needed:
                if any(o in pantry for o in ln.options):
                    continue
                for o in ln.options:
                    if o in pack.ingredients and o not in staples:
                        per_item[o] = per_item.get(o, 0) + 1
            for item, gain in per_item.items():
                if have + gain >= 1 and total - (have + gain) <= 2:
                    gains[item] = gains.get(item, 0) + 1
        blockers = [
            Blocker("add_item", i, pack.ingredients[i].name, c)
            for i, c in sorted(gains.items(), key=lambda kv: (-kv[1], kv[0]))[:BLOCKER_LIMIT]
        ]

    return Answer(
        groups=groups,
        unlocks=unlocks,
        blockers=blockers,
        unknown_pantry=[*request.unknown_names, *unknown_ids],
        pack=pack.info,
    )
