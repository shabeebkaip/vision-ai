import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  baseKey,
  checkSourceKeys,
  compareLocales,
  flatten,
  usedKeys,
  walk,
} from './i18n-check-lib.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const load = (lng) => JSON.parse(readFileSync(join(root, 'src', 'i18n', `${lng}.json`), 'utf8'));

describe('i18n key check', () => {
  it('passes for the shipped en.json and ar.json', () => {
    expect(compareLocales({ en: load('en'), ar: load('ar') })).toEqual([]);
  });

  it('passes for the source code: every literal t() key exists', () => {
    expect(checkSourceKeys(walk(join(root, 'src')), load('en'))).toEqual([]);
  });

  it('reports a key missing from Arabic', () => {
    const problems = compareLocales({ en: { a: { b: 'x', c: 'y' } }, ar: { a: { b: 'س' } } });
    expect(problems).toEqual(['ar: missing key "a.c" (present in en)']);
  });

  it('reports a key missing from English and empty values', () => {
    const problems = compareLocales({ en: { a: '' }, ar: { a: 'س', extra: 'ص' } });
    expect(problems).toContain('en: a is empty');
    expect(problems).toContain('en: missing key "extra" (present in ar)');
  });

  it('folds plural forms: English one/other matches Arabic zero..other', () => {
    const en = { n_one: '{{n}} item', n_other: '{{n}} items' };
    const ar = {
      n_zero: 'لا شيء',
      n_one: 'عنصر',
      n_two: 'عنصران',
      n_few: '{{n}} عناصر',
      n_many: '{{n}} عنصرًا',
      n_other: '{{n}} عنصر',
    };
    expect(compareLocales({ en, ar })).toEqual([]);
    expect(baseKey('n_few')).toBe('n');
  });

  it('reports mismatched placeholders', () => {
    const problems = compareLocales({ en: { hi: 'Hello {{name}}' }, ar: { hi: 'مرحبا {{user}}' } });
    expect(problems[0]).toMatch(/placeholders differ for "hi"/);
  });

  it('finds literal keys in source', () => {
    const keys = usedKeys(`t('a.b'); t("c.d", { n }); <Trans i18nKey="e.f" />; t(\`dyn.\${x}\`)`);
    expect([...keys].sort()).toEqual(['a.b', 'c.d', 'e.f']);
    expect(flatten({ a: { b: { c: 'x' } } })).toEqual({ 'a.b.c': 'x' });
  });
});
