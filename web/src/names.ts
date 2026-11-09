// Port of pantrychef/ingredients/names.py: resolve one typed pantry name to ingredient ids.
// Steps, first hit wins: exact, split, contained, fuzzy. The golden `resolve` cases in
// tests/golden/answer_cases.json keep the two engines together.

import { tokens } from "./normalize";
import { parseQuantity, parseUnit, type Words } from "./units";

export type Step = "exact" | "split" | "contained" | "fuzzy" | "none";
export interface NameMatch {
  ids: string[];
  step: Step;
}

const NONE: NameMatch = { ids: [], step: "none" };
// A "/" between two digits is a fraction, not a separator. After `clean`, spaces are single.
const SPLIT = / *(?:[,&]|(?<![0-9])\/|\/(?![0-9])) *| and /;
// Every character that Python or JavaScript counts as white space, so `\s` never decides anything.
const BLANKS = /[\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+/g;
const MIN_FUZZY_LEN = 4; // shorter names never match fuzzily
const LONG_FUZZY_LEN = 8; // from this length the limit is 2, below it 1

type Keys = Record<string, string>;

// `keys` comes from JSON, so "constructor" and "__proto__" must not read the prototype.
const lookup = (keys: Keys, key: string): string | undefined =>
  Object.hasOwn(keys, key) ? keys[key] : undefined;

function clean(text: string): string {
  return text
    .normalize("NFKC")
    .toLowerCase()
    .replace(/(?![0-9])\p{Nd}/gu, " ") // the quantity parser reads ASCII digits only
    .replace(BLANKS, " ")
    .replace(/^ +| +$/g, "");
}

/** A size, container or preparation word, or an "-ed" word ("-seed" words are food). */
export function isModifier(token: string, words: Words): boolean {
  return (
    words.size.has(token) ||
    words.container.has(token) ||
    words.prep.has(token) ||
    (token.endsWith("ed") && token.length > 4 && !token.endsWith("seed"))
  );
}

/** Damerau-Levenshtein distance (optimal string alignment: a swap of neighbours costs 1). */
export function editDistance(a: string, b: string): number {
  let prev2: number[] = [];
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      let d = Math.min(prev[j]! + 1, cur[j - 1]! + 1, prev[j - 1]! + (a[i - 1] === b[j - 1] ? 0 : 1));
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        d = Math.min(d, prev2[j - 2]! + 1);
      }
      cur.push(d);
    }
    prev2 = prev;
    prev = cur;
  }
  return prev[b.length]!;
}

function exact(text: string, keys: Keys): NameMatch | null {
  const toks = tokens(text);
  const hit = toks.length ? lookup(keys, toks.join(" ")) : undefined;
  return hit ? { ids: [hit], step: "exact" } : null;
}

/**
 * Tokens left after the quantity and the unit, and whether a lone unit word is the name. "2 cloves"
 * has nothing after the unit, so the unit word is the name. It may reach the exact and contained
 * steps only, never the fuzzy step ("2 pints" must not become "mint").
 */
function strippedTokens(text: string, words: Words): { toks: string[]; loneUnit: boolean } {
  const [, rest] = parseQuantity(text);
  const [unit, after] = parseUnit(rest, words.units);
  if (unit !== null && tokens(after).length === 0) return { toks: tokens(rest), loneUnit: true };
  return { toks: tokens(after), loneUnit: false };
}

function contained(toks: string[], keys: Keys, words: Words): NameMatch | null {
  // Recomputed on every call: O(keys), and the spread fails near 100k keys. Cache it if the table grows.
  const longest = Math.max(0, ...Object.keys(keys).map((k) => k.split(" ").length));
  const ids: string[] = [];
  const covered = toks.map(() => false);
  let i = 0;
  while (i < toks.length) {
    let n = Math.min(longest, toks.length - i);
    let hit: string | undefined;
    for (; n > 0; n--) {
      hit = lookup(keys, toks.slice(i, i + n).join(" "));
      if (hit) break;
    }
    if (hit) {
      covered.fill(true, i, i + n);
      if (!ids.includes(hit)) ids.push(hit);
      i += n;
    } else {
      i += 1;
    }
  }
  if (!ids.length || toks.some((t, k) => !covered[k] && !isModifier(t, words))) return null;
  return { ids, step: "contained" };
}

function fuzzy(toks: string[], keys: Keys, words: Words): NameMatch | null {
  const kept = toks.filter((t) => !isModifier(t, words));
  const name = kept.join(" ");
  // Too short, or only unit words ("pint", "dashes"): not a name to guess at.
  if (name.length < MIN_FUZZY_LEN || kept.every((t) => words.units.has(t))) return null;
  const limit = name.length >= LONG_FUZZY_LEN ? 2 : 1;
  let best = limit + 1;
  let ids: string[] = [];
  for (const [key, id] of Object.entries(keys)) {
    if (Math.abs(key.length - name.length) > limit) continue;
    const d = editDistance(name, key);
    if (d < best) {
      best = d;
      ids = [id];
    } else if (d === best) {
      ids.push(id);
    }
  }
  return best <= limit && ids.length === 1 ? { ids: [ids[0]!], step: "fuzzy" } : null;
}

/** Steps 1, 3 and 4 on one piece of text. */
function leaf(text: string, keys: Keys, words: Words): NameMatch {
  const { toks, loneUnit } = strippedTokens(text, words);
  return (
    exact(text, keys) ??
    contained(toks, keys, words) ??
    (loneUnit ? null : fuzzy(toks, keys, words)) ??
    NONE
  );
}

/** Resolve one typed name. `keys` maps a key (canonical tokens joined by a space) to an id. */
export function resolveName(text: string, keys: Keys, words: Words): NameMatch {
  const t = clean(text);
  const hit = exact(t, keys);
  if (hit) return hit;
  const parts = t.split(SPLIT).filter((p) => p !== "");
  if (parts.length > 1) {
    const ids: string[] = [];
    let all = true;
    for (const part of parts) {
      const m = leaf(part, keys, words);
      if (m.step === "none") {
        all = false;
        break;
      }
      for (const id of m.ids) if (!ids.includes(id)) ids.push(id);
    }
    if (all) return { ids, step: "split" };
  }
  return leaf(t, keys, words);
}
