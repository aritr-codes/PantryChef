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
  and "bone", "skin" or "shell" before "in", "on", "removed", "discarded", "attached", "left" or
  "off" ("skin on", "skin removed"; not "fish bones washed").
  Any other word ("pomegranate juice", "garlic paste", "red chili powder") makes that part
  unread, unless a table key covers the whole phrase. A staple right after a food ("linseed
  oil", "chile oil") is a product form, so that part is unread too. This rule costs coverage
  (MEASURED, dev snapshot: lines read 95.7% before, 93.5% after; recipes_fully_read 0.7338
  before, 0.6377 after). The table rounds win back part of it: table round 2 reads 95.6% of lines
  and recipes_fully_read 0.7244 (MEASURED, growth rows 1b, 2b and 7).
- Round 3 rules (M3 Task 11; found by reading the spent test and dev sets, so any dev gain is
  in-sample; MEASURED on dev: mention_accuracy 0.8618 to 0.8882, parser_precision 0.9632 to
  0.9712):
  F1 an unknown "and" part in a later comma chunk is skipped, not a reason to unread the line
  ("peeled and cut into pieces"). The first chunk stays strict ("salt and X").
  F2 inside one "or" part, a match after "with" is a note when a match comes before it.
  F3 two adjacent matches read as one longer key when the first loses its leading words
  ("dry marsala" + "wine" is "marsala wine").
  F4 a word after the food that is already in the row name is explained ("amchur powder").
  F5 a line that reads nothing is tried once more with the parenthetical text kept.
  F6 "powdered" or "ground" before a food reads the "<food> powder" row when that key exists.
  F7 in a later comma chunk, a match after a clause word is a note ("made with rye flour").
  "of", "such" and "as" do not start a note there ("loaf of white bread", "such as carrots").
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

_WITH = frozenset(["with"])
# Clause words that do not start a note in a later chunk: "loaf of white bread", "such as
# carrots" (the next chunk of the list is read, so this one must be too).
_LIST_WORDS = frozenset(["of", "such", "as"])
# "powdered mustard", "ground chile pepper": the form word may read the "<food> powder" row.
_FORM = frozenset(["powdered", "ground"])

_PART_NOTE = frozenset(["bone", "skin", "shell"])
# What may follow a part word to make it a note: "bone in", "skin on", "skin removed",
# "shells left on".
# Any other word ("fish bones washed", "skin rendered") means the part is food or a product.
_PART_NEXT = frozenset(["in", "on", "removed", "discarded", "attached", "left", "off"])


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
    A form word with no key of its own ("powdered", "ground") before a food reads the
    "<food> powder" row when that key exists (F6). Two adjacent matches that overlap a longer
    key once the first loses its leading words read as that key ("dry marsala" + "wine" is
    "marsala wine", F3).
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
            powder = _powder_span(toks, i, table) if toks[i] in _FORM else None
            if powder:
                out.append(powder)
                i = powder[1]
                continue
            if toks[i] == "pepper":
                if out and out[-1][1] == i and out[-1][2] in _pepper_names(table):
                    out[-1] = (out[-1][0], i + 1, out[-1][2])
                else:
                    out.append((i, i + 1, _PEPPER))
            i += 1
    return _merge_overlaps(out, toks, table)


def _powder_span(
    toks: tuple[str, ...], i: int, table: IngredientTable
) -> tuple[int, int, str] | None:
    """The form word at ``i`` plus the longest food after it that has a "<food> powder" key."""
    for n in range(min(table.max_key_len - 1, len(toks) - i - 1), 0, -1):
        hit = table.keys.get(toks[i + 1 : i + 1 + n] + ("powder",))
        if hit:
            return (i, i + 1 + n, hit)
    return None


def _merge_overlaps(
    spans: list[tuple[int, int, str]], toks: tuple[str, ...], table: IngredientTable
) -> list[tuple[int, int, str]]:
    """Merge two adjacent spans when the first loses its leading words and a longer key forms."""
    out: list[tuple[int, int, str]] = []
    for span in spans:
        prev = out[-1] if out else None
        if prev and prev[1] == span[0] and _PEPPER not in (prev[2], span[2]):
            for lose in range(1, prev[1] - prev[0]):
                hit = table.keys.get(toks[prev[0] + lose : span[1]])
                if hit:
                    out[-1] = (prev[0] + lose, span[1], hit)
                    break
            else:
                out.append(span)
        else:
            out.append(span)
    return out


def _note_start(
    toks: tuple[str, ...], spans: list[tuple[int, int, str]], clause: frozenset[str]
) -> int:
    """Index of the first ``clause`` word that is not inside a match, else ``len(toks)``."""
    inside = {k for s, e, _ in spans for k in range(s, e)}
    return next((k for k, t in enumerate(toks) if t in clause and k not in inside), len(toks))


def _trailing_modifier(rest: tuple[str, ...], k: int, words: Words) -> bool:
    """True when ``rest[k]`` is a word that does not change the food.

    That is a modifier, an "-ly" adverb ("lightly", "approximately"; "-elly" is food: jelly,
    belly) or a part word that a "bone in", "skin on", "skin removed" or "shells on" note
    explains (only "in", "on", "removed", "discarded", "attached", "left" or "off" may follow).
    This lives in the resolver only. The TS name matcher has no such rule.
    """
    t = rest[k]
    if is_modifier(t, words) or (t.endswith("ly") and len(t) > 4 and not t.endswith("elly")):
        return True
    if t in ("left", "off") and k and rest[k - 1] in _PART_NOTE:
        return True  # "skin left on", "bone off": the part word was explained by this word
    nxt = rest[k + 1] if k + 1 < len(rest) else ""
    return t in _PART_NOTE and nxt in _PART_NEXT


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
    row = table.by_id.get(spans[-1][2])
    named = frozenset(tokens(row.name)) if row else frozenset()  # F4: "mango powder" + "powder"
    if any(
        t not in words.trailing_ok and t not in named for t in after_head(toks, spans[-1][1], words)
    ):
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


def _body(text: str, words: Words = DEFAULT_WORDS, keep_paren: bool = False) -> str:
    """The line without quantity and unit. Parenthetical text goes, unless ``keep_paren``."""
    unwrapped = text.replace("(", " ").replace(")", " ") if keep_paren else _PAREN.sub(" ", text)
    body = unwrapped.replace("&", " and ")
    body = _SLASH.sub(" or ", body)
    _, rest = parse_quantity(body)
    unit, rest = parse_unit(rest, words.units)
    if unit == "clove" and not rest.strip():
        return "clove"  # "4 cloves" alone means the spice
    return rest


def resolve_lines(text: str, table: IngredientTable) -> list[ResolvedLine]:
    lines = _resolve(text, table, False)
    if lines and not lines[0].read and "(" in text:
        # F5: a line that reads nothing gets one more try with the parenthetical text kept.
        retry = _resolve(text, table, True)
        if retry[0].read:
            return retry
    return lines


def _resolve(text: str, table: IngredientTable, keep_paren: bool) -> list[ResolvedLine]:
    raw = text.strip()
    if not raw or raw.endswith(":"):
        return []
    optional_text = bool(_OPTIONAL.search(raw))
    taste = bool(_TASTE.search(raw))

    # groups: (separator, list of alternatives, each a list of ids) in line order
    groups: list[tuple[str, list[list[str]], bool, bool]] = []
    words = table.words
    has_cue = False
    for ci, chunk in enumerate(_body(raw, table.words, keep_paren).split(",")):
        toks = tokens(chunk)
        spans = _spans(toks, table)
        has_cue = has_cue or any(i in words.staple_cue for _, _, i in spans)
        if ci:  # F7: a later chunk is a note after its first clause word ("made with rye flour")
            cut = _note_start(toks, spans, _CLAUSE - _LIST_WORDS)
            spans = [sp for sp in spans if sp[0] < cut]
        for ai, (a_toks, a_spans) in enumerate(_split(toks, spans, "and")):
            sep = "first" if ci == 0 and ai == 0 else ("and" if ai else "comma")
            late = ci > 0 and ai > 0  # F1: an unknown "and" part in a later chunk is skipped
            alts, plain = [], True
            for o_toks, o_spans in _split(a_toks, a_spans, "or"):
                # F2: in one "or" part, a match after "with" is a note when a match comes before
                cut = _note_start(o_toks, o_spans, _WITH)
                o_spans = [sp for sp in o_spans if sp[0] < cut] or o_spans
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
            groups.append((sep, alts, plain, late))

    lines: list[ResolvedLine] = []
    seen: set[tuple[str, ...]] = set()
    for sep, alts, plain, late in groups:
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
        elif not plain and sep in ("first", "and") and not late:
            return [ResolvedLine((), optional_text, False, raw)]
    return lines or [ResolvedLine((), optional_text, False, raw)]
