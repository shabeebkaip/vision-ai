#!/usr/bin/env node
// Fails (exit 1) when en.json and ar.json disagree or source uses an unknown key. Run: npm run i18n:check
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkSourceKeys, compareLocales, walk } from './i18n-check-lib.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const load = (lng) => JSON.parse(readFileSync(join(root, 'src', 'i18n', `${lng}.json`), 'utf8'));
const en = load('en');
const ar = load('ar');

const problems = [...compareLocales({ en, ar }), ...checkSourceKeys(walk(join(root, 'src')), en)];
if (problems.length) {
  console.error(`i18n check failed with ${problems.length} problem(s):`);
  for (const p of problems) console.error(`  - ${p}`);
  process.exit(1);
}
console.log('i18n check passed: en and ar have the same keys and placeholders.');
