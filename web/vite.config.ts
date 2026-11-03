import preact from "@preact/preset-vite";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";
import { CSP } from "./csp.ts";

// The dev server injects inline scripts, so the policy applies to the build only.
const csp = (): Plugin => ({
  name: "pantrychef-csp",
  apply: "build",
  transformIndexHtml: {
    order: "pre",
    handler: (html) =>
      html.replace(
        "<!-- csp -->",
        `<meta http-equiv="Content-Security-Policy" content="${CSP}" />`,
      ),
  },
});

// The site is served from a GitHub Pages sub-path, so asset URLs stay relative.
export default defineConfig({
  base: "./",
  plugins: [preact(), csp()],
  test: { include: ["tests/**/*.test.ts"], environment: "node" },
});
