// Read a typed or pasted list of ingredients. Commas, semicolons, new lines and "and" split items.
// This only prepares names. The engine decides what a name means (engine.resolve).

type Resolve = (names: string[]) => { ids: string[]; unknown: string[] };

const BREAK = /[,;\n\r]+/;
const AND = /\s+and\s+/i;

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

/** Remove a leading quantity or article: "2 onions" becomes "onions". */
export function stripLead(name: string): string {
  return name
    .replace(/^[\d\s/.]+/, "")
    .replace(/^(a|an|some|the)\s+/i, "")
    .trim();
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
      const hit = resolve([candidate]).ids[0];
      if (hit !== undefined) {
        if (!ids.includes(hit)) ids.push(hit);
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
