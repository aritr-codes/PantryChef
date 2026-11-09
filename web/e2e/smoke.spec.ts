import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { expect, test } from "@playwright/test";

test("pantry to results to recipe, with no off-origin requests", async ({ page }) => {
  const offOrigin: string[] = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.protocol.startsWith("http") && u.origin !== "http://127.0.0.1:4173") offOrigin.push(r.url());
  });
  const violations: string[] = [];
  page.on("console", (m) => {
    if (/content security policy/i.test(m.text())) violations.push(m.text());
  });

  await page.goto("/");

  // The CSP meta tag must come before any script, or it does not protect the script.
  const order = await page.evaluate(() => {
    const nodes = [...document.head.children];
    const csp = nodes.findIndex((n) => n.getAttribute("http-equiv") === "Content-Security-Policy");
    const script = nodes.findIndex((n) => n.tagName === "SCRIPT");
    return { csp, script };
  });
  expect(order.csp).toBeGreaterThanOrEqual(0);
  expect(order.script).toBeGreaterThanOrEqual(0);
  expect(order.csp).toBeLessThan(order.script);

  const input = page.getByLabel("Type an ingredient");
  await input.fill("flour");
  await input.press("Enter");
  await input.fill("egg");
  await input.press("Enter");
  await expect(page.getByRole("heading", { name: "Your pantry (2)" })).toBeVisible();

  await page.getByRole("button", { name: /See recipes/ }).click();
  await expect(page.getByRole("heading", { name: /Make now \(\d+\)/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /One item away \(\d+\)/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Top unlocks" })).toBeVisible();
  await expect(page.getByText(/^Add .+ to move \d+ recipes? to make now$/).first()).toBeVisible();

  await page.locator(".card-link").first().click();
  await expect(page.getByRole("heading", { level: 3, name: "Ingredients" })).toBeVisible();
  const attribution = page.locator("footer.attribution");
  await expect(attribution).toContainText("Revision");
  await expect(attribution).toContainText("Licence:");
  const hrefs = await attribution.locator("a").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  expect(hrefs.length).toBeGreaterThan(0);
  for (const h of hrefs) expect(h).toMatch(/^https:\/\/(en\.wikibooks\.org|creativecommons\.org)\//);
  const source = attribution.getByRole("link").first();
  await expect(source).toHaveAttribute("href", /^https:\/\/en\.wikibooks\.org\//);

  expect(offOrigin).toEqual([]);
  expect(violations).toEqual([]);
});

test("Enter takes the top suggestion for a partial word", async ({ page }) => {
  await page.goto("/");
  const input = page.getByLabel("Type an ingredient");
  await input.fill("flou");
  await expect(page.getByRole("listbox", { name: "Suggestions" })).toBeVisible();
  await input.press("Enter");
  await expect(page.getByRole("heading", { name: "Your pantry (1)" })).toBeVisible();
  await expect(page.locator(".unknown")).toHaveCount(0);
});

test("a typed pair adds both ingredients, and a typo adds the nearest one", async ({ page }) => {
  await page.goto("/");
  const input = page.getByLabel("Type an ingredient");
  await input.fill("s&p");
  await input.press("Enter");
  await expect(page.getByRole("heading", { name: "Your pantry (2)" })).toBeVisible();
  const chips = page.getByRole("list", { name: "Your pantry" });
  await expect(chips).toContainText("salt");
  await expect(chips).toContainText("black pepper");
  await input.fill("cinamon");
  await input.press("Enter");
  await expect(page.getByRole("heading", { name: "Your pantry (3)" })).toBeVisible();
  await expect(chips).toContainText("cinnamon");
  await expect(page.locator(".unknown")).toHaveCount(0);
});

test("an unknown name is shown as not used, and removable", async ({ page }) => {
  await page.goto("/");
  const input = page.getByLabel("Type an ingredient");
  await input.fill("zzqxw");
  await input.press("Enter");
  await expect(page.getByText("Not recognised: “zzqxw”")).toBeVisible();
  await page.getByRole("button", { name: "Remove “zzqxw”" }).click();
  await expect(page.locator(".unknown")).toHaveCount(0);
});

test("focus moves to the heading when the screen changes", async ({ page }) => {
  await page.goto("/");
  const input = page.getByLabel("Type an ingredient");
  await input.fill("flour");
  await input.press("Enter");
  await page.getByRole("button", { name: /See recipes/ }).click();
  await expect(page.locator("#results-h")).toBeFocused();
});

test("one item shows singular wording and a hint", async ({ page }) => {
  await page.goto("/");
  const input = page.getByLabel("Type an ingredient");
  await input.fill("flour");
  await input.press("Enter");
  await page.getByRole("button", { name: /See recipes/ }).click();
  await expect(page.getByRole("heading", { name: "Results for 1 item" })).toBeVisible();
  await expect(page.getByText("Add more items for better matches.")).toBeVisible();
});

test("Show more adds cards and keeps focus on a card", async ({ page }) => {
  await page.goto("/");
  const input = page.getByLabel("Type an ingredient");
  for (const n of ["flour", "egg", "milk", "sugar"]) {
    await input.fill(n);
    await input.press("Enter");
  }
  await page.getByRole("button", { name: /See recipes/ }).click();
  const more = page.getByRole("button", { name: /Show more/ }).first();
  await expect(more).toBeVisible();
  const before = await page.locator(".card").count();
  await more.click();
  await expect.poll(() => page.locator(".card").count()).toBeGreaterThan(before);
  await expect(page.locator(".card-link:focus")).toHaveCount(1);
});

test("a CC BY-SA recipe shows the licence text link", async ({ page }) => {
  // The fixture says "Synthetic test fixture (MIT)". Serve a copy that says CC BY-SA 4.0.
  const text = JSON.parse(readFileSync("../tests/fixtures/pack/text.v1.json", "utf8"));
  for (const r of Object.values<{ licence: string }>(text.recipes)) r.licence = "CC BY-SA 4.0";
  await page.route("**/pack/text.v1.json.gz", (route) =>
    route.fulfill({ contentType: "application/gzip", body: gzipSync(JSON.stringify(text)) }),
  );
  await page.goto("/");
  const input = page.getByLabel("Type an ingredient");
  await input.fill("flour");
  await input.press("Enter");
  await page.getByRole("button", { name: /See recipes/ }).click();
  await page.locator(".card-link").first().click();
  const link = page.getByRole("link", { name: "licence text" });
  await expect(link).toHaveAttribute("href", "https://creativecommons.org/licenses/by-sa/4.0/");
  await expect(page.locator("footer.attribution")).toContainText("Licence: CC BY-SA 4.0");
});
