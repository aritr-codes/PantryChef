// Measure the deployed production bundle end to end, under a CPU throttle.
// For each run: load the page, add the pantry, click "See recipes", and time the click until the
// results heading is on screen and the next frame is painted. That covers answer() and rendering.
// Usage: node scripts/latency-live.mjs [--url URL] [--rate 6] [--runs 15] [--seed 1] [--out FILE]
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { latencyMetrics, writeResult } from "./result.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const arg = (n, d) => {
  const i = process.argv.indexOf(`--${n}`);
  return i > 0 ? process.argv[i + 1] : d;
};
const URL_ = arg("url", "https://aritr-codes.github.io/PantryChef/");
const RATE = Number(arg("rate", 6));
const RUNS = Number(arg("runs", 15));
const SEED = Number(arg("seed", 1));
const OUT = arg("out", "m1_latency_live.json");
const SIZES = [3, 5, 8, 12];
const NAMES = ["egg", "flour", "milk", "butter", "sugar", "onion", "garlic", "tomato", "chicken", "rice", "potato", "cheese", "carrot", "lemon", "beef", "pasta", "apple", "honey"];

let s = SEED >>> 0;
const rnd = () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 2 ** 32);
const stats = (xs) => {
  const a = [...xs].sort((x, y) => x - y);
  const at = (q) => a[Math.min(a.length - 1, Math.floor(q * a.length))];
  return { n: a.length, p50: at(0.5), p95: at(0.95), max: a[a.length - 1] };
};

const browser = await chromium.launch();
const bySize = {};
const loads = [];
for (const size of SIZES) {
  const times = [];
  for (let r = 0; r < RUNS; r++) {
    const page = await browser.newPage();
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Network.enable");
    await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
    const t0 = Date.now();
    await page.goto(URL_);
    const input = page.getByLabel("Type an ingredient");
    await input.waitFor();
    loads.push(Date.now() - t0);
    // The throttle starts after load. It models a slow device for the interaction, not the download.
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: RATE });
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
    if (r >= 2) times.push(ms); // the first two runs per size are warm-up
    await page.close();
  }
  bySize[size] = stats(times);
}
await browser.close();
const config = { cpu_throttle_rate: RATE, runs_per_size: RUNS, warmup_runs: 2, pantry_sizes: SIZES, cache: "disabled", pool: NAMES };
const raw = {
  url: URL_,
  config,
  metrics: { bySize, pack_page_ready_ms: stats(loads), threshold_ms: 100, sizes_over_threshold: Object.entries(bySize).filter(([, v]) => v.p95 >= 100).map(([k]) => Number(k)) },
  limits: "Page-ready time is unthrottled. Network time is real, so page-ready time varies with the connection. Includes render time and two animation frames, which is more than answer() alone. One run.",
};
writeResult(
  join(root, "results", OUT),
  {
    label: "MEASURED",
    what: "Click on 'See recipes' to results painted, deployed production bundle, headless Chromium, CPU throttled",
    command: `node web/scripts/latency-live.mjs --url ${URL_} --rate ${RATE} --runs ${RUNS} --seed ${SEED} --out ${OUT}`,
    config,
    seed: SEED,
    corpus_fingerprint: `none recorded (deployed bundle: ${URL_})`,
    arms: [],
    metrics: latencyMetrics(bySize),
    comparisons: [],
    raw,
  },
  root,
);
console.log(JSON.stringify(raw.metrics, null, 2));
