/**
 * Time helpers. Everything on the wire is ISO 8601 UTC; screens show the site's local time
 * (default Asia/Riyadh) regardless of the browser's own timezone.
 */
export const DEFAULT_TZ = 'Asia/Riyadh';

interface LocalParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
  /** ISO weekday 1 = Monday .. 7 = Sunday */
  isoWeekday: number;
}

const partsFormatters = new Map<string, Intl.DateTimeFormat>();

function partsFormatter(tz: string): Intl.DateTimeFormat {
  let f = partsFormatters.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      weekday: 'short',
    });
    partsFormatters.set(tz, f);
  }
  return f;
}

const WEEKDAYS: Record<string, number> = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 };

export function localParts(date: Date | string, tz: string = DEFAULT_TZ): LocalParts {
  const d = typeof date === 'string' ? new Date(date) : date;
  const out: Record<string, string> = {};
  for (const p of partsFormatter(tz).formatToParts(d)) out[p.type] = p.value;
  return {
    year: Number(out.year),
    month: Number(out.month),
    day: Number(out.day),
    hour: Number(out.hour) % 24,
    minute: Number(out.minute),
    second: Number(out.second),
    isoWeekday: WEEKDAYS[out.weekday ?? 'Mon'] ?? 1,
  };
}

/** Offset of `tz` from UTC at the given instant, in minutes (Riyadh: +180). */
export function tzOffsetMinutes(date: Date, tz: string): number {
  const p = localParts(date, tz);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return Math.round((asUtc - Math.floor(date.getTime() / 1000) * 1000) / 60000);
}

/** Converts a wall-clock time in `tz` to a UTC Date. */
export function zonedToUtc(
  y: number,
  m: number,
  d: number,
  hh = 0,
  mm = 0,
  ss = 0,
  tz: string = DEFAULT_TZ,
): Date {
  const guess = new Date(Date.UTC(y, m - 1, d, hh, mm, ss));
  const offset = tzOffsetMinutes(guess, tz);
  const result = new Date(guess.getTime() - offset * 60000);
  // Correct once more in case the offset changed between the guess and the result (DST zones).
  const offset2 = tzOffsetMinutes(result, tz);
  return offset2 === offset ? result : new Date(guess.getTime() - offset2 * 60000);
}

/** Local calendar date (YYYY-MM-DD) of an instant in `tz`. */
export function localDateString(date: Date | string, tz: string = DEFAULT_TZ): string {
  const p = localParts(date, tz);
  return `${p.year}-${String(p.month).padStart(2, '0')}-${String(p.day).padStart(2, '0')}`;
}

/** UTC [start, end) of a local calendar day (YYYY-MM-DD) in `tz`. */
export function localDayRangeUtc(day: string, tz: string = DEFAULT_TZ): [string, string] {
  const [y, m, d] = day.split('-').map(Number) as [number, number, number];
  const start = zonedToUtc(y, m, d, 0, 0, 0, tz);
  const next = new Date(Date.UTC(y, m - 1, d + 1));
  const end = zonedToUtc(
    next.getUTCFullYear(),
    next.getUTCMonth() + 1,
    next.getUTCDate(),
    0,
    0,
    0,
    tz,
  );
  return [start.toISOString(), end.toISOString()];
}

/** "09:00:00" -> minutes since midnight */
export function timeToMinutes(t: string): number {
  const [h = '0', m = '0'] = t.split(':');
  return Number(h) * 60 + Number(m);
}

/** "09:00:00" -> "09:00" */
export function hhmm(t: string): string {
  return t.slice(0, 5);
}
