#!/usr/bin/env node
// Licence guard for npm packages (the Python side is scripts/licence_check.py at the repo root).
// Fails on copyleft / non-commercial licences or a missing licence field. Run: npm run licences
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const FORBIDDEN =
  /\b(AGPL|Affero|GPL|SSPL|BUSL|Business Source|Non-?Commercial|CC-BY-NC|Commons Clause)\b/i;
const ALLOWED =
  /\b(MIT|MIT-0|ISC|BSD-2-Clause|BSD-3-Clause|0BSD|Apache-2\.0|BlueOak-1\.0\.0|CC0-1\.0|CC-BY-4\.0|Unlicense|Python-2\.0|PSF-2\.0|MPL-2\.0)\b/;
// MPL-2.0 (file-level copyleft) is allowed for build tools only: lightningcss via Tailwind.
// CC-BY-4.0 is caniuse-lite's browser data, used at build time.

const seen = new Map();
function walk(dir) {
  if (!existsSync(dir)) return;
  for (const name of readdirSync(dir)) {
    if (name.startsWith('.')) continue;
    const p = join(dir, name);
    if (name.startsWith('@')) {
      walk(p);
      continue;
    }
    const pj = join(p, 'package.json');
    if (existsSync(pj)) {
      try {
        const j = JSON.parse(readFileSync(pj, 'utf8'));
        if (j.name && j.version) {
          let lic = j.license ?? j.licenses?.map((l) => l.type).join(' OR ') ?? '';
          if (typeof lic === 'object') lic = lic.type ?? '';
          seen.set(`${j.name}@${j.version}`, String(lic));
        }
      } catch {
        /* not a package */
      }
    }
    walk(join(p, 'node_modules'));
  }
}
walk(join(root, 'node_modules'));

const failures = [];
for (const [pkg, lic] of seen) {
  if (!lic) failures.push(`${pkg}: no licence field`);
  else if (FORBIDDEN.test(lic) && !/\bOR\b/.test(lic)) failures.push(`${pkg}: ${lic}`);
  else if (!ALLOWED.test(lic)) failures.push(`${pkg}: unrecognised licence "${lic}"`);
}
if (failures.length) {
  console.error(`Licence check failed (${failures.length}):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(`Licence check passed for ${seen.size} npm packages.`);
