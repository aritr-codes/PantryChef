// result.mjs writes the same shape as pantrychef/eval/results.py. The committed sample is read by pytest.
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
// @ts-expect-error plain .mjs helper without types
import { gitFacts, validate, writeResult } from "../scripts/result.mjs";

const root = resolve(__dirname, "..", "..");
const SAMPLE = join(root, "tests", "fixtures", "results", "node_sample.json");
const REQUIRED = ["schema", "label", "what", "command", "commit", "dirty", "dirty_paths", "config", "seed", "corpus_fingerprint", "arms", "metrics", "comparisons", "environment"];

const input = () => ({
  label: "MEASURED",
  what: "sample written by result.mjs",
  command: "npm test (web/tests/result.test.ts)",
  config: { note: "fixed sample" },
  seed: 1,
  corpus_fingerprint: "none",
  arms: [],
  metrics: [{ name: "latency_p50_ms", role: "latency", depends_on: [], arm: null, split: "all", n: 3, value: 12.5, group: { pantry_size: 3 } }],
  comparisons: [],
});

describe("result.mjs", () => {
  it("writes every required key, sorted, LF, trailing newline", () => {
    const out = join(mkdtempSync(join(tmpdir(), "pc-")), "x.json");
    writeResult(out, input(), root);
    const text = readFileSync(out, "utf8");
    const doc = JSON.parse(text);
    for (const k of REQUIRED) expect(doc).toHaveProperty(k);
    expect(doc.schema).toBe(1);
    expect(doc.commit).toMatch(/^[0-9a-f]{40}$/);
    expect(text.endsWith("}\n")).toBe(true);
    expect(text).not.toContain("\r");
    expect(Object.keys(doc)).toEqual([...Object.keys(doc)].sort());
    expect(() => validate(doc)).not.toThrow();
  });

  it("rejects a bad document", () => {
    const out = join(mkdtempSync(join(tmpdir(), "pc-")), "x.json");
    expect(() => writeResult(out, { ...input(), label: "GUESS" }, root)).toThrow(/label/);
    const { seed: _seed, ...noSeed } = input();
    expect(() => writeResult(out, noSeed, root)).toThrow(/seed/);
  });

  it("gitFacts finds the commit and caps dirty_paths", () => {
    const g = gitFacts(root);
    expect(g.commit).toMatch(/^[0-9a-f]{40}$/);
    expect(g.dirty_paths.length).toBeLessThanOrEqual(20);
  });

  it("the committed sample has not drifted from what result.mjs writes", () => {
    const out = join(mkdtempSync(join(tmpdir(), "pc-")), "x.json");
    const fresh = writeResult(out, input(), root);
    const sample = JSON.parse(readFileSync(SAMPLE, "utf8"));
    expect(() => validate(sample)).not.toThrow();
    const strip = (d: Record<string, unknown>) => {
      const { commit: _c, dirty: _d, dirty_paths: _p, environment: _e, ...rest } = d;
      return { ...rest, env_keys: Object.keys((d.environment as object) ?? {}) };
    };
    expect(strip(sample)).toEqual(strip(fresh));
  });
});

// Run `UPDATE_SAMPLE=1 npx vitest run result` to rewrite the committed sample after a deliberate change.
if (process.env.UPDATE_SAMPLE) writeResult(SAMPLE, input(), root);
