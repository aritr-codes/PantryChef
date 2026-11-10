// Pure UI logic: list parsing, on-device persistence, the "Buy one thing" ticket text.
// The vitest environment is node, so storage is passed in as a small fake.

import { readFileSync } from "node:fs";
import { resolve as resolvePath } from "node:path";
import { describe, expect, it } from "vitest";
import { Engine } from "../src/engine";
import { mergeRestore, resolveList, splitList, stripLead } from "../src/list";
import { recipeSlots } from "../src/slots";
import { load, save, storageWorks } from "../src/store";
import { ticket, ticketText } from "../src/ticket";
import type { Core } from "../src/types";

const root = resolvePath(__dirname, "..", "..");
const core = JSON.parse(readFileSync(resolvePath(root, "tests/fixtures/pack/core.v1.json"), "utf8")) as Core;
const engine = new Engine(core);

function fakeStorage(seed: Record<string, string> = {}) {
  const data = { ...seed };
  return {
    data,
    getItem: (k: string) => data[k] ?? null,
    setItem: (k: string, v: string) => void (data[k] = v),
    removeItem: (k: string) => void delete data[k],
  };
}
const blocked = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
  removeItem: () => {
    throw new Error("blocked");
  },
};

describe("splitList", () => {
  it("splits on commas, semicolons, new lines and the word and", () => {
    expect(splitList("eggs, milk; flour\nsugar and butter")).toEqual(["eggs", "milk", "flour", "sugar", "butter"]);
  });
  it("drops empty parts and bullets, and keeps words that merely contain and", () => {
    expect(splitList(" - eggs,, \n* sand\n")).toEqual(["eggs", "sand"]);
    expect(splitList("")).toEqual([]);
    expect(splitList("  ")).toEqual([]);
  });
});

describe("stripLead", () => {
  it("removes a leading quantity and article", () => {
    expect(stripLead("2 onions")).toBe("onions");
    expect(stripLead("1/2 cup")).toBe("cup");
    expect(stripLead("1/2 cup flour")).toBe("flour");
    expect(stripLead("2 cloves of garlic")).toBe("garlic");
    expect(stripLead("2 cloves")).toBe("cloves");
    expect(stripLead("cloves")).toBe("cloves");
    expect(stripLead("a lemon")).toBe("lemon");
    expect(stripLead("some rice")).toBe("rice");
    expect(stripLead("onion")).toBe("onion");
  });
});

describe("mergeRestore", () => {
  it("puts the snapshot back and keeps what was added since, without repeats", () => {
    expect(mergeRestore(["a", "b"], ["c", "a"])).toEqual(["a", "b", "c"]);
    expect(mergeRestore(["a"], [])).toEqual(["a"]);
  });
});

describe("resolveList", () => {
  it("reads a pasted list against the engine, and keeps unknown words", () => {
    const r = resolveList("flour, 2 eggs and zzqxw, flour", (n) => engine.resolve(n));
    expect(r.ids).toEqual(["flour", "egg"]);
    expect(r.unknown).toEqual(["zzqxw"]);
  });
  it("tries the whole comma part before splitting on and", () => {
    const seen: string[] = [];
    const fake = (names: string[]) => {
      seen.push(...names);
      return names[0] === "salt and pepper" ? { ids: ["sp"], unknown: [] } : { ids: [], unknown: names };
    };
    expect(resolveList("salt and pepper", fake).ids).toEqual(["sp"]);
    expect(seen).toEqual(["salt and pepper"]);
  });
});

describe("saved kitchen", () => {
  const known = new Set(["egg", "flour", "salt"]);
  it("round-trips ids and the staple switches that are off, nothing else", () => {
    const s = fakeStorage();
    expect(save({ ids: ["egg", "flour"], staplesOff: ["salt"] }, s)).toBe(true);
    expect(Object.keys(s.data)).toHaveLength(1);
    expect(JSON.parse(Object.values(s.data)[0] as string)).toEqual({ v: 1, ids: ["egg", "flour"], staplesOff: ["salt"] });
    expect(load(known, s)).toEqual({ ids: ["egg", "flour"], staplesOff: ["salt"] });
  });
  it("drops ids the pack no longer knows, and repeats", () => {
    const s = fakeStorage({ k: "x" });
    save({ ids: ["egg", "gone", "egg"], staplesOff: [] }, s);
    expect(load(known, s)?.ids).toEqual(["egg"]);
  });
  it("ignores damaged data", () => {
    for (const raw of ["not json", "null", "[]", '{"v":2,"ids":[]}', '{"v":1,"ids":"egg"}', '{"v":1,"ids":[1],"staplesOff":[]}']) {
      const s = fakeStorage();
      s.setItem("pantrychef.kitchen.v1", raw);
      expect(load(known, s), raw).toBeNull();
    }
  });
  it("returns nothing when there is no saved kitchen", () => {
    expect(load(known, fakeStorage())).toBeNull();
  });
  it("works with storage blocked, and with no storage at all", () => {
    expect(save({ ids: ["egg"], staplesOff: [] }, blocked)).toBe(false);
    expect(load(known, blocked)).toBeNull();
    expect(storageWorks(blocked)).toBe(false);
    expect(save({ ids: ["egg"], staplesOff: [] }, null)).toBe(false);
    expect(load(known, null)).toBeNull();
    expect(storageWorks(null)).toBe(false);
    expect(storageWorks(fakeStorage())).toBe(true);
  });
});

describe("Buy one thing ticket", () => {
  const req = (pantry: string[]) => ({ pantry, staples: [], diet: null, limit: 10, unknown_names: [] });
  it("is absent when nothing is one item away", () => {
    expect(ticket(engine.answer(req([])))).toBeNull();
  });
  it("names recipes from the returned one-away items that miss exactly that item", () => {
    const answer = engine.answer(req(["flour", "egg", "milk"]));
    const t = ticket(answer);
    expect(t).not.toBeNull();
    const top = answer.unlocks[0]!;
    expect(t!.id).toBe(top.ingredient_id);
    expect(t!.recipes).toBe(top.recipes);
    expect(t!.titles.length).toBeLessThanOrEqual(3);
    for (const title of t!.titles) {
      const item = answer.groups.one_away.items.find((i) => i.title === title)!;
      expect(item.missing).toHaveLength(1);
      expect(item.missing[0]!.options).toContain(top.ingredient_id);
    }
    expect(t!.more).toBe(top.recipes - t!.titles.length);
  });
});

describe("recipeSlots", () => {
  const ln = (o: string[], opt = false, r = true) => ({ t: "x", o, opt, r });
  const name = (id: string) => id.toUpperCase();
  it("makes have, need and assumed slots and counts unread lines", () => {
    const lines = [ln(["a"]), ln(["b", "c"]), ln(["s"]), ln(["a"]), ln(["z"], true), ln([], false, false)];
    const out = recipeSlots(lines, name, new Set(["a"]), new Set(["s"]));
    expect(out.slots).toEqual([
      { kind: "have", name: "A" },
      { kind: "need", name: "B or C" },
      { kind: "assumed", name: "S" },
    ]);
    expect(out.check).toBe(1);
  });
});

describe("ticketText", () => {
  const t = (titles: string[], recipes: number) => ({ id: "x", name: "x", recipes, titles, more: recipes - titles.length });
  it("lists up to three titles and counts the rest", () => {
    expect(ticketText(t(["A"], 1))).toBe("With x, you can cook 1 more: A.");
    expect(ticketText(t(["A", "B"], 2))).toBe("With x, you can cook 2 more: A and B.");
    expect(ticketText(t(["A", "B", "C"], 3))).toBe("With x, you can cook 3 more: A, B and C.");
    expect(ticketText(t(["A", "B", "C"], 5))).toBe("With x, you can cook 5 more: A, B, C and 2 more.");
  });
  it("still says the full count when no title is on the page yet", () => {
    expect(ticketText(t([], 4))).toBe("With x, you can cook 4 more.");
  });
});