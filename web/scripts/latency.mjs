// Measure answer() latency in Chromium under a CPU throttle, on the real pack.
// Usage: npm run pack:real && node scripts/latency.mjs [--rate 6] [--runs 40] [--seed 1]
// Writes ../results/m1_latency.json. The dev server is used so the page can import engine.ts.
import { execFileSync, spawn } from "node:child_process";
import { createServer } from "node:http";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const web = resolve(here, "..");
const root = resolve(web, "..");
const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? Number(process.argv[i + 1]) : dflt;
};
const RATE = arg("rate", 6);
const RUNS = arg("runs", 40);
const SEED = arg("seed", 1);
const OUT = process.argv.includes("--out") ? process.argv[process.argv.indexOf("--out") + 1] : "m1_latency.json";
const PORT = 5199;
const PACK_PORT = 5198;
const SIZES = [3, 5, 8, 12];

const git = (...a) => execFileSync("git", a, { cwd: root, encoding: "utf8" }).trim();
const manifest = JSON.parse(readFileSync(join(root, "build", "pack", "manifest.v1.json"), "utf8"));

const server = spawn(process.execPath, [join(web, "node_modules", "vite", "bin", "vite.js"), "--port", String(PORT), "--strictPort", "--host", "127.0.0.1"], {
  cwd: web,
  stdio: "ignore",
});
// The Vite dev server corrupts .gz files, so a small static server serves the pack. CORS lets the
// dev-server page fetch it.
const gz = createServer((req, res) => {
  const name = (req.url ?? "").split("?")[0].replace(/^\/+/, "");
  if (!/^(core|text)\.v1\.json\.gz$/.test(name)) return res.writeHead(404).end();
  res.writeHead(200, { "Content-Type": "application/gzip", "Access-Control-Allow-Origin": "*" });
  res.end(readFileSync(join(root, "build", "pack", name)));
});
gz.listen(PACK_PORT, "127.0.0.1");
const stop = () => {
  server.kill();
  gz.close();
};
process.on("exit", stop);

async function waitUp() {
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`http://127.0.0.1:${PORT}/`)).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error("dev server did not start");
}

try {
  await waitUp();
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${PORT}/`);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: RATE });

  const metrics = await page.evaluate(
    async ({ runs, seed, sizes, packUrl }) => {
      const mod = await import("/src/engine.ts");
      const t0 = performance.now();
      const engine = await mod.ready(packUrl);
      const loadMs = performance.now() - t0;
      const coldPantry = engine.popular(3).map((x) => x.id);
      const c0 = performance.now();
      engine.answer({ pantry: coldPantry, staples: engine.defaultStaples, diet: null, limit: 10, unknown_names: [] });
      const coldFirstCallMs = performance.now() - c0;
      // Small seeded generator so the pantries are the same on every run.
      let s = seed >>> 0;
      const rnd = () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 2 ** 32);
      const pool = engine.popular(120).map((x) => x.id);
      const staples = engine.defaultStaples;
      const stats = (xs) => {
        const a = [...xs].sort((x, y) => x - y);
        const at = (q) => a[Math.min(a.length - 1, Math.floor(q * a.length))];
        return { n: a.length, p50: at(0.5), p95: at(0.95), max: a[a.length - 1] };
      };
      const bySize = {};
      const all = [];
      for (const size of sizes) {
        const times = [];
        for (let r = 0; r < runs + 3; r++) {
          const pantry = [];
          while (pantry.length < size) {
            const id = pool[Math.floor(rnd() * pool.length)];
            if (!pantry.includes(id)) pantry.push(id);
          }
          const a = performance.now();
          engine.answer({ pantry, staples, diet: null, limit: 10, unknown_names: [] });
          const dt = performance.now() - a;
          if (r >= 3) times.push(dt); // the first three runs warm up the engine
        }
        bySize[size] = stats(times);
        all.push(...times);
      }
      return { loadMs, coldFirstCallMs, bySize, overall: stats(all) };
    },
    { runs: RUNS, seed: SEED, sizes: SIZES, packUrl: `http://127.0.0.1:${PACK_PORT}/` },
  );
  await browser.close();

  const dirty = git("status", "--porcelain", "--untracked-files=no") !== "";
  const out = {
    label: "MEASURED",
    what: "answer() latency, Chromium headless, Vite dev server, real pack, CPU throttled",
    commit: git("rev-parse", "HEAD"),
    dirty,
    config: { cpu_throttle_rate: RATE, runs_per_size: RUNS, pantry_sizes: SIZES, limit: 10, warmup: 3, pool: "120 most common ingredients" },
    pack: {
      corpus_fingerprint: manifest.inputs?.snapshot?.sha256 ?? null,
      files: manifest.files.map((f) => ({ name: f.name, sha256: f.sha256, size: f.size })),
      recipes: manifest.counts.recipes,
    },
    seed: SEED,
    metrics: {
      ...metrics,
      threshold_ms: 100,
      p95_under_threshold: metrics.overall.p95 < 100,
      sizes_over_threshold: Object.entries(metrics.bySize)
        .filter(([, v]) => v.p95 >= 100)
        .map(([k]) => Number(k)),
    },
    worker_plan:
      "Small pantries match many recipes and are the slowest. If a production-bundle run still shows p95 >= 100 ms, move Engine into a Web Worker (module worker, same origin, loads the pack itself) and post AnswerRequest/Answer messages. The Answer type is plain JSON, so no code change in the engine is needed. Until then answer() runs on the main thread.",
    limits: "Covers answer() at limit 10 only, not rendering. Pantries come from the 120 most common ingredients. The dev server serves unminified code. One run: run-to-run spread is not measured. The first call after load is reported separately as coldFirstCallMs.",
    command: `node web/scripts/latency.mjs --rate ${RATE} --runs ${RUNS} --seed ${SEED} --out ${OUT}`,
  };
  mkdirSync(join(root, "results"), { recursive: true });
  writeFileSync(join(root, "results", OUT), JSON.stringify(out, null, 2) + "\n");
  console.log(JSON.stringify({ overall: metrics.overall, bySize: metrics.bySize, loadMs: metrics.loadMs }, null, 2));
} finally {
  stop();
}
