// Probe the deployed app on a real Android phone: tap-target sizes, sideways scroll and focus after
// each step. Reads the DOM over CDP. Writes results/m2_device_ui_probe.json.
// Setup: USB debugging on, screen awake, Chrome open. If several adb devices are attached, set ANDROID_SERIAL.
// Usage: node scripts/probe-device-ui.mjs [--url URL] [--port 9222] [--out FILE]
import { execFileSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { writeResult } from "./result.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const arg = (n, d) => {
  const i = process.argv.indexOf(`--${n}`);
  return i > 0 ? process.argv[i + 1] : d;
};
const URL_ = arg("url", "https://aritr-codes.github.io/PantryChef/");
const PORT = Number(arg("port", 9222));
const OUT = arg("out", "m2_device_ui_probe.json");
const ADB = process.env.ADB ?? "adb";
const MIN = 44;
const adb = (...a) => execFileSync(ADB, a, { encoding: "utf8" }).trim();

adb("shell", "input", "keyevent", "KEYCODE_WAKEUP");
adb("forward", `tcp:${PORT}`, "localabstract:chrome_devtools_remote");
const browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`);
const context = browser.contexts()[0];
const page = context.pages().find((p) => p.url().startsWith(URL_)) ?? (await context.newPage());
await page.bringToFront();
await page.goto(URL_, { waitUntil: "load" });
const ua = await page.evaluate(() => navigator.userAgent);

const snap = (step) =>
  page.evaluate(
    ([step, MIN]) => {
      const sel = "button, a[href], input, select, textarea, summary, [role=option], [role=button]";
      const seen = [...document.querySelectorAll(sel)].flatMap((el) => {
        // A check box is tapped through its label, so measure the label.
        const box = el.type === "checkbox" ? (el.closest("label") ?? el) : el;
        const r = box.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return [];
        const text = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || "").trim().slice(0, 40);
        return [{ tag: el.tagName.toLowerCase(), text, w: Math.round(r.width), h: Math.round(r.height) }];
      });
      const a = document.activeElement;
      return {
        step,
        controls: seen.length,
        below_min: seen.filter((t) => t.w < MIN || t.h < MIN),
        active: a ? `${a.tagName.toLowerCase()}${a.id ? "#" + a.id : ""}` : null,
        active_text: a ? (a.textContent || "").trim().slice(0, 40) : null,
        sideways_scroll_px: document.documentElement.scrollWidth - innerWidth,
        viewport_css_px: innerWidth,
        dpr: devicePixelRatio,
      };
    },
    [step, MIN],
  );

const steps = [];
steps.push(await snap("pantry_empty"));
const input = page.getByLabel("Type an ingredient");
for (const n of ["egg", "flour", "milk"]) {
  await input.fill(n);
  await input.press("Enter");
}
await page.getByText(/Your pantry \(3\)/).waitFor({ timeout: 10000 });
steps.push(await snap("pantry_3_items"));
await input.fill("ch");
await page.waitForTimeout(500);
steps.push(await snap("suggestions_open"));
await input.fill("");
await page.getByRole("button", { name: /See recipes/ }).click();
await page.locator("#results-h").waitFor({ timeout: 10000 });
await page.waitForTimeout(500);
steps.push(await snap("results"));

// Open the first recipe. A failure here is recorded, not hidden.
let recipe = { step: "recipe_open", ok: false };
try {
  const cand = page.locator("main button, main a[href]").filter({ hasNotText: /pantry|see recipes|back|staples/i }).first();
  const label = ((await cand.textContent()) ?? "").trim().slice(0, 40);
  await cand.click();
  await page.waitForFunction(() => !/Loading recipe/.test(document.body.innerText), null, { timeout: 15000 });
  await page.waitForTimeout(500);
  recipe = { ...(await snap("recipe_open")), ok: true, clicked: label };
} catch (e) {
  recipe.error = String(e).slice(0, 200);
}
steps.push(recipe);

// Go back twice: recipe -> results -> pantry. Record the focus after each.
for (const [step, name] of [["back_to_results", /Results/], ["back_to_pantry", /Pantry/]]) {
  try {
    await page.getByRole("button", { name }).first().click({ timeout: 5000 });
    await page.waitForTimeout(500);
    steps.push(await snap(step));
  } catch (e) {
    steps.push({ step, ok: false, error: String(e).slice(0, 200) });
  }
}
adb("forward", "--remove", `tcp:${PORT}`);

const model = adb("shell", "getprop", "ro.product.model");
const doc = {
  label: "MEASURED",
  what: "Tap-target size (CSS px, below 44), sideways scroll and focus after each step, deployed app, real Android phone in Chrome",
  command: `node web/scripts/probe-device-ui.mjs --url ${URL_} --port ${PORT} --out ${OUT}`,
  config: { url: URL_, min_target_css_px: MIN, items_added: ["egg", "flour", "milk"], input: "CDP fill and press, taps not used", limit: "geometry and focus only; no screen reader, no on-screen keyboard" },
  seed: 0,
  corpus_fingerprint: `deployed bundle: ${URL_}`,
  arms: [],
  metrics: [],
  comparisons: [],
  environment: { device: model, user_agent: ua },
  raw: { steps },
};
writeResult(join(root, "results", OUT), doc, root);
console.log(JSON.stringify(steps, null, 1));
process.exit(0);
