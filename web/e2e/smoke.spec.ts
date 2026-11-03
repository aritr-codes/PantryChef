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
