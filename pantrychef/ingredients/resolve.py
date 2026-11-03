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
- A bare "pepper" is black pepper only when the line also names salt or says "to taste".
  This is provisional. M3 decides it fully.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pantrychef.ingredients.table import IngredientTable, tokens
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
# Words that may stand alone in an "and" part without hiding an ingredient.
_PREP = frozenset(
    """a an the of into to for with in on or and plus more extra some about each as if desired
    chopped diced sliced minced peeled cored seeded soaked cooked drained rinsed mashed crushed
    grated shredded melted softened beaten trimmed halved quartered cut finely roughly thinly
    coarsely fresh freshly dried dry ground whole small large medium taste needed optional
    washed dried cleaned divided packed sifted toasted roasted boiled steamed chilled cold warm
    hot room temperature skinned deveined pitted stemmed boneless skinless ripe firm lean thick
    thin raw frozen canned unsalted salted plain""".split()  # noqa: SIM905
)


@dataclass(frozen=True)
class ResolvedLine:
    options: tuple[str, ...]
    optional: bool
    read: bool
    text: str


def _is_prep(token: str) -> bool:
    return token in _PREP or (token.endswith("ed") and len(token) > 4)


def _spans(toks: tuple[str, ...], table: IngredientTable) -> list[tuple[int, int, str]]:
    """Greedy left-to-right longest matches. A bare "pepper" gets the marker id."""
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
                out.append((i, i + 1, _PEPPER))
            i += 1
    return out


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


def _body(text: str) -> str:
    body = _PAREN.sub(" ", text).replace("&", " and ")
    body = _SLASH.sub(" or ", body)
    _, rest = parse_quantity(body)
    unit, rest = parse_unit(rest)
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
    has_salt = False
    for ci, chunk in enumerate(_body(raw).split(",")):
        toks = tokens(chunk)
        spans = _spans(toks, table)
        has_salt = has_salt or any(i == "salt" for _, _, i in spans)
        for ai, (a_toks, a_spans) in enumerate(_split(toks, spans, "and")):
            sep = "first" if ci == 0 and ai == 0 else ("and" if ai else "comma")
            alts, plain = [], True
            for o_toks, o_spans in _split(a_toks, a_spans, "or"):
                ids = [i for _, _, i in o_spans]
                plain = plain and all(_is_prep(t) for t in o_toks) and not ids
                if ids:
                    alts.append(ids[-1:])  # head noun: the last match
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
                    if not (has_salt or taste):
                        continue
                    i = "black_pepper"
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
