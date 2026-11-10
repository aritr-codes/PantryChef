// Security and wording rules for the app. Recipe text is public input: render it as text only.

import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { CSP } from "../csp";
import { historyUrl, safeWikibooksUrl } from "../src/links";
import { lineStatus } from "../src/status";
import type { CoreLine } from "../src/types";

const src = resolve(__dirname, "..", "src");

describe("recipe text is rendered as text", () => {
  it("never uses innerHTML, dangerouslySetInnerHTML or document.write", () => {
    const files = readdirSync(src).filter((f) => /\.(tsx?|css)$/.test(f));
    expect(files.length).toBeGreaterThan(5);
    for (const f of files) {
      const text = readFileSync(join(src, f), "utf8");
      expect(text, f).not.toMatch(/dangerouslySetInnerHTML|innerHTML|outerHTML|document\.write|insertAdjacentHTML/);
    }
  });

  it("has no analytics, trackers, cookies or network calls outside the engine", () => {
    for (const f of readdirSync(src).filter((x) => /\.tsx?$/.test(x))) {
      const text = readFileSync(join(src, f), "utf8");
      expect(text, f).not.toMatch(/sessionStorage|indexedDB|document\.cookie|sendBeacon|gtag|analytics/);
      if (f !== "engine.ts") expect(text, f).not.toMatch(/\bfetch\(|XMLHttpRequest|WebSocket/);
    }
  });

  it("uses localStorage only in store.ts, which saves ids and never free text", () => {
    for (const f of readdirSync(src).filter((x) => /\.tsx?$/.test(x))) {
      const text = readFileSync(join(src, f), "utf8");
      if (f === "store.ts") expect(text).toMatch(/localStorage/);
      else expect(text, f).not.toMatch(/localStorage/);
    }
    // The saved shape has only these keys.
    const store = readFileSync(join(src, "store.ts"), "utf8");
    expect(store).toMatch(/JSON\.stringify\(\{ v: 1, ids: s\.ids, staplesOff: s\.staplesOff \}\)/);
  });

  it("sets no inline style attributes (the policy allows only style files)", () => {
    for (const f of readdirSync(src).filter((x) => /\.tsx$/.test(x))) {
      expect(readFileSync(join(src, f), "utf8"), f).not.toMatch(/\bstyle=/);
    }
  });
});

describe("the stylesheet", () => {
  const css = readFileSync(join(src, "style.css"), "utf8");

  it("is one light look: no dark-mode query, no dark colour scheme", () => {
    expect(css).not.toMatch(/prefers-color-scheme/);
    expect(css).toMatch(/color-scheme:\s*light\b/);
  });

  it("loads nothing from outside: no url(), @import or @font-face", () => {
    expect(css).not.toMatch(/url\s*\(|@import|@font-face|https?:\/\//);
  });

  it("starts every animation, transition and keyframe use inside the no-preference query", () => {
    // Cut the sheet at the motion block. Nothing before it may move.
    const at = css.indexOf("@media (prefers-reduced-motion: no-preference)");
    expect(at).toBeGreaterThan(0);
    expect(css.slice(0, at)).not.toMatch(/\banimation(-\w+)?\s*:|\btransition(-\w+)?\s*:/);
    // Only keyframes may follow the block, and the block uses no other query.
    const after = css.slice(css.indexOf("@keyframes"));
    expect(after.replace(/@keyframes[^{]+\{(?:[^{}]|\{[^{}]*\})*\}/g, "").trim()).toBe("");
  });
});

describe("source links", () => {
  it("accept only https://en.wikibooks.org/", () => {
    expect(safeWikibooksUrl("https://en.wikibooks.org/wiki/Cookbook:Apple_Cobbler")).toContain(
      "en.wikibooks.org",
    );
    for (const bad of [
      "javascript:alert(1)",
      "http://en.wikibooks.org/wiki/X",
      "https://en.wikibooks.org.evil.example/wiki/X",
      "https://en.wikibooks.org@evil.example/",
      "https://user:pw@en.wikibooks.org/",
      "https://en.wikibooks.org:444/",
      "//en.wikibooks.org/x",
      "not a url",
    ]) {
      expect(safeWikibooksUrl(bad), bad).toBeNull();
    }
  });

  it("builds a history link", () => {
    expect(historyUrl("https://en.wikibooks.org/wiki/Cookbook:X")).toBe(
      "https://en.wikibooks.org/wiki/Cookbook:X?action=history",
    );
    expect(historyUrl("javascript:1")).toBeNull();
  });
});

describe("content security policy", () => {
  it("sets the directives that default-src does not cover", () => {
    for (const d of ["base-uri 'none'", "object-src 'none'", "form-action 'none'", "default-src 'self'"]) {
      expect(CSP).toContain(d);
    }
    expect(CSP).not.toMatch(/unsafe-inline|unsafe-eval|\*/);
  });
});

describe("line status", () => {
  const line = (o: string[], opt = false, r = true): CoreLine => ({ t: "x", o, opt, r });
  const pantry = new Set(["a"]);
  const staples = new Set(["s"]);
  it("labels every case", () => {
    expect(lineStatus(line(["a"]), pantry, staples)).toBe("have");
    expect(lineStatus(line(["b"]), pantry, staples)).toBe("missing");
    expect(lineStatus(line(["b", "s"]), pantry, staples)).toBe("assumed");
    expect(lineStatus(line(["b"], true), pantry, staples)).toBe("optional");
    expect(lineStatus(line([], false, false), pantry, staples)).toBe("check");
  });
});
