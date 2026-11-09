"""Resolve one typed pantry name to ingredient ids.

The browser engine runs the same steps (``web/src/names.ts``). Golden cases keep the two together
(ADR 0004). The steps run in order and the first hit wins:

1. ``exact``: the canonical tokens of the text are a key.
2. ``split``: the text holds ``and``, ``&``, ``,`` or ``/``. Each part must resolve by steps 1, 3
   and 4. The ids are the union, in order.
3. ``contained``: quantity and unit come off. Greedy longest key spans must cover every token
   except modifiers (size, container and preparation words, "-ed" words).
4. ``fuzzy``: on the tokens left after quantity, unit and modifiers (ADR 0006 plan, D8). One
   unique nearest key within an edit-distance limit that grows with the length.

A bare "pepper" is not a key, so it stays unknown (D6). The person picks the pepper they hold.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pantrychef.ingredients.table import Words, is_modifier, tokens
from pantrychef.ingredients.units import parse_quantity, parse_unit

Step = Literal["exact", "split", "contained", "fuzzy", "none"]


@dataclass(frozen=True)
class NameMatch:
    ids: tuple[str, ...]
    step: Step


_NONE = NameMatch((), "none")
# A "/" between two digits is a fraction, not a separator. Port as is to ``names.ts``.
_SPLIT = re.compile(r" *(?:[,&]|(?<![0-9])/|/(?![0-9])) *| and ")  # after _clean: single spaces
_NON_ASCII_DIGIT = re.compile(r"(?![0-9])\d")  # the quantity parser reads ASCII digits only
# Every character that Python or JavaScript counts as white space, so ``\s`` decides nothing.
_BLANKS = re.compile(
    r"[\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+"
)
MIN_FUZZY_LEN = 4  # shorter names never match fuzzily
LONG_FUZZY_LEN = 8  # from this length the limit is 2, below it 1


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return _BLANKS.sub(" ", _NON_ASCII_DIGIT.sub(" ", text)).strip(" ")


def edit_distance(a: str, b: str) -> int:
    """Damerau-Levenshtein distance (optimal string alignment: a swap of neighbours costs 1)."""
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def _exact(text: str, keys: Mapping[str, str]) -> NameMatch | None:
    toks = tokens(text)
    hit = keys.get(" ".join(toks)) if toks else None
    return NameMatch((hit,), "exact") if hit else None


def _stripped_tokens(text: str, words: Words) -> tuple[tuple[str, ...], bool]:
    """Tokens left after the quantity and the unit, and whether a lone unit word is the name.

    "2 cloves" has nothing after the unit, so the unit word is the name. That name may reach the
    exact and contained steps only, never the fuzzy step ("2 pints" must not become "mint").
    """
    _, rest = parse_quantity(text)
    unit, after = parse_unit(rest, words.units)
    if unit and not tokens(after):
        return tokens(rest), True
    return tokens(after), False


def _contained(toks: tuple[str, ...], keys: Mapping[str, str], words: Words) -> NameMatch | None:
    # Recomputed on every call: O(keys), fine for a few thousand keys. Cache it if the table grows.
    longest = max((k.count(" ") + 1 for k in keys), default=0)
    ids: list[str] = []
    covered = [False] * len(toks)
    i = 0
    while i < len(toks):
        for n in range(min(longest, len(toks) - i), 0, -1):
            hit = keys.get(" ".join(toks[i : i + n]))
            if hit:
                covered[i : i + n] = [True] * n
                if hit not in ids:
                    ids.append(hit)
                i += n
                break
        else:
            i += 1
    if not ids or any(
        not c and not is_modifier(t, words) for c, t in zip(covered, toks, strict=True)
    ):
        return None
    return NameMatch(tuple(ids), "contained")


def _fuzzy(toks: tuple[str, ...], keys: Mapping[str, str], words: Words) -> NameMatch | None:
    kept = [t for t in toks if not is_modifier(t, words)]
    name = " ".join(kept)
    if len(name) < MIN_FUZZY_LEN or all(t in words.units for t in kept):
        return None  # too short, or only unit words ("pint", "dashes"): not a name to guess at
    limit = 2 if len(name) >= LONG_FUZZY_LEN else 1
    best, ids = limit + 1, []
    for key, id_ in keys.items():
        if abs(len(key) - len(name)) > limit:
            continue
        d = edit_distance(name, key)
        if d < best:
            best, ids = d, [id_]
        elif d == best:
            ids.append(id_)
    return NameMatch((ids[0],), "fuzzy") if best <= limit and len(ids) == 1 else None


def _leaf(text: str, keys: Mapping[str, str], words: Words) -> NameMatch:
    """Steps 1, 3 and 4 on one piece of text."""
    toks, lone_unit = _stripped_tokens(text, words)
    return (
        _exact(text, keys)
        or _contained(toks, keys, words)
        or (None if lone_unit else _fuzzy(toks, keys, words))
        or _NONE
    )


def resolve_name(text: str, keys: Mapping[str, str], words: Words) -> NameMatch:
    """Resolve one typed name. ``keys`` maps a key (canonical tokens joined by a space) to an id."""
    text = _clean(text)
    if hit := _exact(text, keys):
        return hit
    parts = [p for p in _SPLIT.split(text) if p]
    if len(parts) > 1:
        ids: list[str] = []
        for part in parts:
            match = _leaf(part, keys, words)
            if match.step == "none":
                break
            ids += [i for i in match.ids if i not in ids]
        else:
            return NameMatch(tuple(ids), "split")
    return _leaf(text, keys, words)
