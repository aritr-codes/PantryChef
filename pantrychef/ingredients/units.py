"""Rule-based quantity and unit extraction.

Design choices:
- Ranges ("1-2", "1 to 2") take the FIRST number for determinism.
- Mixed numbers ("1 1/2") and unicode fractions ("½") are supported.
"""

from __future__ import annotations

import re
from fractions import Fraction

UNICODE_FRACTIONS = {
    "½": "1/2",
    "⅓": "1/3",
    "⅔": "2/3",
    "¼": "1/4",
    "¾": "3/4",
    "⅕": "1/5",
    "⅖": "2/5",
    "⅗": "3/5",
    "⅘": "4/5",
    "⅙": "1/6",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}

UNITS = {
    "cup": "cup",
    "cups": "cup",
    "c": "cup",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "tbsp": "tbsp",
    "tbs": "tbsp",
    "tbsps": "tbsp",
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "tsp": "tsp",
    "tsps": "tsp",
    "gram": "g",
    "grams": "g",
    "g": "g",
    "kg": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "ounce": "oz",
    "ounces": "oz",
    "oz": "oz",
    "pound": "lb",
    "pounds": "lb",
    "lb": "lb",
    "lbs": "lb",
    "milliliter": "ml",
    "milliliters": "ml",
    "ml": "ml",
    "liter": "l",
    "liters": "l",
    "litre": "l",
    "litres": "l",
    "l": "l",
    "pinch": "pinch",
    "dash": "dash",
    "clove": "clove",
    "cloves": "clove",
    "can": "can",
    "cans": "can",
    "package": "package",
    "packages": "package",
    "pkg": "package",
    "slice": "slice",
    "slices": "slice",
    "stick": "stick",
    "sticks": "stick",
    "quart": "quart",
    "quarts": "quart",
    "pint": "pint",
    "pints": "pint",
}

_NUM = re.compile(r"^\s*(\d+\s+\d+/\d+|\d+/\d+|\d+\.\d+|\d+)")
_RANGE_TAIL = re.compile(r"^\s*(?:-|to)\s*(?:\d+\.\d+|\d+/\d+|\d+)")


def replace_unicode_fractions(text: str) -> str:
    for u, a in UNICODE_FRACTIONS.items():
        text = text.replace(u, " " + a + " ")
    return text


def _to_float(token: str) -> float:
    token = token.strip()
    if len(token.split()) > 1:  # mixed number "1 1/2" (any whitespace)
        whole, frac = token.split(maxsplit=1)
        return float(whole) + float(Fraction(frac.strip()))
    if "/" in token:
        return float(Fraction(token))
    return float(token)


def parse_quantity(text: str) -> tuple[float | None, str]:
    text = replace_unicode_fractions(text)
    # NFKC fraction slash; en and em dash as a range dash
    text = text.replace("⁄", "/").replace("–", "-").replace("—", "-")
    m = _NUM.match(text)
    if not m:
        return None, text.strip()
    qty = _to_float(m.group(1))
    rest = text[m.end() :]
    rest = _RANGE_TAIL.sub("", rest)
    return qty, rest.strip()


_SIZE_PAREN = re.compile(r"^\s*\([^)]*\)\s*")


def parse_unit(text: str) -> tuple[str | None, str]:
    """Split a leading unit off ``text``. A size note such as "(14 oz) can" is skipped."""
    sized = _SIZE_PAREN.sub("", text, count=1)
    if sized != text:
        unit, rest = parse_unit(sized)
        if unit:
            return unit, rest
    parts = text.strip().split()
    if not parts:
        return None, ""
    first = parts[0].lower().rstrip(".")
    if first in UNITS:
        return UNITS[first], " ".join(parts[1:]).strip()
    return None, text.strip()
