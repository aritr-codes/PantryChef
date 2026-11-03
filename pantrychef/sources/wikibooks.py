"""Wikibooks Cookbook source adapter: one snapshot record to one ``SourceRecipe``.

The adapter reads wikitext. It keeps the page's own words and removes markup only.
A page without an ingredient list gives ``None``.
"""

from __future__ import annotations

import html
import re
from urllib.parse import quote

from pantrychef.sources.types import SourceRecipe

WIKI_BASE = "https://en.wikibooks.org/"
LICENCE = "CC BY-SA 4.0"
_STEP_HEADINGS = ("procedure", "directions", "instructions", "method")

_REF = re.compile(r"<ref\b[^>]*?/>|<ref\b[^>]*>.*?</ref>", re.S | re.I)
_BR = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")
_FILE_LINK = re.compile(r"\[\[(?:File|Image|Media):[^\[\]]*(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]", re.I)
_LINK = re.compile(r"\[\[([^\[\]|]*)(?:\|([^\[\]]*))?\]\]")
_EXT_LINK = re.compile(r"\[(?:https?:)?//\S+\s+([^\]]+)\]")
_EMPHASIS = re.compile(r"'{2,}")
_WS = re.compile(r"\s+")
_HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
_SUMMARY = re.compile(r"\{\{\s*recipe\s*summary\b", re.I)


def _strip_templates(text: str) -> str:
    """Remove ``{{...}}`` templates, nested ones included."""
    out, depth, i = [], 0, 0
    while i < len(text):
        if text.startswith("{{", i):
            depth += 1
            i += 2
        elif text.startswith("}}", i) and depth:
            depth -= 1
            i += 2
        else:
            if not depth:
                out.append(text[i])
            i += 1
    return "".join(out)


def clean_markup(text: str) -> str:
    text = _REF.sub("", text)
    text = _BR.sub("; ", text)
    text = _strip_templates(text)
    text = _FILE_LINK.sub("", text)
    text = _LINK.sub(lambda m: m.group(2) if m.group(2) is not None else m.group(1), text)
    text = _EXT_LINK.sub(r"\1", text)
    text = _TAG.sub("", text)
    text = _EMPHASIS.sub("", text)
    text = html.unescape(text).replace("\xa0", " ")
    return _WS.sub(" ", text).strip(" ;")


def _sections(wikitext: str) -> dict[str, list[str]]:
    """Map a level-2 heading (lowercase) to its lines, subsections included."""
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in wikitext.splitlines():
        m = _HEADING.match(line.strip())
        if m and len(m.group(1)) == 2:
            current = sections.setdefault(m.group(2).lower(), [])
        elif m:
            continue
        elif current is not None:
            current.append(line)
    return sections


def _summary_body(wikitext: str) -> str | None:
    m = _SUMMARY.search(wikitext)
    if not m:
        return None
    depth, i = 0, m.start()
    while i < len(wikitext):
        if wikitext.startswith("{{", i):
            depth += 1
            i += 2
        elif wikitext.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                return wikitext[m.start() + 2 : i - 2]
        else:
            i += 1
    return wikitext[m.start() + 2 :]


def _summary_fields(wikitext: str) -> dict[str, str]:
    body = _summary_body(wikitext)
    if body is None:
        return {}
    parts, buf, brackets = [], [], 0
    for i, ch in enumerate(body):
        if body.startswith("[[", i):
            brackets += 1
        elif body.startswith("]]", i):
            brackets -= 1
        if ch == "|" and brackets <= 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    fields: dict[str, str] = {}
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        if sep:
            fields[key.strip().lower()] = value
    return fields


def page_url(title: str) -> str:
    return WIKI_BASE + "wiki/" + quote(title.replace(" ", "_"), safe=":/(),'!*-._~")


def _items(lines: list[str], marker: str) -> tuple[str, ...]:
    out = []
    for line in lines:
        s = line.lstrip()
        if s.startswith(marker):
            text = clean_markup(s.lstrip(marker))
            if text:
                out.append(text)
    return tuple(out)


def parse_page(record: dict, retrieved_on: str) -> SourceRecipe | None:
    title = record["title"]
    text = record["wikitext"]
    if not title.startswith("Cookbook:") or title.startswith("Cookbook:Policy/"):
        return None
    if text.lstrip().upper().startswith("#REDIRECT"):
        return None
    sections = _sections(text)
    ingredients = _items(sections.get("ingredients", []), "*")
    if not ingredients:
        return None
    steps: tuple[str, ...] = ()
    for name in _STEP_HEADINGS:
        if name in sections:
            steps = _items(sections[name], "#")
            break
    fields = _summary_fields(text)

    def field(key: str) -> str | None:
        return (clean_markup(fields[key]) or None) if key in fields else None

    return SourceRecipe(
        recipe_id=f"wb-{record['page_id']}",
        title=title.removeprefix("Cookbook:"),
        page=title,
        url=page_url(title),
        revision_id=record["revision_id"],
        revision_url=f"{WIKI_BASE}w/index.php?oldid={record['revision_id']}",
        licence=LICENCE,
        retrieved_on=retrieved_on,
        ingredient_lines=ingredients,
        steps=steps,
        category=field("category"),
        servings=field("servings"),
        time=field("time"),
    )
