import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { type Page, expect, test } from "@playwright/test";

const ORIGIN = "http://127.0.0.1:4173";
const PHONE = { width: 390, height: 844 };

async function add(page: Page, ...names: string[]) {
  const input = page.getByLabel("Add what you have");
  for (const n of names) {
    await input.fill(n);
    await input.press("Enter");
  }
}
const word = (page: Page, name: string) => page.getByRole("button", { name: `Remove ${name}` });
const tab = (page: Page, name: RegExp) => page.getByRole("tab", { name });
const items = (page: Page) => page.locator(".pantry .have");
/** The "N items" note on the kitchen slip (the full view, not the phone summary). */
const noteOf = (page: Page) => page.locator(".full .head .kicker").nth(1);
const ticketOf = (page: Page) => page.getByRole("group", { name: "Buy 1 thing" });

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
  await expect(noteOf(page)).toHaveText("2 items");
  // The answer is already on the page. There is no separate "see recipes" step.
  await expect(page.getByRole("tablist")).toBeVisible();
  await expect(tab(page, /Ready now/)).toBeVisible();
  await expect(tab(page, /Need 1 thing/)).toBeVisible();
  await expect(tab(page, /Need 2 things/)).toBeVisible();
  await expect(ticketOf(page)).toBeVisible();

  await page.locator(".rec-link").first().click();
  await expect(page.getByRole("heading", { level: 3, name: "Ingredients" })).toBeVisible();
  await expect(page.locator(".lines .mk").first()).toBeVisible();
  // The skip link is on the recipe screen too, and it points at the same target.
  await expect(page.locator("a.skip")).toHaveAttribute("href", "#answer");
  await expect(page.locator("#answer")).toBeAttached();
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

test("the empty state explains the page, shows three steps and offers examples", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Your kitchen is empty. Add what you have, or start with an example.")).toBeVisible();
  await expect(page.locator(".how li")).toHaveCount(3);
  await expect(page.locator(".examples .ex")).toHaveCount(3);
  await expect(tab(page, /Ready now/)).toContainText("0");
  await expect(page.locator(".ticket")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Clear all" })).toHaveCount(0);
});

test("an example kitchen fills the kitchen, focuses the first tab, is announced and is saved", async ({ page }) => {
  await page.goto("/");
  const ex = page.locator(".examples .ex").first();
  const name = (await ex.locator("b").textContent())!;
  await ex.click();
  const n = await items(page).count();
  expect(n).toBeGreaterThanOrEqual(3);
  await expect(tab(page, /Ready now/)).toBeFocused();
  await expect(tab(page, /Ready now/)).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("[role=status][aria-live=polite]", { hasText: `${name} added. ${n} items.` })).toHaveCount(1);
  await expect(page.locator(".examples")).toHaveCount(0);
  // Same save path as a normal add.
  await page.reload();
  await expect(items(page)).toHaveCount(n);
});

test("the Buy 1 thing numbers are N and N + k, and k matches the sentence", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg", "milk");
  const ticket = ticketOf(page);
  const now = Number(await ticket.locator(".from").textContent());
  const to = Number(await ticket.locator(".to").textContent());
  const k = Number(/you can cook (\d+) more/.exec((await ticket.locator(".why").textContent())!)![1]);
  expect(k).toBeGreaterThan(0);
  expect(to).toBe(now + k);
  await expect(tab(page, /Ready now/).locator(".n")).toHaveText(String(now));
  // After the add, "Ready now" has grown by k.
  await ticket.getByRole("button", { name: /^Add / }).click();
  await expect(tab(page, /Ready now/).locator(".n")).toHaveText(String(to));
});

test("the ticket counts a recipe whose only needed line is the item, and Add says one thing", async ({ page }) => {
  await page.goto("/");
  // In the fixture, Flour Paste and Salt Dough need only flour. The engine's unlock count misses them.
  await add(page, "egg", "milk", "banana");
  const ticket = ticketOf(page);
  const now = Number(await ticket.locator(".from").textContent());
  const to = Number(await ticket.locator(".to").textContent());
  const k = Number(/you can cook (\d+) more/.exec((await ticket.locator(".why").textContent())!)![1]);
  expect(k).toBeGreaterThan(1);
  expect(to).toBe(now + k);
  const label = (await ticket.getByRole("button", { name: /^Add / }).textContent())!.replace("Add ", "");
  await ticket.getByRole("button", { name: /^Add / }).click();
  // The count on the tab, the lead line and the undo message all give the same numbers.
  await expect(tab(page, /Ready now/).locator(".n")).toHaveText(String(to));
  await expect(page.locator("#answer-h")).toContainText(new RegExp(`^${to} recipes are ready now`));
  const name = `${label.charAt(0).toUpperCase()}${label.slice(1)}`;
  await expect(page.locator(".answer .undo")).toHaveText(new RegExp(`^${name} added\\. ${k} more recipes are ready now\\.`));
});

test("Clear all, then an example, then no undo is left to bring back the old kitchen", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg");
  await page.getByRole("button", { name: "Clear all" }).click();
  await expect(page.locator(".kitchen .undo")).toContainText("Kitchen cleared.");
  await page.locator(".examples .ex").first().click();
  await expect(page.locator(".kitchen .undo")).toHaveText("");
  await expect(page.getByRole("button", { name: "Undo" })).toHaveCount(0);
});

test("the skip link jumps to the recipes, and the combobox names the active option", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour");
  await page.locator("body").click({ position: { x: 1, y: 1 } });
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to the recipes" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#answer")).toBeFocused();
  await expect(page.getByRole("tabpanel")).toHaveAttribute("tabindex", "0");

  const input = page.getByLabel("Add what you have");
  await input.fill("mil");
  await input.press("ArrowDown");
  const id = await input.getAttribute("aria-activedescendant");
  expect(id).toMatch(/^sug-/);
  await expect(page.locator(`#${id}`)).toHaveAttribute("role", "option");
  await expect(page.locator(`#${id}`)).toHaveAttribute("aria-selected", "true");
});

test("with reduced motion nothing animates after any action", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const count = () => page.evaluate(() => document.getAnimations().length);
  expect(await count()).toBe(0);
  await page.locator(".examples .ex").first().click();
  await expect(items(page).first()).toBeVisible();
  expect(await count()).toBe(0);
  await ticketOf(page).getByRole("button", { name: /^Add / }).click();
  await expect(page.locator(".answer .undo")).toContainText("added.");
  expect(await count()).toBe(0);
  await expect(page.locator(".dot")).toHaveCount(0);
  await tab(page, /Need 1 thing/).click();
  await items(page).first().click();
  expect(await count()).toBe(0);
});

test("with motion allowed, Add plays a short burst that is removed, and focus stays put", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/");
  await add(page, "flour", "egg", "milk");
  await ticketOf(page).getByRole("button", { name: /^Add / }).click();
  await expect(page.locator(".dot").first()).toBeAttached();
  await expect(page.locator(".dot").first()).toHaveAttribute("aria-hidden", "true");
  // The dots are decoration: they are never the focused element, and they go away.
  expect(await page.evaluate(() => document.activeElement?.classList.contains("dot"))).toBe(false);
  await expect(page.locator(".dot")).toHaveCount(0, { timeout: 2000 });
});

test("Enter takes the top suggestion for a partial word", async ({ page }) => {
  await page.goto("/");
  const input = page.getByLabel("Add what you have");
  await input.fill("flou");
  await expect(page.getByRole("listbox", { name: "Suggestions" })).toBeVisible();
  await input.press("Enter");
  await expect(word(page, "flour")).toBeVisible();
  await expect(page.locator(".stamp")).toHaveCount(0);
});

test("an unknown name gets the stamp, and can be dismissed", async ({ page }) => {
  await page.goto("/");
  await add(page, "zzqxw");
  await expect(page.getByText("We do not know “zzqxw” yet.")).toBeVisible();
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
  await expect(page.getByText("We do not know “flou” yet.")).toBeVisible();
  await expect(page.getByText("We do not know “zzqxw” yet.")).toBeVisible();
  // "Use Flour instead" fixes the typo.
  await page.getByRole("button", { name: "Use Flour instead" }).click();
  await expect(word(page, "flour")).toBeVisible();
  await expect(page.getByText("We do not know “flou” yet.")).toHaveCount(0);
  await expect(page.getByLabel("Add what you have")).toBeFocused();
});

test("a comma ends an item, and pasting a list into the field adds it", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/");
  const input = page.getByLabel("Add what you have");
  await input.pressSequentially("flour,");
  await expect(word(page, "flour")).toBeVisible();
  await expect(input).toHaveValue("");
  await page.evaluate(() => navigator.clipboard.writeText("egg, milk and sugar"));
  await input.focus();
  await page.keyboard.press("ControlOrMeta+V");
  for (const n of ["egg", "milk", "sugar"]) await expect(word(page, n)).toBeVisible();
});

test("tapping a word removes it, with a 44 px target and a clear name", async ({ page }) => {
  // The chip pops in from half size. Measure it at rest.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await add(page, "flour", "egg");
  const egg = word(page, "egg");
  const box = await egg.boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(44);
  expect(box!.width).toBeGreaterThanOrEqual(44);
  await egg.click();
  await expect(egg).toHaveCount(0);
  await expect(noteOf(page)).toHaveText("1 item");
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
  await expect(page.locator("footer.page")).toContainText("Saved on this device. We send nothing to a server.");
  // Switch off a staple, and check that the switch also comes back.
  await page.getByText(/Choose staples/).click();
  await page.getByRole("checkbox", { name: "salt", exact: true }).uncheck();
  // No wait before the reload: the save also runs when the page is hidden or closed.
  await page.reload();
  await expect(word(page, "flour")).toBeVisible();
  await expect(word(page, "egg")).toBeVisible();
  await page.getByText(/Choose staples/).click();
  await expect(page.getByRole("checkbox", { name: "salt", exact: true })).not.toBeChecked();
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
  await expect(page.getByText("Your kitchen is empty.")).toBeVisible();
  const bar = page.locator(".undo[role=status]").first();
  await expect(bar).toContainText("Kitchen cleared.");
  await expect(bar).toHaveAttribute("aria-live", "polite");
  await expect(page.getByLabel("Add what you have")).toBeFocused();
  await page.getByRole("button", { name: "Undo" }).click();
  // The undo button goes away, so focus must land on the field.
  await expect(page.getByLabel("Add what you have")).toBeFocused();
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
  await expect(items(page)).toHaveCount(3);
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
  await expect(page.getByLabel("Add what you have")).toBeFocused();
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
  await expect(page.locator("footer.page")).toContainText("Not saved: this browser blocks storage.");
  await expect(page.locator("footer.page")).not.toContainText("Saved on this device");
  await expect(page.getByRole("tablist")).toBeVisible();
});

test("Buy 1 thing names recipes, and Add adds the item with an undo", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg", "milk");
  const ticket = ticketOf(page);
  await expect(ticket).toContainText(/With .+, you can cook \d+ more/);
  await expect(ticket).toContainText("This adds");
  await expect(ticket).toContainText("to your kitchen. You can undo it.");
  const btn = ticket.getByRole("button", { name: /^Add / });
  const label = (await btn.textContent())!.replace("Add ", "");
  const before = await items(page).count();
  await btn.click();
  await expect(items(page)).toHaveCount(before + 1);
  const bar = page.locator(".answer .undo");
  await expect(bar).toContainText(`${label.charAt(0).toUpperCase()}${label.slice(1)} added.`);
  await bar.getByRole("button", { name: "Undo" }).click();
  await expect(items(page)).toHaveCount(before);
  // The undo button goes away, so focus must land on the selected tab.
  await expect(page.getByRole("tab", { selected: true })).toBeFocused();
});

test("focus moves to the heading when the screen changes", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour");
  await page.locator(".rec-link").first().click();
  await expect(page.locator("#recipe-h")).toBeFocused();
  await page.getByRole("button", { name: /Back to results/ }).click();
  await expect(page.locator("#answer-h")).toBeFocused();
  // The pantry and the answer are still there.
  await expect(word(page, "flour")).toBeVisible();
});

test("one item uses singular wording", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour");
  await expect(noteOf(page)).toHaveText("1 item");
  await expect(page.getByText("From 1 item + staples")).toBeVisible();
});

test("Show more adds rows and keeps focus on a row", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg", "milk", "sugar");
  const more = page.getByRole("button", { name: /Show more/ });
  for (const t of [/Ready now/, /Need 1 thing/, /Need 2 things/]) {
    await tab(page, t).click();
    if (await more.isVisible()) break;
  }
  await expect(more).toBeVisible();
  const before = await page.locator(".rec").count();
  await more.click();
  await expect.poll(() => page.locator(".rec").count()).toBeGreaterThan(before);
  await expect(page.locator(".rec-link:focus")).toHaveCount(1);
});

test("a row shows its ingredients as slots, with words for screen readers and no cooking time", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg");
  await tab(page, /Need 1 thing/).click();
  const row = page.locator(".rec").first();
  await expect(row.locator(".s.h").first()).toBeVisible();
  const need = row.locator(".s.n").first();
  await expect(need).toBeVisible();
  await expect(need.locator(".sr")).toHaveText("You need");
  // The plus is a visible cue, and it is hidden from screen readers.
  await expect(need.locator("[aria-hidden=true]")).toHaveText("+");
  await expect(row.locator(".meta")).toContainText(/\d+ of \d+/);
  await expect(row).not.toContainText(/\bmin\b|minutes|\bhours?\b/);
});

test("the recipe screen lists lines as a checklist with markers and status words", async ({ page }) => {
  await page.goto("/");
  await add(page, "flour", "egg");
  await page.locator(".rec-link").first().click();
  const lines = page.locator(".lines");
  await expect(lines).toContainText("[x]");
  await expect(lines).toContainText("You have it");
  await expect(lines).toContainText("(~)");
  await expect(lines).toContainText("Assumed");
  await expect(page.locator(".said")).toContainText(/You need .+ You have the rest\.|You have everything\./);
});

test("on a phone the kitchen is a summary until you edit it, and there is no sideways scroll", async ({ page }) => {
  await page.setViewportSize(PHONE);
  await page.goto("/");
  // Empty: expanded at once.
  await expect(page.getByLabel("Add what you have")).toBeVisible();
  await add(page, "flour", "egg", "milk", "sugar");
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByLabel("Add what you have")).toBeHidden();
  await expect(page.locator(".sum-text")).toHaveText("flour, egg, milk, sugar");
  // The answer is above the fold.
  const top = await page.locator("#answer-h").boundingBox();
  expect(top!.y).toBeLessThan(PHONE.height);
  const edit = page.getByRole("button", { name: "Edit kitchen" });
  await edit.click();
  await expect(page.getByLabel("Add what you have")).toBeFocused();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("at 320 px, with text spacing raised, nothing scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/");
  await add(page, "flour", "egg", "milk");
  // WCAG 1.4.12: line height 1.5, letter spacing .12em, word spacing .16em. A constructed sheet
  // goes through the style object model, which the page policy allows.
  const apply = () =>
    page.evaluate(() => {
      const sheet = new CSSStyleSheet();
      sheet.replaceSync("* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }");
      document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
    });
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(await overflow()).toBeLessThanOrEqual(0);
  await apply();
  // Prove the override took effect, or the check below would pass for nothing.
  expect(await page.evaluate(() => getComputedStyle(document.querySelector(".rec-link")!).letterSpacing)).not.toBe("normal");
  expect(await overflow()).toBeLessThanOrEqual(0);
  await page.locator(".rec-link").first().click();
  await expect(page.locator("#recipe-h")).toBeFocused();
  expect(await overflow()).toBeLessThanOrEqual(0);
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
  await page.locator(".rec-link").first().click();
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
