// Measure the deployed bundle on a real Android phone, with no CPU throttle.
// Setup (the script runs the first two steps for you):
//   adb forward tcp:9222 localabstract:chrome_devtools_remote
//   Chrome must be running on the phone with USB debugging on.
// For each run: open the page, add the seeded pantry, click "See recipes", and time the click until
// the results heading is on screen and two animation frames have passed. Same scenario as
// latency-live.mjs. The phone does the work. The laptop only sends commands over CDP.
// Usage: node scripts/latency-device.mjs [--url URL] [--runs 15] [--seed 1] [--port 9222] [--out FILE]
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const arg = (n, d) => {
  const i = process.argv.indexOf(`--${n}`);
  return i > 0 ? process.argv[i + 1] : d;
};
const URL_ = arg("url", "https://aritr-codes.github.io/PantryChef/");
const RUNS = Number(arg("runs", 15));
const SEED = Number(arg("seed", 1));
const PORT = Number(arg("port", 9222));
const OUT = arg("out", "m1_latency_device.raw.json");
const ADB = process.env.ADB ?? "adb";
const SIZES = [3, 5, 8, 12];
const WARMUP = 2;
const NAMES = ["egg", "flour", "milk", "butter", "sugar", "onion", "garlic", "tomato", "chicken", "rice", "potato", "cheese", "carrot", "lemon", "beef", "pasta", "apple", "honey"];

let s = SEED >>> 0;
const rnd = () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 2 ** 32);
const adb = (...a) => execFileSync(ADB, a, { encoding: "utf8" }).trim();
const git = (...a) => execFileSync("git", a, { cwd: root, encoding: "utf8" }).trim();
const stats = (xs) => {
  const a = [...xs].sort((x, y) => x - y);
  const at = (q) => a[Math.min(a.length - 1, Math.floor(q * a.length))];
  return { n: a.length, p50: at(0.5), p95: at(0.95), max: a[a.length - 1] };
};
const prop = (k) => adb("shell", "getprop", k);
const grep = (cmd, re) => (adb("shell", cmd).split("\n").find((l) => re.test(l)) ?? "").trim();
const facts = () => ({
  battery_level: Number(grep("dumpsys battery", /^\s*level:/).split(":")[1]),
  battery_temp_tenths_c: Number(grep("dumpsys battery", /^\s*temperature:/).split(":")[1]),
  thermal_status: Number(grep("dumpsys thermalservice", /^Thermal Status:/).split(":")[1]),
  low_power_mode: adb("shell", "settings", "get", "global", "low_power"),
});

const device = {
  model: prop("ro.product.model"),
  manufacturer: prop("ro.product.manufacturer"),
  android: prop("ro.build.version.release"),
  sdk: prop("ro.build.version.sdk"),
  screen: adb("shell", "wm", "size"),
  density: adb("shell", "wm", "density"),
  refresh: grep("dumpsys display", /mRefreshRate|refreshRate=/).slice(0, 120),
};
const before = facts();
adb("forward", `tcp:${PORT}`, "localabstract:chrome_devtools_remote");
const browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`);
const version = browser.version();
const context = browser.contexts()[0];
// A tab made by newPage() on Android Chrome did not render, so reuse the open tab (started by `am start`).
const page = context.pages().find((p) => p.url().startsWith(URL_)) ?? (await context.newPage());
await page.bringToFront();
const cdp = await context.newCDPSession(page);
await cdp.send("Network.enable");
await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });

const bySize = {};
const raw = {};
const loads = [];
const perRunFacts = [];
for (const size of SIZES) {
  const times = [];
  const all = [];
  for (let r = 0; r < RUNS; r++) {
    const t0 = Date.now();
    await page.goto(URL_, { waitUntil: "load" });
    const input = page.getByLabel("Type an ingredient");
    await input.waitFor();
    loads.push(Date.now() - t0);
    const pick = [...NAMES].sort(() => rnd() - 0.5).slice(0, size);
    for (const n of pick) {
      await input.fill(n);
      await input.press("Enter");
    }
    const ms = await page.evaluate(
      () =>
        new Promise((resolveMs) => {
          const btn = [...document.querySelectorAll("button")].find((b) => /See recipes/.test(b.textContent ?? ""));
          const t = performance.now();
          new MutationObserver((_, obs) => {
            if (document.querySelector("#results-h")) {
              obs.disconnect();
              requestAnimationFrame(() => requestAnimationFrame(() => resolveMs(performance.now() - t)));
            }
          }).observe(document.body, { childList: true, subtree: true });
          btn.click();
        }),
    );
    all.push(ms);
    console.error(`size ${size} run ${r}: ${ms.toFixed(1)} ms`);
    if (r >= WARMUP) times.push(ms);
  }
  raw[size] = all;
  bySize[size] = stats(times);
  perRunFacts.push({ after_size: size, ...facts() });
  // Keep what we have, in case the phone is unplugged part-way.
  mkdirSync(join(root, "results"), { recursive: true });
  writeFileSync(join(root, "results", OUT + ".partial"), JSON.stringify({ raw_ms: raw, bySize }, null, 2));
}
const after = facts();
adb("forward", "--remove", `tcp:${PORT}`);

const out = {
  device,
  chrome: version,
  before,
  after,
  per_size_facts: perRunFacts,
  url: URL_,
  commit: git("rev-parse", "HEAD"),
  config: { runs_per_size: RUNS, warmup_runs: WARMUP, pantry_sizes: SIZES, cache: "disabled", cpu_throttle: "none", pool: NAMES },
  seed: SEED,
  bySize,
  raw_ms: raw,
  page_ready_ms: stats(loads),
  command: `node web/scripts/latency-device.mjs --url ${URL_} --runs ${RUNS} --seed ${SEED} --port ${PORT} --out ${OUT}`,
};
mkdirSync(join(root, "results"), { recursive: true });
writeFileSync(join(root, "results", OUT), JSON.stringify(out, null, 2) + "\n");
console.log(JSON.stringify({ device, chrome: version, before, after, bySize, page_ready_ms: out.page_ready_ms }, null, 2));
process.exit(0);
