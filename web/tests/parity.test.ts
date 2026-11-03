// Golden parity: the TypeScript engine must match the Python reference on every case.
// Scores within 1e-9, order and counts exact.

import { readFileSync } from "node:fs";
import { resolve as resolvePath } from "node:path";
import { describe, expect, it } from "vitest";
import { Engine } from "../src/engine";
import { tokens } from "../src/normalize";
import type { Answer, AnswerRequest, Core, RecipeResult } from "../src/types";

const root = resolvePath(__dirname, "..", "..");
const read = <T>(rel: string): T =>
  JSON.parse(readFileSync(resolvePath(root, rel), "utf8")) as T;

interface Golden {
  cases: { name: string; request: AnswerRequest; answer: Answer }[];
  tokens: { input: string; tokens: string[] }[];
  names: { names: string[]; ids: string[]; unknown: string[] }[];
}

const golden = read<Golden>("tests/golden/answer_cases.json");
const engine = new Engine(read<Core>("tests/fixtures/pack/core.v1.json"));

function expectSameResults(got: RecipeResult[], want: RecipeResult[]): void {
  expect(got.map((r) => r.recipe_id)).toEqual(want.map((r) => r.recipe_id));
  got.forEach((r, k) => {
    const w = want[k]!;
    expect(Math.abs(r.score - w.score)).toBeLessThanOrEqual(1e-9);
    expect({ ...r, score: 0 }).toEqual({ ...w, score: 0 });
  });
}

describe("golden answer cases", () => {
  it("has at least 200 cases", () => {
    expect(golden.cases.length).toBeGreaterThanOrEqual(200);
  });

  for (const c of golden.cases) {
    it(c.name, () => {
      const got = engine.answer(c.request);
      for (const key of ["make_now", "one_away", "two_away"] as const) {
        expect(got.groups[key].count).toBe(c.answer.groups[key].count);
        expectSameResults(got.groups[key].items, c.answer.groups[key].items);
      }
      expect(got.unlocks).toEqual(c.answer.unlocks);
      expect(got.blockers).toEqual(c.answer.blockers);
      expect(got.unknown_pantry).toEqual(c.answer.unknown_pantry);
      expect(got.pack).toEqual(c.answer.pack);
    });
  }
});

describe("canonical tokens", () => {
  for (const t of golden.tokens) {
    it(JSON.stringify(t.input), () => expect(tokens(t.input)).toEqual(t.tokens));
  }
});

describe("name resolution", () => {
  for (const n of golden.names) {
    it(JSON.stringify(n.names), () => expect(engine.resolve(n.names)).toEqual({
      ids: n.ids,
      unknown: n.unknown,
    }));
  }
});

describe("suggest", () => {
  it("ranks prefix matches first and finds synonyms", () => {
    expect(engine.suggest("egg").map((s) => s.id)[0]).toBe("egg");
    expect(engine.suggest("oliv")[0]?.id).toBe("olive_oil");
    expect(engine.suggest("")).toEqual([]);
  });
});
