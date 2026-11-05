// Node writer for the PantryChef results file (schema 1). Same shape as pantrychef/eval/results.py.
// Contract: results/schema.v1.json. No dependency: validate() checks required keys and types by hand.
// The metric/arm registry lives in Python (tests/eval load_result checks every file there).
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import os from "node:os";

const MAX_DIRTY_PATHS = 20;
const LABELS = ["MEASURED", "ESTIMATE", "HYPOTHESIS"];
const ROLES = ["selection", "sanity", "product", "latency"];
const SPLITS = ["dev", "test", "all"];

const git = (root, ...args) => execFileSync("git", args, { cwd: root, encoding: "utf8" });

// Returns { commit, dirty, dirty_paths }. Paths in `exclude` and files under results/ do not count.
const CODE_DIRS = ["pantrychef/", "scripts/", "tests/", "web/src/", "web/scripts/", "data/eval/", "data/ingredients/", "kaggle/"]; // same list as results.py

export function gitFacts(root, exclude = []) {
  const commit = git(root, "rev-parse", "HEAD").trim();
  const skip = new Set(exclude.map((p) => resolve(p).toLowerCase()));
  const entries = git(root, "status", "--porcelain", "-z", "--untracked-files=all").split("\0");
  const paths = [];
  for (let i = 0; i < entries.length; i++) {
    const e = entries[i];
    if (e.length < 4) continue;
    if (e[0] === "R" || e[0] === "C") i++; // the next entry is the old name
    const p = e.slice(3);
    if (skip.has(resolve(root, p).toLowerCase()) || p.startsWith("results/")) continue;
    if (e.startsWith("??") && !CODE_DIRS.some((d) => p.startsWith(d))) continue; // scratch files outside the code folders
    paths.push(p);
  }
  return { commit, dirty: paths.length > 0, dirty_paths: paths.slice(0, MAX_DIRTY_PATHS) };
}

const isObj = (x) => typeof x === "object" && x !== null && !Array.isArray(x);
const isNum = (x) => typeof x === "number" && Number.isFinite(x);
const isInt = (x) => Number.isInteger(x);
const isStrs = (x) => Array.isArray(x) && x.every((s) => typeof s === "string");
const fail = (where, what) => {
  throw new Error(`${where}: ${what}`);
};
const need = (obj, keys, where) => {
  if (!isObj(obj)) fail(where, "must be an object");
  for (const k of keys) if (!(k in obj)) fail(where, `missing key '${k}'`);
};

export function validate(doc) {
  need(doc, ["schema", "label", "what", "command", "commit", "dirty", "dirty_paths", "config", "seed", "corpus_fingerprint", "arms", "metrics", "comparisons", "environment"], "doc");
  if (doc.schema !== 1) fail("schema", "must be 1");
  if (!LABELS.includes(doc.label)) fail("label", `must be one of ${LABELS}`);
  for (const k of ["what", "command", "corpus_fingerprint"]) if (typeof doc[k] !== "string" || doc[k] === "") fail(k, "must be a non-empty string");
  if (typeof doc.commit !== "string" || !/^[0-9a-f]{40}$/.test(doc.commit)) fail("commit", "must be 40 lowercase hex characters");
  if (typeof doc.dirty !== "boolean") fail("dirty", "must be a boolean");
  if (!isStrs(doc.dirty_paths) || doc.dirty_paths.length > MAX_DIRTY_PATHS) fail("dirty_paths", `must be a list of at most ${MAX_DIRTY_PATHS} strings`);
  if (!isObj(doc.config)) fail("config", "must be an object");
  if (!isInt(doc.seed)) fail("seed", "must be an integer");
  if (!isObj(doc.environment)) fail("environment", "must be an object");
  if ("raw" in doc && !isObj(doc.raw)) fail("raw", "must be an object");
  for (const k of ["arms", "metrics", "comparisons"]) if (!Array.isArray(doc[k])) fail(k, "must be a list");
  for (const a of doc.arms) {
    need(a, ["name", "features_used"], "arm");
    if (typeof a.name !== "string" || !isStrs(a.features_used)) fail("arm", "bad name or features_used");
  }
  for (const m of doc.metrics) {
    need(m, ["name", "role", "depends_on", "arm", "split", "n", "value"], "metric");
    const w = `metric '${m.name}'`;
    if (typeof m.name !== "string") fail(w, "name must be a string");
    if (!ROLES.includes(m.role)) fail(w, `role must be one of ${ROLES}`);
    if (!isStrs(m.depends_on)) fail(w, "depends_on must be a list of strings");
    if (m.arm !== null && typeof m.arm !== "string") fail(w, "arm must be a string or null");
    if (!SPLITS.includes(m.split)) fail(w, `split must be one of ${SPLITS}`);
    if (!isInt(m.n) || m.n < 0) fail(w, "n must be an integer >= 0");
    if (!isNum(m.value)) fail(w, "value must be a number");
    if ("group" in m && !isObj(m.group)) fail(w, "group must be an object");
    if ("ci" in m) {
      need(m.ci, ["lo", "hi", "level", "method", "n_clusters"], `${w} ci`);
      if (![m.ci.lo, m.ci.hi, m.ci.level].every(isNum) || typeof m.ci.method !== "string" || !isInt(m.ci.n_clusters)) fail(`${w} ci`, "bad types");
    }
  }
  for (const c of doc.comparisons) {
    need(c, ["metric", "a", "b", "split", "diff", "ci"], "comparison");
    if (!SPLITS.includes(c.split) || !isNum(c.diff) || !isObj(c.ci)) fail("comparison", "bad split, diff or ci");
  }
}

const sortKeys = (x) =>
  Array.isArray(x) ? x.map(sortKeys) : isObj(x) ? Object.fromEntries(Object.keys(x).sort().map((k) => [k, sortKeys(x[k])])) : x;

// Fills schema, commit, dirty, dirty_paths and environment; validates; writes sorted JSON (indent 2, LF).
export function writeResult(path, doc, root) {
  path = resolve(path);
  const out = { ...doc, schema: 1, ...gitFacts(root, [path]) };
  out.environment = { ...(doc.environment ?? {}), node: process.version, platform: `${os.type()} ${os.release()} (${process.platform})` };
  validate(out);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(sortKeys(out), null, 2) + "\n");
  return out;
}

// Latency stats ({n, p50, p95, max}) per pantry size -> schema metrics. The names are in the Python registry.
export function latencyMetrics(bySize) {
  return Object.entries(bySize).flatMap(([size, s]) =>
    [["latency_p50_ms", s.p50], ["latency_p95_ms", s.p95], ["latency_max_ms", s.max]].map(([name, value]) => ({
      name, role: "latency", depends_on: [], arm: null, split: "all", n: s.n, value, group: { pantry_size: Number(size) },
    })),
  );
}
