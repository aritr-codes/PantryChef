// Read a typed or pasted list of ingredients. Commas, semicolons, new lines and "and" split items.
// This only prepares names. The engine decides what a name means (engine.resolve).

type Resolve = (names: string[]) => { ids: string[]; unknown: string[] };

const BREAK = /[,;\n\r]+/;
const AND = /\s+and\s+/i;

/** Upper-case the first letter, for a name at the start of a sentence ("Banana added."). */
export function cap(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function clean(part: string): string {
  return part.replace(/^\s*[-*•]\s+/, "").trim();
}

/** Split a list into names. */
export function splitList(text: string): string[] {
  return text
    .split(BREAK)
    .flatMap((p) => clean(p).split(AND))
    .map(clean)
    .filter(Boolean);
}

const UNIT =
  /^(?:cups?|tbsps?|tsps?|tablespoons?|teaspoons?|g|kg|ml|l|oz|lbs?|pounds?|cloves?|cans?|pinch(?:es)?|bunch(?:es)?|slices?)\b\s+(?:of\s+)?(?=\S)/i;

/**
 * Remove a leading quantity, a unit that follows a quantity, or an article:
 * "2 onions" becomes "onions", "1/2 cup flour" becomes "flour". A unit with nothing after it stays.
 */
export function stripLead(name: string): string {
  const qty = /^[\d\s/.]+/.exec(name);
  const rest = qty ? name.slice(qty[0].length).replace(UNIT, "") : name;
  return rest.replace(/^(a|an|some|the)\s+/i, "").trim();
}

/** Undo for "Clear all": the snapshot comes back, and items added since are kept. */
export function mergeRestore(before: string[], current: string[]): string[] {
  return [...before, ...current.filter((x) => !before.includes(x))];
}

function same(list: string[], name: string): boolean {
  return list.some((x) => x.toLowerCase() === name.toLowerCase());
}

/**
 * Resolve a whole list. A part between commas is tried as one name first, so a name that
 * contains "and" still works. Then it is split on "and". A name that fails is tried again
 * without its quantity.
 */
export function resolveList(text: string, resolve: Resolve): { ids: string[]; unknown: string[] } {
  const ids: string[] = [];
  const unknown: string[] = [];
  const one = (name: string): boolean => {
    for (const candidate of [name, stripLead(name)]) {
      if (!candidate) continue;
      // One name can mean several ids ("s&p" is salt and black pepper), so keep every id.
      const hits = resolve([candidate]).ids;
      if (hits.length > 0) {
        for (const hit of hits) if (!ids.includes(hit)) ids.push(hit);
        return true;
      }
    }
    return false;
  };
  for (const raw of text.split(BREAK)) {
    const part = clean(raw);
    if (!part || one(part)) continue;
    for (const name of part.split(AND).map(clean).filter(Boolean)) {
      if (!one(name) && !same(unknown, stripLead(name) || name)) unknown.push(stripLead(name) || name);
    }
  }
  return { ids, unknown };
}
