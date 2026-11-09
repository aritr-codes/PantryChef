"""Resolve one recipe line to ingredient ids.

A line becomes one or more ``ResolvedLine`` records. Each record holds a set of acceptable
ids ("or" lines), an ``optional`` flag and a ``read`` flag. An unread line has no ids and
counts as missing in the engine. The rules are deliberately small. M3 owns the full resolver.

Rules (see docs/plans/2026-11-02-m1-thin-slice.md, gap 8):

- Quantity, unit and parenthetical notes are removed first.
- The longest table name or synonym wins. A match never crosses a comma.
- "A or B" gives one line with two options.
- "A and B" or "A, B" gives one line per part. If the first part is unknown, or an "and" part
  is unknown and is not a plain preparation word, the whole line is unread.
- Head noun (M3): the last match is the food only if no unexplained word follows it before a
  note ("for frying", "of choice") starts. A word in ``words.trailing_ok`` ("garlic cloves",
  "basil leaves") is explained. So is a modifier, an "-ly" adverb ("lightly", "approximately")
  and "bone", "skin" or "shell" before "in", "on" or an "-ed" word ("skin on", "skin removed").
  Any other word ("pomegranate juice", "garlic paste", "red chili powder") makes that part
  unread, unless a table key covers the whole phrase. A staple right after a food ("linseed
  oil", "chile oil") is a product form, so that part is unread too. This rule costs coverage
  (MEASURED, dev snapshot: lines read 95.7% before, 93.5% after; recipes_fully_read 0.7338
  before, 0.6377 after). The table rounds win it back.
- A staple never hides a real ingredient when they are not adjacent ("cornstarch mixed with
  water" reads cornstarch).
- A "pepper" right after a match of a row known as "... pepper" is part of that name ("green
  chile pepper"). Any other bare "pepper" is the ``words.bare_pepper`` target: with
  ``when: always`` every time, with ``when: staple_cue_or_taste`` only when the line also
  names a staple cue (salt) or says "to taste". The value is ``staple_cue_or_taste``
  (MEASURED, 80 labelled lines: 56 are black pepper, 0.700, Wilson 95% 0.592 to 0.789; the
  bar for ``always`` was 75 of 80). See ``results/m3_bare_pepper.json``.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

from pantrychef.ingredients.table import (
    DEFAULT_WORDS,
    IngredientTable,
    Words,
    is_modifier,
    tokens,
)
from pantrychef.ingredients.units import parse_quantity, parse_unit

_PAREN = re.compile(r"\([^)]*\)")
_SLASH = re.compile(r"(?<=[a-z])/(?=[a-z])", re.I)
_OPTIONAL = re.compile(
    r"\boptional\b|\bfor (?:the )?(?:serving|garnish\w*|decoration|topping)\b"
    r"|\b(?:to|as a|as) garnish\b|\bgarnish\b",
    re.I,
)
_TASTE = re.compile(r"\bto taste\b|\bas needed\b", re.I)
_PEPPER = "?pepper"
# Words that start a note after the food. The head-noun check stops at the first one.
_CLAUSE = frozenset(
    [
        "for",
        "to",
        "with",
        "in",
        "on",
        "of",
        "at",
        "from",
        "per",
        "into",
        "as",
        "if",
        "such",
        "until",
        "you",
        "your",
        "is",
        "are",
    ]
)

_PART_NOTE = frozenset(["bone", "skin", "shell"])  # "bone in", "skin on", "shells on"


@dataclass(frozen=True)
class ResolvedLine:
    options: tuple[str, ...]
    optional: bool
    read: bool
    text: str


@functools.lru_cache(maxsize=8)
def _pepper_names(table: IngredientTable) -> frozenset[str]:
    """Ids with a key that ends in "pepper" ("chili pepper", "scotch bonnet pepper")."""
    return frozenset(i for k, i in table.keys.items() if len(k) > 1 and k[-1] == "pepper")


def _spans(toks: tuple[str, ...], table: IngredientTable) -> list[tuple[int, int, str]]:
    """Greedy left-to-right longest matches. A bare "pepper" gets the marker id.

    A "pepper" right after a match of a pepper row is part of that name ("green chile pepper").
    """
    out, i = [], 0
    while i < len(toks):
        for n in range(min(table.max_key_len, len(toks) - i), 0, -1):
            hit = table.keys.get(toks[i : i + n])
            if hit:
                out.append((i, i + n, hit))
                i += n
                break
        else:
            if toks[i] == "pepper":
                if out and out[-1][1] == i and out[-1][2] in _pepper_names(table):
                    out[-1] = (out[-1][0], i + 1, out[-1][2])
                else:
                    out.append((i, i + 1, _PEPPER))
            i += 1
    return out


def _trailing_modifier(rest: tuple[str, ...], k: int, words: Words) -> bool:
    """True when ``rest[k]`` is a word that does not change the food.

    That is a modifier, an "-ly" adverb ("lightly", "approximately"; "-elly" is food: jelly,
    belly) or a part word that a "bone in", "skin on", "skin removed" or "shells on" note
    explains ("skin removed" has an "-ed" word). This lives in the resolver only. The TS name
    matcher has no such rule.
    """
    t = rest[k]
    if is_modifier(t, words) or (t.endswith("ly") and len(t) > 4 and not t.endswith("elly")):
        return True
    nxt = rest[k + 1] if k + 1 < len(rest) else ""
    return t in _PART_NOTE and (nxt in ("in", "on") or nxt.endswith("ed"))


def after_head(toks: tuple[str, ...], end: int, words: Words) -> list[str]:
    """Non-modifier words after position ``end``, up to a clause word or a non-letter token.

    A head noun comes before any note: "oil for frying", "cheese of your choice", "2 sticks
    cinnamon 1 inch long". So the scan stops at the first ``_CLAUSE`` word or number.
    """
    out, rest = [], toks[end:]
    for k, t in enumerate(rest):
        if t in _CLAUSE or not t.isalpha():
            break
        if not _trailing_modifier(rest, k, words):
            out.append(t)
    return out


def _head_unexplained(
    toks: tuple[str, ...], spans: list[tuple[int, int, str]], table: IngredientTable
) -> bool:
    """True when the last match is not the head noun of ``toks`` (one "or" part).

    "pomegranate juice": a word after the last match that is not a modifier and not in
    ``words.trailing_ok`` names another food or a product form. "linseed oil": a staple right
    after another food is a product form of it. A table key for the whole phrase avoids both.
    """
    words = table.words
    if any(t not in words.trailing_ok for t in after_head(toks, spans[-1][1], words)):
        return True
    if len(spans) < 2:
        return False
    (_, prev_end, prev), (start, _, last) = spans[-2], spans[-1]
    return prev_end == start and last in table.staples and prev not in table.staples


def _split(
    toks: tuple[str, ...], spans: list[tuple[int, int, str]], word: str
) -> list[tuple[tuple[str, ...], list[tuple[int, int, str]]]]:
    """Split on ``word`` tokens that are not inside a matched span."""
    inside = {k for s, e, _ in spans for k in range(s, e)}
    parts, start = [], 0
    for k, t in enumerate(toks + (word,)):
        if t == word and (k == len(toks) or k not in inside):
            sub = [(s - start, e - start, i) for s, e, i in spans if start <= s and e <= k]
            parts.append((toks[start:k], sub))
            start = k + 1
    return parts


def _body(text: str, words: Words = DEFAULT_WORDS) -> str:
    body = _PAREN.sub(" ", text).replace("&", " and ")
    body = _SLASH.sub(" or ", body)
    _, rest = parse_quantity(body)
    unit, rest = parse_unit(rest, words.units)
    if unit == "clove" and not rest.strip():
        return "clove"  # "4 cloves" alone means the spice
    return rest


def resolve_lines(text: str, table: IngredientTable) -> list[ResolvedLine]:
    raw = text.strip()
    if not raw or raw.endswith(":"):
        return []
    optional_text = bool(_OPTIONAL.search(raw))
    taste = bool(_TASTE.search(raw))

    # groups: (separator, list of alternatives, each a list of ids) in line order
    groups: list[tuple[str, list[list[str]], bool]] = []
    words = table.words
    has_cue = False
    for ci, chunk in enumerate(_body(raw, table.words).split(",")):
        toks = tokens(chunk)
        spans = _spans(toks, table)
        has_cue = has_cue or any(i in words.staple_cue for _, _, i in spans)
        for ai, (a_toks, a_spans) in enumerate(_split(toks, spans, "and")):
            sep = "first" if ci == 0 and ai == 0 else ("and" if ai else "comma")
            alts, plain = [], True
            for o_toks, o_spans in _split(a_toks, a_spans, "or"):
                unexplained = bool(o_spans) and _head_unexplained(o_toks, o_spans, table)
                ids = [] if unexplained else [i for _, _, i in o_spans]
                plain = plain and not unexplained
                plain = plain and all(is_modifier(t, words) for t in o_toks) and not ids
                if ids:
                    # Head noun: the last match, but a staple never hides a real ingredient.
                    real = [i for i in ids if i not in table.staples]
                    alts.append((real or ids)[-1:])
                else:
                    alts.append([])
            if sep == "comma" and a_toks[:1] == ("or",):
                # "A, B, or C" is one "or" line: fold the earlier comma parts into this one
                while groups and groups[-1][0] != "and":
                    prev = groups.pop()
                    alts = prev[1] + alts
                    plain = plain and prev[2]
                    sep = prev[0]
                    if prev[0] == "first":
                        break
            groups.append((sep, alts, plain))

    lines: list[ResolvedLine] = []
    seen: set[tuple[str, ...]] = set()
    for sep, alts, plain in groups:
        ids: list[str] = []
        for alt in alts:
            for i in alt:
                if i == _PEPPER:
                    always = words.bare_pepper["when"] == "always"
                    if not (always or has_cue or taste):
                        continue
                    i = words.bare_pepper["target"]
                if i not in ids:
                    ids.append(i)
        if ids:
            if tuple(ids) not in seen:
                seen.add(tuple(ids))
                opt = optional_text or (taste and all(i in table.staples for i in ids))
                lines.append(ResolvedLine(tuple(ids), opt, True, raw))
        elif not plain and sep in ("first", "and"):
            return [ResolvedLine((), optional_text, False, raw)]
    return lines or [ResolvedLine((), optional_text, False, raw)]
