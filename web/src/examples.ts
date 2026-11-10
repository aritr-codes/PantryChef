// Starter kitchens. Each one is a list of ingredient NAMES. The engine turns names into ids at run
// time, so the page never holds an id. A name that does not resolve is skipped without a message,
// and an example with fewer than MIN names that resolve is hidden.

export interface ExampleDef {
  name: string;
  names: string[];
}
export interface Example {
  name: string;
  ids: string[];
}

export const EXAMPLES: ExampleDef[] = [
  {
    name: "After a big shop",
    names: ["egg", "milk", "butter", "tomato", "onion", "garlic", "potato", "cheddar", "chicken", "lemon"],
  },
  { name: "Student cupboard", names: ["pasta", "tuna", "tomato", "onion", "cheddar", "rice", "bread", "egg"] },
  { name: "A quick egg supper", names: ["egg", "rice", "onion", "butter", "soy sauce"] },
];

const MIN = 3;

export function resolveExamples(
  resolve: (names: string[]) => { ids: string[] },
  defs: ExampleDef[] = EXAMPLES,
): Example[] {
  const out: Example[] = [];
  for (const d of defs) {
    const ids: string[] = [];
    for (const n of d.names) {
      const id = resolve([n]).ids[0];
      if (id !== undefined && !ids.includes(id)) ids.push(id);
    }
    if (ids.length >= MIN) out.push({ name: d.name, ids });
  }
  return out;
}
