/**
 * Translation key checks (WEB-03), shared by the CLI script and its unit test.
 *
 * - Every key in one locale exists in the other (plural suffixes such as _one/_few/_other are
 *   folded to their base key, since Arabic has six plural forms and English two).
 * - No empty strings.
 * - The same {{placeholders}} are used by a key in every locale.
 * - Every literal key used in source with t('...') / i18nKey="..." exists.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

/** Flattens nested objects to dotted keys: { a: { b: 'x' } } -> { 'a.b': 'x' } */
export function flatten(obj, prefix = '', out = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) flatten(v, key, out);
    else out[key] = v;
  }
  return out;
}

export function baseKey(key) {
  return key.replace(PLURAL_SUFFIX, '');
}

function placeholders(value) {
  return new Set(
    [...String(value).matchAll(/\{\{\s*([\w.]+)\s*(?:,[^}]*)?\}\}/g)].map((m) => m[1]),
  );
}

/** Map of base key -> union of placeholders across that key's plural forms. */
function byBase(flat) {
  const out = new Map();
  for (const [k, v] of Object.entries(flat)) {
    const b = baseKey(k);
    const set = out.get(b) ?? new Set();
    for (const p of placeholders(v)) set.add(p);
    out.set(b, set);
  }
  return out;
}

/**
 * Compares locales. `locales` is { en: {...}, ar: {...} }. Returns a list of problems (strings);
 * an empty list means the check passes.
 */
export function compareLocales(locales) {
  const problems = [];
  const names = Object.keys(locales);
  const flat = Object.fromEntries(names.map((n) => [n, flatten(locales[n])]));
  const bases = Object.fromEntries(names.map((n) => [n, byBase(flat[n])]));
  for (const a of names) {
    for (const [k, v] of Object.entries(flat[a])) {
      if (typeof v !== 'string') problems.push(`${a}: ${k} is not a string`);
      else if (v.trim() === '') problems.push(`${a}: ${k} is empty`);
    }
    for (const b of names) {
      if (a === b) continue;
      for (const key of bases[a].keys()) {
        if (!bases[b].has(key)) problems.push(`${b}: missing key "${key}" (present in ${a})`);
      }
    }
  }
  const [first, ...rest] = names;
  for (const other of rest) {
    for (const [key, ph] of bases[first]) {
      const otherPh = bases[other].get(key);
      if (!otherPh) continue;
      const missing = [...ph].filter((p) => !otherPh.has(p) && p !== 'count');
      const extra = [...otherPh].filter((p) => !ph.has(p) && p !== 'count');
      if (missing.length || extra.length) {
        problems.push(
          `${other}: placeholders differ for "${key}" (${first}: ${[...ph].join(', ') || '-'}; ${other}: ${[...otherPh].join(', ') || '-'})`,
        );
      }
    }
  }
  return problems;
}

/** Literal translation keys used in source code. Template-literal keys are not checked. */
export function usedKeys(source) {
  const keys = new Set();
  const patterns = [
    /\bt\(\s*['"]([\w.-]+)['"]/g,
    /i18nKey=\{?['"]([\w.-]+)['"]/g,
    /['"](rules\.err\.[\w.-]+)['"]/g,
  ];
  for (const re of patterns) for (const m of source.matchAll(re)) keys.add(m[1]);
  return keys;
}

export function walk(dir, exts = ['.ts', '.tsx']) {
  const files = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) files.push(...walk(p, exts));
    else if (exts.some((e) => p.endsWith(e)) && !p.endsWith('.test.ts') && !p.endsWith('.test.tsx'))
      files.push(p);
  }
  return files;
}

export function checkSourceKeys(files, locale) {
  const known = new Set(Object.keys(flatten(locale)).map(baseKey));
  const problems = [];
  for (const file of files) {
    for (const key of usedKeys(readFileSync(file, 'utf8'))) {
      if (!known.has(key)) problems.push(`${file}: uses unknown key "${key}"`);
    }
  }
  return problems;
}
