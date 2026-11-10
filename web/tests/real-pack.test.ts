// Checks on the real pack. The pack is not in git, so these skip when it is absent. To run them
// from a worktree, point PANTRY_REAL_PACK at the file (build/pack/core.v2.json.gz in the main checkout).

import { existsSync, readFileSync } from "node:fs";
import { resolve as resolvePath } from "node:path";
import { gunzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { categoryOf } from "../src/category";
import { Engine } from "../src/engine";
import { resolveExamples } from "../src/examples";
import { readyAfter } from "../src/ticket";
import type { Core } from "../src/types";

const file = process.env.PANTRY_REAL_PACK ?? resolvePath(__dirname, "..", "..", "build", "pack", "core.v2.json.gz");
const have = existsSync(file);
const core = have ? (JSON.parse(gunzipSync(readFileSync(file)).toString("utf8")) as Core) : null;

describe.skipIf(!have)(`real pack (${have ? "found" : "build/pack/core.v2.json.gz is absent"})`, () => {
  it("gives no icon to names that hold a food word but are another thing", () => {
    const wrong = [
      "cocoa butter", "apple butter", "butter chicken masala", "meat masala", "celery salt", "garlic salt",
      "onion salt", "onion soup mix", "potato starch", "makrut lime leaf", "banana leaf", "grape leaf",
      "avocado leaf", "cassava leaf", "corn husk", "orange blossom water", "bitter melon",
      "coconut milk powder", "wine yeast", "coconut yogurt", "soy yogurt",
    ];
    const names = new Set(core!.ingredients.map((i) => i.name.toLowerCase()));
    expect(names.size).toBeGreaterThan(500);
    for (const n of wrong) if (names.has(n)) expect(categoryOf(n), n).toBeNull();
    // Over the whole table: no name with these words gets a food icon. Two cases are meant: a herb
    // leaf is a herb, and a tin of soup is a tin.
    for (const n of names) {
      if (/\b(leaf|leaves|husk|salt|masala|starch|soup|blossom|yeast)\b/.test(n) && !/\b(bay|curry|pandan|mint|basil) (leaf|leaves)\b|\bcondensed soup\b/.test(n)) {
        expect(categoryOf(n), n).toBeNull();
      }
    }
  });

  it("the ticket gain is the real number of recipes that open, for every starter kitchen", () => {
    const engine = new Engine(core!);
    const staples = engine.defaultStaples;
    const examples = resolveExamples((names) => engine.resolve(names));
    expect(examples.length).toBeGreaterThan(0);
    for (const ex of examples) {
      const req = { pantry: ex.ids, staples, diet: null, limit: 10, unknown_names: [] };
      const a = engine.answer(req);
      const top = a.unlocks[0];
      if (!top) continue;
      const now = a.groups.make_now.count;
      const after = readyAfter(engine, ex.ids, staples, top.ingredient_id);
      const real = engine.answer({ ...req, pantry: [...ex.ids, top.ingredient_id] }).groups.make_now.count;
      expect(after, ex.name).toBe(real);
      // The engine's unlock count is a floor, and the real gain is at least that.
      expect(after - now, ex.name).toBeGreaterThanOrEqual(top.recipes);
    }
  });
});
