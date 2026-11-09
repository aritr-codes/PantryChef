// Port of pantrychef/ingredients/units.py (`parse_quantity`, `parse_unit`) and of the `Words`
// word lists in table.py. The golden name cases in tests/golden/answer_cases.json keep the two
// together. Unit words come from `core.words`, the same file the Python engine reads.

import type { WordsJson } from "./types";

export interface Words {
  units: ReadonlyMap<string, string>;
  size: ReadonlySet<string>;
  container: ReadonlySet<string>;
  prep: ReadonlySet<string>;
}

/** Word lists from a pack core. A core from before pack v2 has none, so every list is empty. */
export function makeWords(raw?: WordsJson): Words {
  return {
    units: new Map(Object.entries(raw?.units ?? {})),
    size: new Set(raw?.size),
    container: new Set(raw?.container),
    prep: new Set(raw?.prep),
  };
}

const UNICODE_FRACTIONS: [string, string][] = [
  ["½", "1/2"],
  ["⅓", "1/3"],
  ["⅔", "2/3"],
  ["¼", "1/4"],
  ["¾", "3/4"],
  ["⅕", "1/5"],
  ["⅖", "2/5"],
  ["⅗", "3/5"],
  ["⅘", "4/5"],
  ["⅙", "1/6"],
  ["⅛", "1/8"],
  ["⅜", "3/8"],
  ["⅝", "5/8"],
  ["⅞", "7/8"],
];

const NUM = /^\s*(\d+\s+\d+\/\d+|\d+\/\d+|\d+\.\d+|\d+)/;
const RANGE_TAIL = /^\s*(?:-|to)\s*(?:\d+\.\d+|\d+\/\d+|\d+)/;
const SIZE_PAREN = /^\s*\([^)]*\)\s*/;

function fraction(text: string): number {
  const [top, bottom] = text.split("/").map(Number);
  if (!bottom) throw new RangeError("zero denominator"); // Python raises ZeroDivisionError
  return top! / bottom;
}

function toFloat(token: string): number {
  const t = token.trim();
  const parts = t.split(/\s+/);
  if (parts.length > 1) return Number(parts[0]) + fraction(parts[1]!); // mixed number "1 1/2"
  return t.includes("/") ? fraction(t) : Number(t);
}

/** Split a leading quantity off `text`. A range takes its first number. */
export function parseQuantity(text: string): [number | null, string] {
  let t = text;
  for (const [u, a] of UNICODE_FRACTIONS) t = t.replaceAll(u, ` ${a} `);
  // NFKC fraction slash; en and em dash as a range dash
  t = t.replaceAll("⁄", "/").replaceAll("–", "-").replaceAll("—", "-");
  const m = NUM.exec(t);
  if (!m) return [null, t.trim()];
  let qty: number;
  try {
    qty = toFloat(m[1]!);
  } catch {
    return [null, t.trim()]; // "1/0 cup" is not a quantity
  }
  return [qty, t.slice(m[0].length).replace(RANGE_TAIL, "").trim()];
}

/** Split a leading unit off `text`. A size note such as "(14 oz) can" is skipped. */
export function parseUnit(
  text: string,
  units: ReadonlyMap<string, string>,
): [string | null, string] {
  const sized = text.replace(SIZE_PAREN, "");
  if (sized !== text) {
    const [unit, rest] = parseUnit(sized, units);
    if (unit) return [unit, rest];
  }
  const t = text.trim();
  if (t === "") return [null, ""];
  const parts = t.split(/\s+/);
  const unit = units.get(parts[0]!.toLowerCase().replace(/\.+$/, ""));
  if (unit !== undefined) return [unit, parts.slice(1).join(" ").trim()];
  return [null, t];
}
