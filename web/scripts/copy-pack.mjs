// Copy a pack into public/pack so the dev server and the build can serve it.
// Usage: node scripts/copy-pack.mjs fixture | node scripts/copy-pack.mjs real
import { copyFileSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..", "..");
const sources = {
  fixture: { dir: join(root, "tests", "fixtures", "pack"), match: /^(core|text)\.v2\.json$/ },
  real: { dir: join(root, "build", "pack"), match: /^(core|text)\.v2\.json\.gz$/ },
};
const which = process.argv[2];
const src = sources[which];
if (!src) {
  console.error("usage: copy-pack.mjs fixture|real");
  process.exit(1);
}
const dest = join(here, "..", process.env.PANTRY_PUBLIC ?? "public", "pack");
mkdirSync(dest, { recursive: true });
for (const f of readdirSync(dest)) if (f !== ".gitignore") rmSync(join(dest, f));
const files = readdirSync(src.dir).filter((f) => src.match.test(f));
if (files.length < 2) {
  console.error(`no pack files in ${src.dir}`);
  process.exit(1);
}
// The fixture is plain JSON. Gzip it so the e2e run uses the same loading path as production.
for (const f of files) {
  if (which === "fixture") writeFileSync(join(dest, `${f}.gz`), gzipSync(readFileSync(join(src.dir, f)), { mtime: 0 }));
  else copyFileSync(join(src.dir, f), join(dest, f));
}
console.log(`copied ${files.join(", ")} to public/pack`);
