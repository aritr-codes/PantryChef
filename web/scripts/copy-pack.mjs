// Copy a pack into public/pack so the dev server and the build can serve it.
// Usage: node scripts/copy-pack.mjs fixture | node scripts/copy-pack.mjs real
import { copyFileSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..", "..");
const sources = {
  fixture: { dir: join(root, "tests", "fixtures", "pack"), match: /^(core|text)\.v1\.json$/ },
  real: { dir: join(root, "build", "pack"), match: /^(core|text)\.v1\.json\.gz$/ },
};
const which = process.argv[2];
const src = sources[which];
if (!src) {
  console.error("usage: copy-pack.mjs fixture|real");
  process.exit(1);
}
const dest = join(here, "..", "public", "pack");
mkdirSync(dest, { recursive: true });
for (const f of readdirSync(dest)) if (f !== ".gitignore") rmSync(join(dest, f));
const files = readdirSync(src.dir).filter((f) => src.match.test(f));
if (files.length < 2) {
  console.error(`no pack files in ${src.dir}`);
  process.exit(1);
}
for (const f of files) copyFileSync(join(src.dir, f), join(dest, f));
console.log(`copied ${files.join(", ")} to public/pack`);
