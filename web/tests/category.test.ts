// The category icon is a name heuristic. A wrong icon is worse than no icon, so the traps matter.

import { readFileSync } from "node:fs";
import { resolve as resolvePath } from "node:path";
import { describe, expect, it } from "vitest";
import { type IconKey, categoryOf } from "../src/category";
import { resolveExamples } from "../src/examples";

const names = (() => {
  // Ingredient names from the real table (the second CSV column). The names have no commas.
  const csv = readFileSync(resolvePath(__dirname, "..", "..", "data", "ingredients", "ingredients.csv"), "utf8");
  return csv
    .split(/\r?\n/)
    .slice(1)
    .filter(Boolean)
    .map((line) => line.split(",")[1] as string);
})();

describe("categoryOf", () => {
  const cases: [string, IconKey | null][] = [
    // plain cases
    ["egg", "egg"],
    ["milk", "dairy"],
    ["butter", "dairy"],
    ["cheddar", "dairy"],
    ["sour cream", "dairy"],
    ["lemon", "fruit"],
    ["tomato", "fruit"],
    ["bell pepper", "fruit"],
    ["onion", "root"],
    ["sweet potato", "root"],
    ["spinach", "veg"],
    ["mushroom", "mushroom"],
    ["basil", "herb"],
    ["rice", "grain"],
    ["bread flour", "grain"],
    ["bread", "bread"],
    ["chicken", "meat"],
    ["ground beef", "meat"],
    ["tuna", "fish"],
    ["lentil", "legume"],
    ["soy sauce", "bottle"],
    ["olive oil", "bottle"],
    ["tofu", "tofu"],
    // traps: the name holds a word of another group
    ["coconut milk", "tin"],
    ["condensed milk", "tin"],
    ["peanut butter", null],
    ["almond butter", null],
    ["butternut squash", "veg"],
    ["buttermilk", "dairy"],
    ["cream of tartar", null],
    ["eggplant", "veg"],
    ["egg noodle", "grain"],
    ["ground ginger", null],
    ["ginger", "root"],
    ["lemongrass", "herb"],
    ["lemon pepper", null],
    ["black pepper", null],
    ["celery seed", null],
    ["celery", "veg"],
    ["green bean", "veg"],
    ["bean sprout", "veg"],
    ["split pea", "legume"],
    ["pea", "veg"],
    ["rice vinegar", "bottle"],
    ["oyster sauce", "bottle"],
    ["fish sauce", "bottle"],
    ["hamburger bun", "bread"],
    ["canned tomato", "tin"],
    ["tomato paste", "tin"],
    ["chicken stock", "tin"],
    ["baking soda", null],
    ["baking powder", null],
    ["corn syrup", "bottle"],
    ["cornstarch", null],
    ["applesauce", null],
    ["oily fish", "fish"],
    // no match means no icon
    ["water", null],
    ["water chestnut", null],
    ["olive", null],
    ["saffron", null],
    ["cumin", null],
    ["zzqxw", null],
    ["", null],
  ];
  for (const [name, want] of cases) {
    it(`${JSON.stringify(name)} gives ${want}`, () => expect(categoryOf(name)).toBe(want));
  }

  it("ignores case and spaces", () => {
    expect(categoryOf("  Egg ")).toBe("egg");
  });

  it("gives an icon to some of the real table, and none to spices and other plain names", () => {
    expect(names.length).toBeGreaterThan(300);
    const mapped = names.filter((n) => categoryOf(n) !== null);
    expect(mapped.length / names.length).toBeGreaterThan(0.4);
    for (const spice of ["paprika", "cumin", "turmeric", "cinnamon", "nutmeg", "saffron", "water", "salt", "mustard", "vanilla", "yeast", "gelatin"]) {
      expect(categoryOf(spice), spice).toBeNull();
    }
  });
});

describe("resolveExamples", () => {
  const known: Record<string, string> = { egg: "egg", milk: "milk", butter: "butter", rice: "rice", onion: "onion" };
  const resolve = (ns: string[]) => ({ ids: ns.filter((n) => n in known).map((n) => known[n] as string) });
  const defs = [
    { name: "Many", names: ["egg", "milk", "butter", "ghost", "rice"] },
    { name: "Few", names: ["egg", "ghost", "phantom", "milk"] },
    { name: "Exactly three", names: ["egg", "milk", "onion", "ghost"] },
  ];
  it("keeps the ids that resolve, skips names that do not, and hides an example with fewer than 3", () => {
    expect(resolveExamples(resolve, defs)).toEqual([
      { name: "Many", ids: ["egg", "milk", "butter", "rice"] },
      { name: "Exactly three", ids: ["egg", "milk", "onion"] },
    ]);
  });
  it("never repeats an id", () => {
    expect(resolveExamples(resolve, [{ name: "Dup", names: ["egg", "egg", "milk", "onion"] }])[0]?.ids).toEqual(["egg", "milk", "onion"]);
  });
});
