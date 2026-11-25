// Pinned ordering of the shipped rule (M4, plan 11.2). The Python twin is tests/test_rank_pinned.py.
// The real-pack part skips when build/pack is absent. Re-pin tests/golden/rank_pinned.json on purpose.

import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { resolve as resolvePath } from "node:path";
import { gunzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { Engine } from "../src/engine";
import type { Core } from "../src/types";

const root = resolvePath(__dirname, "..", "..");
interface Pinned {
  fixture: { pantries: { name: string; pantry: string[]; top5: string[] }[] };
  real_pack: { core_sha256: string; pantries: { names: string[]; pantry: string[]; top5: string[] }[] };
}
const pinned = JSON.parse(readFileSync(resolvePath(root, "tests/golden/rank_pinned.json"), "utf8")) as Pinned;

function top5(engine: Engine, pantry: string[]): string[] {
  const got = engine.answer({ pantry, staples: [...engine.defaultStaples], diet: null, limit: 1000, unknown_names: [] });
  return (["make_now", "one_away", "two_away"] as const)
    .flatMap((g) => got.groups[g].items.map((r) => r.recipe_id))
    .slice(0, 5);
}

describe("pinned ordering, fixture pack", () => {
  const engine = new Engine(
    JSON.parse(readFileSync(resolvePath(root, "tests/fixtures/pack/core.v2.json"), "utf8")) as Core,
  );
  for (const c of pinned.fixture.pantries) {
    it(c.name, () => expect(top5(engine, c.pantry)).toEqual(c.top5));
  }
});

const file = process.env.PANTRY_REAL_PACK ?? resolvePath(root, "build", "pack", "core.v2.json.gz");
describe.skipIf(!existsSync(file))("pinned ordering, real pack", () => {
  const bytes = existsSync(file) ? readFileSync(file) : Buffer.alloc(0);
  it("is the pinned pack", () => {
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(pinned.real_pack.core_sha256);
  });
  for (const c of pinned.real_pack.pantries) {
    it(c.names.join(","), () => {
      const engine = new Engine(JSON.parse(gunzipSync(bytes).toString("utf8")) as Core);
      expect(top5(engine, c.pantry)).toEqual(c.top5);
    });
  }
});
