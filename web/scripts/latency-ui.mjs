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
//
// Real phone: connect to Chrome on an Android phone and measure there, with no CPU throttle.
//   adb reverse tcp:4175 tcp:4175; adb forward tcp:9222 localabstract:chrome_devtools_remote
//   adb shell svc power stayon usb   (a screen that turns off stops animation frames, and every timing then reads about 1.7 s; undo with: adb shell svc power stayon false)
//   open http://localhost:4175/ in Chrome on the phone, then:
//   node scripts/latency-ui.mjs --url http://localhost:4175/ --cdp http://127.0.0.1:9222 --device "<model>" --out latency_ui_device.json
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
const CDP = arg("cdp", ""); // a real browser to measure on. The throttle is then off: the device is the limit.
const DEVICE = arg("device", "");
const DISCARD = 2; // the first runs of each cell are dropped. Each run opens a new page, so this is not a warm-up.
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
function timedNow(page, kind) {
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

/** Let the work left over from the last action finish, so it cannot fall inside the next timing. */
async function timed(page, kind) {
  await page.evaluate(
    () => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(done, 300)))),
  );
  return timedNow(page, kind);
}

let loadRetries = 0;
/** Open the page. A load that fails is retried once: it is a harness fault, and no timing has started. */
async function open(browser) {
  try {
    return await openOnce(browser);
  } catch (e) {
    loadRetries++;
    console.error(`page did not load, retrying once: ${String(e.message).split(/\r?\n/)[0]}`);
    return openOnce(browser);
  }
}

async function openOnce(browser) {
  if (CDP) return openOnDevice(browser);
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

/** Reuse the one tab of the phone. The saved kitchen is cleared through the page, so each run starts empty. */
async function openOnDevice(browser) {
  const page = browser.contexts()[0].pages().find((p) => p.url().startsWith(URL_.replace(/\/$/, ""))) ?? browser.contexts()[0].pages()[0];
  const t0 = Date.now();
  await page.goto(URL_, { waitUntil: "load" });
  await page.locator("#edit-kitchen, #ingredient").first().waitFor({ state: "attached" });
  // On a phone the kitchen is a summary once it holds items. Page clicks go through the DOM, because the sticky bar can cover a button.
  if (await page.locator("#edit-kitchen").isVisible()) await page.locator("#edit-kitchen").evaluate((e) => e.click());
  const input = page.getByLabel("Add what you have");
  await input.waitFor();
  if ((await page.locator(".pantry .have").count()) > 0) {
    await page.getByRole("button", { name: "Clear all" }).evaluate((e) => e.click());
    await page.waitForFunction(() => document.querySelectorAll(".pantry .have").length === 0);
  }
  return { page, input, ready: Date.now() - t0 };
}

async function fill(page, input, names) {
  for (const n of names) {
    const was = await count(page);
    await input.fill(n);
    await input.press("Enter");
    await page.waitForFunction(([w]) => document.querySelectorAll(".pantry .have").length > w, [was], { timeout: 8000 });
  }
}

const browser = CDP ? await chromium.connectOverCDP(CDP) : await chromium.launch();
const deviceInfo = CDP
  ? await (async () => {
      const pg = browser.contexts()[0].pages()[0];
      return pg.evaluate(() => ({ user_agent: navigator.userAgent, width: innerWidth, height: innerHeight, dpr: devicePixelRatio, cores: navigator.hardwareConcurrency }));
    })()
  : null;
const results = {}; // `${action}@${size}` -> ms[]
const skipped = {};
const pasteNew = {}; // paste start size -> how many of the 20 pasted items are new
const loads = [];
const commits = {}; // same keys: ms until the kitchen grew, before the two frames
const push = (key, r, ms) => {
  if (r < DISCARD) return;
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
      if (!CDP) await page.close();
    }
  }
  for (const size of PASTE_SIZES) {
    for (let r = 0; r < RUNS; r++) {
      const { page, input, ready } = await open(browser);
      loads.push(ready);
      const have = shuffled(POOL).slice(0, size);
      await fill(page, input, have);
      const pasteButton = page.getByRole("button", { name: "Paste a list" });
      if (CDP) await pasteButton.evaluate((e) => e.click()); // the sticky bar of a phone can cover the button
      else await pasteButton.click();
      // A pasted list of 20 items, split over commas and new lines, with quantities on some.
      const items = shuffled(POOL).map((n, i) => (i % 5 === 0 ? `2 ${n}` : n));
      pasteNew[size] = POOL.filter((n) => !have.includes(n)).length; // the other pasted items are already in the kitchen
      await page.getByLabel("Paste ingredients").fill(items.slice(0, 10).join(", ") + "\n" + items.slice(10).join(" and "));
      push(`paste@${size}`, r, await timed(page, "paste"));
      if (!CDP) await page.close();
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
// Hash the script bundle the server really served, so the result shows which build ran.
const html = await (await fetch(URL_)).text();
const bundleRef = /assets\/index-[^"']+\.js/.exec(html)?.[0];
const bundle = bundleRef ? Buffer.from(await (await fetch(new URL(bundleRef, URL_))).arrayBuffer()) : null;
const core = readFileSync(join(web, "public", "pack", "core.v2.json.gz"));
const config = {
  cpu_throttle_rate: CDP ? 0 : RATE,
  device: CDP ? { name: DEVICE || "unnamed", ...deviceInfo } : null,
  runs_per_cell: RUNS,
  discarded_first_runs: DISCARD,
  start_sizes: SIZES,
  paste_start_sizes: PASTE_SIZES,
  cache: CDP ? "browser default" : "disabled",
  served_bundle: bundleRef ? `${bundleRef} sha256 ${createHash("sha256").update(bundle).digest("hex")}` : "not found",
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
  paste_new_items: pasteNew,
  settle_before_each_timing_ms: 300,
  load_retries: loadRetries,
  page_ready_ms: stats(loads),
  limits:
    (CDP ? "Real phone over USB debugging, Chrome as installed, page served from the laptop through adb reverse, so there is no network delay. One phone, one state of charge and temperature. " : "Headless Chromium on a development laptop, local preview server, CPU throttle only. ") + "Page-ready time is unthrottled. The end of each timing is two animation frames after the kitchen grows, so it is more than the engine call alone. One run" + (CDP ? ". On a phone, page-ready time also includes the reset of the saved kitchen." : ", no real phone."),
};
writeResult(
  join(root, "results", OUT),
  {
    label: "MEASURED",
    what: "Action to painted frame on the one-screen page: chip tap, Enter on a typed item, paste of about 20 items, 'Add' on the ticket. Production build, real pack v2, " + (CDP ? `real phone (${DEVICE || "unnamed"}), no throttle` : "headless Chromium, CPU throttled"),
    command: `node web/scripts/latency-ui.mjs --url ${URL_} ${CDP ? `--cdp ${CDP} --device "${DEVICE}"` : `--rate ${RATE}`} --runs ${RUNS} --seed ${SEED} --out ${OUT}`,
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
