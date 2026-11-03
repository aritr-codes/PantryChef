import preact from "@preact/preset-vite";
import { defineConfig } from "vitest/config";

// The site is served from a GitHub Pages sub-path, so asset URLs stay relative.
export default defineConfig({
  base: "./",
  plugins: [preact()],
  test: { include: ["tests/**/*.test.ts"], environment: "node" },
});
