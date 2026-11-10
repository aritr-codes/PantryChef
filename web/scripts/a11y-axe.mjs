// Scan the built page with axe-core: the empty state, a kitchen with results, the ticket after
// "Add", and a recipe screen, each at 1200, 390 and 320 px. It exits with 1 on any violation.
// axe is not a dependency of this project. Get axe.min.js from the axe-core package yourself and
// pass its path:
//   npm run build && npm run preview -- --host 127.0.0.1 --port 4174 --strictPort
//   AXE_PATH=/path/to/axe.min.js node scripts/a11y-axe.mjs [--url http://127.0.0.1:4174/]
// A "color-contrast incomplete" result means axe could not read the background (the gingham table
// or a pseudo-element). Check those by hand.
import { readFileSync } from "node:fs";
import { chromium } from "@playwright/test";

const arg = (n, d) => {
  const i = process.argv.indexOf(`--${n}`);
  return i > 0 ? process.argv[i + 1] : d;
};
const URL_ = arg("url", "http://127.0.0.1:4174/");
const AXE_PATH = process.env.AXE_PATH;
if (!AXE_PATH) {
  console.error("Set AXE_PATH to the path of axe.min.js.");
  process.exit(2);
}
const AXE = readFileSync(AXE_PATH, "utf8");
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
const SIZES = [[1200, 900], [390, 844], [320, 700]];

let failed = 0;
async function scan(page, label) {
  await page.evaluate(AXE);
  const r = await page.evaluate((tags) => axe.run(document, { runOnly: { type: "tag", values: tags } }), TAGS);
  console.log(`${label}: ${r.violations.length} violations, ${r.passes.length} rules passed, ${r.incomplete.length} incomplete`);
  for (const v of r.violations) {
    failed++;
    console.log(`  - ${v.id} (${v.impact}): ${v.help}`);
    for (const n of v.nodes.slice(0, 4)) console.log(`      ${n.target.join(" ")}`);
  }
}

const browser = await chromium.launch();
try {
  for (const [w, h] of SIZES) {
    const page = await (await browser.newContext({ viewport: { width: w, height: h } })).newPage();
    await page.goto(URL_);
    const input = page.getByLabel("Add what you have");
    await input.waitFor();
    await page.waitForTimeout(900); // let the print-in finish
    await scan(page, `${w}px empty`);
    for (const n of ["flour", "egg", "milk"]) {
      await input.fill(n);
      await input.press("Enter");
    }
    await page.waitForTimeout(900);
    await scan(page, `${w}px kitchen with results`);
    await page.getByRole("group", { name: "Buy 1 thing" }).getByRole("button", { name: /^Add / }).click();
    await page.waitForTimeout(900);
    await scan(page, `${w}px ticket after Add`);
    await page.locator(".rec-link").first().click();
    await page.locator("#recipe-h").waitFor();
    await page.waitForTimeout(500);
    await scan(page, `${w}px recipe screen`);
    await page.context().close();
  }
} finally {
  await browser.close();
}
process.exit(failed ? 1 : 0);
