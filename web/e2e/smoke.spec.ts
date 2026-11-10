import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { type Page, expect, test } from "@playwright/test";

const ORIGIN = "http://127.0.0.1:4173";
const PHONE = { width: 390, height: 844 };

async function add(page: Page, ...names: string[]) {
  const input = page.getByLabel("Add ingredients");
  for (const n of names) {
    await input.fill(n);
    await input.press("Enter");
  }
}
const word = (page: Page, name: string) => page.getByRole("button", { name: `Remove ${name}` });
const tab = (page: Page, name: RegExp) => page.getByRole("tab", { name });

test("kitchen to answer to recipe, with no off-origin requests", async ({ page }) => {
  const offOrigin: string[] = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.protocol.startsWith("http") && u.origin !== ORIGIN) offOrigin.push(r.url());
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

  await add(page, "flour", "egg");
  await expect(page.getByText("2 items", { exact: true })).toBeVisible();
  // The answer is already on the page. There is no separate "see recipes" step.
  await expect(page.getByRole("tablist")).toBeVisible();
  await expect(tab(page, /Ready now/)).toBeVisible();
  await expect(tab(page, /One item away/)).toBeVisible();
  await expect(tab(page, /Two items away/)).toBeVisible();
  await expect(page.getByRole("group", { name: "Buy one thing" })).toBeVisible();

  await page.locator(".card-link").first().click();
  await expect(page.getByRole("heading", { level: 3, name: "Ingredients" })).toBeVisible();
  await expect(page.locator(".lines .box").first()).toBeVisible();
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

test("the empty state explains the page and has no tabs", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Start with what you have.")).toBeVisible();
  await expect(page.getByRole("tablist")).toHaveCount(0);
  await expect(page.getByText("Nothing in your kitchen yet")).toBeVisible();
  await expect(page.getByRole("button", { name: "Clear all" })).toHaveCount(0);
});

test("Enter takes the top suggestion for a partial word", async ({ page }) => {
  await page.goto("/");
  const input = page.getByLabel("Add ingredients");
  await input.fill("flou");
  await expect(page.getByRole("listbox", { name: "Suggestions" })).toBeVisible();
  await input.press("Enter");
  await expect(word(page, "flour")).toBeVisible();
  await expect(page.locator(".stamp")).toHaveCount(0);
});

test("an unknown name gets the stamp, and can be dismissed", async ({ page }) => {
  await page.goto("/");
  await add(page, "zzqxw");
  await expect(page.getByText("Not on the list: “zzqxw”")).toBeVisible();
  await page.getByRole("button", { name: "Dismiss “zzqxw”" }).click();
  await expect(page.locator(".stamp")).toHaveCount(0);
});

test("a pasted list splits on commas, new lines and and, and keeps the unknown words", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Paste a list" }).click();
  await page.getByLabel("Paste ingredients").fill("flou, 2 eggs\nmilk and zzqxw");
  await page.getByRole("button", { name: "Add these" }).click();
  await expect(word(page, "egg")).toBeVisible();
  await expect(word(page, "milk")).toBeVisible();
  await expect(page.getByText("Not on the list: “flou”")).toBeVisible();
  await expect(page.getByText("Not on the list: “zzqxw”")).toBeVisible();
  // "Use flour" fixes the typo.
  await page.getByRole("button", { name: "Use Flour" }).click();
  await expect(word(page, "flour")).toBeVisible();
  await expect(page.getByText("Not on the list: “flou”")).toHaveCount(0);
  await expect(page.getByLabel("Add ingredients")).toBeFocused();
});

test("a comma ends an item, and pasting a list into the field adds it", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/");
  const input = page.getByLabel("Add ingredients");
  await input.pressSequentially("flour,");
  await expect(word(page, "flour")).toBeVisible();
  await expect(input).toHaveValue("");
  await page.evaluate(() => navigator.clipboard.writeText("egg, milk and sugar"));
  await input.focus();
  await page.keyboard.press("ControlOrMeta+V");
  for (const n of ["egg", "milk", "sugar"]) await expect(word(page, n)).toBeVisible();
});

test("tapping a word removes it, with a 44 px target and a clear name", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg");
  const egg = word(page, "egg");
  const box = await egg.boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(44);
  expect(box!.width).toBeGreaterThanOrEqual(44);
  await egg.click();
  await expect(egg).toHaveCount(0);
  await expect(page.getByText("1 item", { exact: true })).toBeVisible();
  // Focus stays in the list, on the next word.
  await expect(word(page, "flour")).toBeFocused();
});

test("the distance tabs are a real tablist with arrow-key support", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg", "milk");
  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveCount(3);
  const first = tabs.nth(0);
  const second = tabs.nth(1);
  const third = tabs.nth(2);
  await first.click();
  await expect(first).toHaveAttribute("aria-selected", "true");
  await expect(first).toHaveAttribute("tabindex", "0");
  await expect(second).toHaveAttribute("tabindex", "-1");
  await expect(page.getByRole("tabpanel")).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(second).toBeFocused();
  await expect(second).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowRight");
  await expect(third).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(first).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(third).toBeFocused();
  await page.keyboard.press("Home");
  await expect(first).toBeFocused();
  await page.keyboard.press("End");
  await expect(third).toBeFocused();
  await expect(page.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", /tab-two_away/);
});

test("the kitchen is saved on this device and comes back after a reload", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg");
  await expect(page.getByText("Saved on this device. Never sent anywhere.")).toBeVisible();
  // Switch off a staple, and check that the switch also comes back.
  await page.getByText(/Staples assumed/).click();
  await page.getByLabel("Salt").uncheck();
  // No wait before the reload: the save also runs when the page is hidden or closed.
  await page.reload();
  await expect(word(page, "flour")).toBeVisible();
  await expect(word(page, "egg")).toBeVisible();
  await page.getByText(/Staples assumed/).click();
  await expect(page.getByLabel("Salt")).not.toBeChecked();
  // Only ids are stored. Typed text that was not recognised is not stored.
  await add(page, "zzqxw");
  const raw = await page.evaluate(() => JSON.stringify({ ...localStorage }));
  expect(raw).not.toContain("zzqxw");
  expect(raw).toContain("flour");
});

test("Clear all can be undone, and the undo does not steal focus", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg");
  await page.getByRole("button", { name: "Clear all" }).click();
  await expect(page.getByText("Nothing in your kitchen yet")).toBeVisible();
  const bar = page.locator(".undo[role=status]").first();
  await expect(bar).toContainText("Kitchen cleared.");
  await expect(bar).toHaveAttribute("aria-live", "polite");
  await expect(page.getByLabel("Add ingredients")).toBeFocused();
  await page.getByRole("button", { name: "Undo" }).click();
  // The undo button goes away, so focus must land on the field.
  await expect(page.getByLabel("Add ingredients")).toBeFocused();
  await expect(word(page, "flour")).toBeVisible();
  await expect(word(page, "egg")).toBeVisible();
  await page.reload();
  await expect(word(page, "egg")).toBeVisible();
});

test("Undo after Clear all keeps items added since", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg");
  await page.getByRole("button", { name: "Clear all" }).click();
  await add(page, "milk");
  await page.getByRole("button", { name: "Undo" }).click();
  for (const n of ["flour", "egg", "milk"]) await expect(word(page, n)).toBeVisible();
  await expect(page.locator(".words .word")).toHaveCount(3);
});

test("a long paste shows five stamps and a count, and Dismiss all clears them", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Paste a list" }).click();
  await page.getByLabel("Paste ingredients").fill("aaqx, bbqx, ccqx, ddqx, eeqx, ffqx, ggqx, hhqx");
  await page.getByRole("button", { name: "Add these" }).click();
  await expect(page.locator(".stamp[aria-label^=\"Not on the list\"]")).toHaveCount(5);
  await expect(page.getByText("and 3 more not on the list.")).toBeVisible();
  await page.getByRole("button", { name: "Dismiss all" }).click();
  await expect(page.locator(".stamp")).toHaveCount(0);
  await expect(page.getByLabel("Add ingredients")).toBeFocused();
});

test("the page works with storage blocked, and says so", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new DOMException("blocked", "SecurityError");
      },
    });
  });
  await page.goto("/");
  await add(page, "flour", "egg");
  await expect(word(page, "egg")).toBeVisible();
  await expect(page.getByText("Not saved: this browser blocks storage.")).toBeVisible();
  await expect(page.locator("footer.page")).toContainText("not saved, because this browser blocks storage");
  await expect(page.locator("footer.page")).not.toContainText("is saved in this browser");
  await expect(page.getByRole("tablist")).toBeVisible();
});

test("Buy one thing names recipes, and Try it adds the item with an undo", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg", "milk");
  const ticket = page.getByRole("group", { name: "Buy one thing" });
  await expect(ticket).toContainText(/Opens \d+ recipes?(: .+)?\./);
  const btn = ticket.getByRole("button", { name: /^Try it with / });
  const label = (await btn.textContent())!.replace("Try it with ", "");
  const before = await page.locator(".words .word").count();
  await btn.click();
  await expect(page.locator(".words .word")).toHaveCount(before + 1);
  const bar = page.locator("#panel .undo");
  await expect(bar).toContainText(`Added ${label}.`);
  await bar.getByRole("button", { name: "Undo" }).click();
  await expect(page.locator(".words .word")).toHaveCount(before);
  // The undo button goes away, so focus must land on the selected tab.
  await expect(page.getByRole("tab", { selected: true })).toBeFocused();
});

test("focus moves to the heading when the screen changes", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour");
  await page.locator(".card-link").first().click();
  await expect(page.locator("#recipe-h")).toBeFocused();
  await page.getByRole("button", { name: /Back to results/ }).click();
  await expect(page.locator("#answer-h")).toBeFocused();
  // The pantry and the answer are still there.
  await expect(word(page, "flour")).toBeVisible();
});

test("one item uses singular wording", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour");
  await expect(page.getByText("1 item", { exact: true })).toBeVisible();
  await expect(page.getByText(/1 item \+ staples/)).toBeVisible();
});

test("Show more adds rows and keeps focus on a row", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg", "milk", "sugar");
  let more = page.getByRole("button", { name: /Show more/ });
  for (const t of [/Ready now/, /One item away/, /Two items away/]) {
    await tab(page, t).click();
    if (await more.isVisible()) break;
  }
  await expect(more).toBeVisible();
  const before = await page.locator(".card").count();
  await more.click();
  await expect.poll(() => page.locator(".card").count()).toBeGreaterThan(before);
  await expect(page.locator(".card-link:focus")).toHaveCount(1);
});

test("a row shows its ingredients as slots, with words for screen readers", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg");
  await tab(page, /One item away/).click();
  const row = page.locator(".card").first();
  await expect(row.locator(".slot-have").first()).toBeVisible();
  const need = row.locator(".slot-need").first();
  await expect(need).toBeVisible();
  await expect(need.locator(".sr")).toHaveText("Missing: ");
  // The plus is a visible cue, and it is hidden from screen readers.
  await expect(need.locator("[aria-hidden=true]")).toHaveText("+");
});

test("the recipe screen lists lines as a checklist with markers and status words", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg");
  await page.locator(".card-link").first().click();
  const lines = page.locator(".lines");
  await expect(lines).toContainText("[x]");
  await expect(lines).toContainText("You have this");
  await expect(lines).toContainText("(~)");
  await expect(lines).toContainText("Assumed (staple)");
  await expect(page.locator(".said")).toContainText(/Missing: |Nothing is missing\./);
});

test("on a phone the kitchen is a summary until you edit it, and there is no sideways scroll", async ({ page }) => {
  await page.setViewportSize(PHONE);
  await page.goto("/");
  // Empty: expanded at once.
  await expect(page.getByLabel("Add ingredients")).toBeVisible();
  await add(page, "flour", "egg", "milk", "sugar");
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByLabel("Add ingredients")).toBeHidden();
  await expect(page.getByText("Flour, Egg, Milk +1 more")).toBeVisible();
  // The answer is above the fold.
  const top = await page.locator("#answer-h").boundingBox();
  expect(top!.y).toBeLessThan(PHONE.height);
  const edit = page.getByRole("button", { name: "Edit kitchen" });
  await edit.click();
  await expect(page.getByLabel("Add ingredients")).toBeFocused();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("a CC BY-SA recipe shows the licence text link", async ({ page }) => {
  // The fixture says "Synthetic test fixture (MIT)". Serve a copy that says CC BY-SA 4.0.
  const text = JSON.parse(readFileSync("../tests/fixtures/pack/text.v1.json", "utf8"));
  for (const r of Object.values<{ licence: string }>(text.recipes)) r.licence = "CC BY-SA 4.0";
  await page.route("**/pack/text.v1.json.gz", (route) =>
    route.fulfill({ contentType: "application/gzip", body: gzipSync(JSON.stringify(text)) }),
  );
  await page.goto("/");
  await add(page, "flour");
  await page.locator(".card-link").first().click();
  const link = page.getByRole("link", { name: "licence text" });
  await expect(link).toHaveAttribute("href", "https://creativecommons.org/licenses/by-sa/4.0/");
  await expect(page.locator("footer.attribution")).toContainText("Licence: CC BY-SA 4.0");
});

test("a failed pack download shows a clear error with a reload button", async ({ page }) => {
  await page.route("**/pack/core.v1.json*", (route) => route.fulfill({ status: 404, body: "no" }));
  await page.goto("/");
  await expect(page.getByRole("alert")).toHaveText("The recipe data did not load. Check your connection and reload.");
  await expect(page.getByRole("button", { name: "Reload" })).toBeVisible();
});
