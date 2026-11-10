// Measure the one-screen page under a CPU throttle. There is no "See recipes" click any more, so
// each action is timed from the moment its event is dispatched to the next painted frame after the
// kitchen has grown. The answer is computed in the same render, so this covers the engine call,
// the render and two animation frames.
//
// Actions: tap a "Tap to add" chip, press Enter on a typed item, paste a list of about 20 items,
// and press "Add <item>" on the "Buy 1 thing" ticket.
//
// Run it on a production build with the real pack:
//   npm run pack:real && npm run build && npm run preview -- --host 127.0.0.1 --port 4175 --strictPort
//   node scripts/latency-ui.mjs [--url http://127.0.0.1:4175/] [--rate 6] [--runs 15] [--seed 1] [--out latency_ui.json]
// Pass line: p95 <= 200 ms for every action and start size. Goal: 100 ms.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { writeResult } from "./result.mjs";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const root = resolve(web, "..");
const arg = (n, d) => {
  const i = process.argv.indexOf(`--${n}`);
  return i > 0 ? process.argv[i + 1] : d;
};
const URL_ = arg("url", "http://127.0.0.1:4175/");
const RATE = Number(arg("rate", 6));
const RUNS = Number(arg("runs", 15));
const SEED = Number(arg("seed", 1));
const OUT = arg("out", "latency_ui.json");
const WARMUP = 2;
const PASS_MS = 200;
const GOAL_MS = 100;
const SIZES = [3, 8, 15]; // kitchen size before the timed actions
const PASTE_SIZES = [0, 8];
const POOL = ["egg", "flour", "milk", "butter", "sugar", "onion", "garlic", "tomato", "chicken", "rice", "potato", "cheese", "carrot", "lemon", "beef", "pasta", "apple", "honey", "spinach", "basil"];
const TYPED = ["mushroom", "cinnamon", "yogurt", "bread", "pork", "lime"]; // typed with Enter, never in POOL

let s = SEED >>> 0;
const rnd = () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 2 ** 32);
const shuffled = (xs) => xs.map((x) => [rnd(), x]).sort((a, b) => a[0] - b[0]).map((p) => p[1]);
const stats = (xs) => {
  const a = [...xs].sort((x, y) => x - y);
  const at = (q) => a[Math.min(a.length - 1, Math.floor(q * a.length))];
  return { n: a.length, p50: at(0.5), p95: at(0.95), max: a[a.length - 1] };
};

const count = (page) => page.locator(".pantry .have").count();

/** Dispatch one action inside the page. Resolves with {commit, paint}: ms until the kitchen grew, and until two frames after. */
function timed(page, kind) {
  return page.evaluate(
    (k) =>
      new Promise((resolveMs, reject) => {
        const have = () => document.querySelectorAll(".pantry .have").length;
        const before = have();
        const obs = new MutationObserver(() => {
          if (have() > before) {
            obs.disconnect();
            const commit = performance.now() - t;
            requestAnimationFrame(() => requestAnimationFrame(() => resolveMs({ commit, paint: performance.now() - t })));
          }
        });
        obs.observe(document.body, { childList: true, subtree: true });
        setTimeout(() => {
          obs.disconnect();
          reject(new Error(`no change after ${k}`));
        }, 8000);
        const t = performance.now();
        if (k === "chip") {
          document.querySelector(".quick .add").click();
        } else if (k === "enter") {
          document.querySelector("#ingredient").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
        } else if (k === "ticket") {
          document.querySelector(".ticket .btn").click();
        } else if (k === "paste") {
          [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Add these").click();
        }
      }),
    kind,
  );
}

async function open(browser) {
  const page = await browser.newPage();
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  const t0 = Date.now();
  await page.goto(URL_);
  const input = page.getByLabel("Add what you have");
  await input.waitFor();
  const ready = Date.now() - t0;
  // The throttle starts after load. It models a slow device for the interaction, not the download.
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: RATE });
  return { page, input, ready };
}

async function fill(page, input, names) {
  for (const n of names) {
    const was = await count(page);
    await input.fill(n);
    await input.press("Enter");
    await page.waitForFunction(([w]) => document.querySelectorAll(".pantry .have").length > w, [was], { timeout: 8000 });
  }
}

const browser = await chromium.launch();
const results = {}; // `${action}@${size}` -> ms[]
const skipped = {};
const loads = [];
const commits = {}; // same keys: ms until the kitchen grew, before the two frames
const push = (key, r, ms) => {
  if (r < WARMUP) return;
  (results[key] ??= []).push(ms.paint);
  (commits[key] ??= []).push(ms.commit);
};

try {
  for (const size of SIZES) {
    for (let r = 0; r < RUNS; r++) {
      const { page, input, ready } = await open(browser);
      loads.push(ready);
      await fill(page, input, shuffled(POOL).slice(0, size));
      // Chip: the chip list comes from the engine, so it needs a kitchen to suggest from.
      if ((await page.locator(".quick .add").count()) > 0) push(`chip@${size}`, r, await timed(page, "chip"));
      else skipped[`chip@${size}`] = (skipped[`chip@${size}`] ?? 0) + 1;
      await input.fill(TYPED[r % TYPED.length]);
      push(`enter@${size}`, r, await timed(page, "enter"));
      if ((await page.locator(".ticket .btn").count()) > 0) push(`ticket@${size}`, r, await timed(page, "ticket"));
      else skipped[`ticket@${size}`] = (skipped[`ticket@${size}`] ?? 0) + 1;
      await page.close();
    }
  }
  for (const size of PASTE_SIZES) {
    for (let r = 0; r < RUNS; r++) {
      const { page, input, ready } = await open(browser);
      loads.push(ready);
      await fill(page, input, shuffled(POOL).slice(0, size));
      await page.getByRole("button", { name: "Paste a list" }).click();
      // A pasted list of 20 items, split over commas and new lines, with quantities on some.
      const items = shuffled(POOL).map((n, i) => (i % 5 === 0 ? `2 ${n}` : n));
      await page.getByLabel("Paste ingredients").fill(items.slice(0, 10).join(", ") + "\n" + items.slice(10).join(" and "));
      push(`paste@${size}`, r, await timed(page, "paste"));
      await page.close();
    }
  }
} finally {
  await browser.close();
}

const keys = Object.keys(results);
const byKey = Object.fromEntries(keys.map((k) => [k, stats(results[k])]));
const over = keys.filter((k) => byKey[k].p95 > PASS_MS);
const metrics = keys.flatMap((k) => {
  const [action, size] = k.split("@");
  const st = byKey[k];
  return [["latency_p50_ms", st.p50], ["latency_p95_ms", st.p95], ["latency_max_ms", st.max]].map(([name, value]) => ({
    name,
    role: "latency",
    depends_on: [],
    arm: null,
    split: "all",
    n: st.n,
    value,
    group: { action, start_size: Number(size) },
  }));
});
const core = readFileSync(join(web, "public", "pack", "core.v2.json.gz"));
const config = {
  cpu_throttle_rate: RATE,
  runs_per_cell: RUNS,
  warmup_runs: WARMUP,
  start_sizes: SIZES,
  paste_start_sizes: PASTE_SIZES,
  cache: "disabled",
  pass_p95_ms: PASS_MS,
  goal_p95_ms: GOAL_MS,
  pool: POOL,
  typed: TYPED,
};
const raw = {
  url: URL_,
  config,
  by_cell: byKey,
  commit_by_cell: Object.fromEntries(keys.map((k) => [k, stats(commits[k])])),
  cells_over_pass_line: over,
  cells_over_goal: keys.filter((k) => byKey[k].p95 > GOAL_MS),
  skipped_runs: skipped,
  page_ready_ms: stats(loads),
  limits:
    "Headless Chromium on a development laptop, local preview server, CPU throttle only. Page-ready time is unthrottled. The end of each timing is two animation frames after the kitchen grows, so it is more than the engine call alone. One run, no real phone.",
};
writeResult(
  join(root, "results", OUT),
  {
    label: "MEASURED",
    what: "Action to painted frame on the one-screen page: chip tap, Enter on a typed item, paste of about 20 items, 'Add' on the ticket. Production build, real pack v2, headless Chromium, CPU throttled",
    command: `node web/scripts/latency-ui.mjs --url ${URL_} --rate ${RATE} --runs ${RUNS} --seed ${SEED} --out ${OUT}`,
    config,
    seed: SEED,
    corpus_fingerprint: `core.v2.json.gz sha256 ${createHash("sha256").update(core).digest("hex")}`,
    arms: [],
    metrics,
    comparisons: [],
    raw,
  },
  root,
);
console.log(JSON.stringify({ by_cell: byKey, commit_by_cell: raw.commit_by_cell, over_pass_line: over, over_goal: raw.cells_over_goal, skipped }, null, 2));
process.exit(over.length ? 1 : 0);
