/**
 * Locale-aware formatting. Arabic uses the Gregorian calendar (ar-SA defaults to Umm al-Qura) and
 * a 24-hour clock; the user picks Western (0-9) or Arabic-Indic digits.
 */
import { DEFAULT_TZ, hhmm } from './time';

export type Lang = 'en' | 'ar';
export type Digits = 'latn' | 'arab';

export interface FormatOptions {
  lang: Lang;
  digits: Digits;
  tz?: string;
}

export function localeTag({ lang, digits }: FormatOptions): string {
  return lang === 'ar' ? `ar-SA-u-ca-gregory-nu-${digits}` : `en-GB-u-nu-${digits}`;
}

const cache = new Map<string, Intl.DateTimeFormat | Intl.NumberFormat | Intl.RelativeTimeFormat>();

function dtf(o: FormatOptions, opts: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `dt|${localeTag(o)}|${o.tz ?? DEFAULT_TZ}|${JSON.stringify(opts)}`;
  let f = cache.get(key) as Intl.DateTimeFormat | undefined;
  if (!f) {
    f = new Intl.DateTimeFormat(localeTag(o), {
      timeZone: o.tz ?? DEFAULT_TZ,
      hourCycle: 'h23',
      ...opts,
    });
    cache.set(key, f);
  }
  return f;
}

export function fmtNumber(
  n: number,
  o: FormatOptions,
  opts: Intl.NumberFormatOptions = {},
): string {
  const key = `nf|${localeTag(o)}|${JSON.stringify(opts)}`;
  let f = cache.get(key) as Intl.NumberFormat | undefined;
  if (!f) {
    f = new Intl.NumberFormat(localeTag(o), opts);
    cache.set(key, f);
  }
  return f.format(n);
}

export function fmtPercent(ratio: number, o: FormatOptions): string {
  return fmtNumber(ratio, o, { style: 'percent', maximumFractionDigits: 0 });
}

export function fmtDateTime(iso: string, o: FormatOptions): string {
  return dtf(o, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(iso));
}

export function fmtDateTimeSeconds(iso: string, o: FormatOptions): string {
  return dtf(o, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(iso));
}

export function fmtTime(iso: string | Date, o: FormatOptions): string {
  return dtf(o, { hour: '2-digit', minute: '2-digit' }).format(
    typeof iso === 'string' ? new Date(iso) : iso,
  );
}

export function fmtDay(iso: string, o: FormatOptions): string {
  return dtf(o, { weekday: 'short', day: 'numeric', month: 'short' }).format(new Date(iso));
}

/** "09:00:00" (schedule time) -> "09:00" with the chosen digits. */
export function fmtClock(t: string, o: FormatOptions): string {
  const s = hhmm(t);
  return o.digits === 'arab' ? s.replace(/\d/g, (d) => '٠١٢٣٤٥٦٧٨٩'[Number(d)]!) : s;
}

/** Short weekday name for an ISO weekday (1 = Monday .. 7 = Sunday). */
export function weekdayName(
  isoDay: number,
  o: FormatOptions,
  width: 'short' | 'long' = 'short',
): string {
  // 2026-11-02 is a Monday.
  const d = new Date(Date.UTC(2026, 10, 1 + isoDay, 12));
  return new Intl.DateTimeFormat(localeTag(o), { weekday: width, timeZone: 'UTC' }).format(d);
}

export function fmtRelative(iso: string, now: Date, o: FormatOptions): string {
  const key = `rt|${localeTag(o)}`;
  let f = cache.get(key) as Intl.RelativeTimeFormat | undefined;
  if (!f) {
    f = new Intl.RelativeTimeFormat(localeTag(o), { numeric: 'auto', style: 'short' });
    cache.set(key, f);
  }
  const diffS = Math.round((new Date(iso).getTime() - now.getTime()) / 1000);
  const abs = Math.abs(diffS);
  if (abs < 45) return f.format(0, 'second');
  if (abs < 3600) return f.format(Math.round(diffS / 60), 'minute');
  if (abs < 86400) return f.format(Math.round(diffS / 3600), 'hour');
  return f.format(Math.round(diffS / 86400), 'day');
}
