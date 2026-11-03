// Check that public/pack holds exactly the pack files whose hashes are committed in pack-hashes.json.
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dir = join(web, "public", "pack");
const expected = JSON.parse(readFileSync(join(web, "pack-hashes.json"), "utf8")).files;
const present = readdirSync(dir).filter((f) => f !== ".gitignore");
const problems = [];
for (const f of present) if (!expected[f]) problems.push(`unexpected file ${f}`);
for (const [name, want] of Object.entries(expected)) {
  let data;
  try {
    data = readFileSync(join(dir, name));
  } catch {
    problems.push(`missing ${name}`);
    continue;
  }
  const got = createHash("sha256").update(data).digest("hex");
  if (got !== want.sha256 || data.length !== want.size) problems.push(`${name}: hash or size differs from pack-hashes.json`);
}
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log(`pack verified: ${Object.keys(expected).join(", ")}`);
