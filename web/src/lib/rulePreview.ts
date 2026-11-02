/**
 * Plain-language sentence for a rule, e.g. "Alert Store Manager on WhatsApp when more than 5
 * people wait in Checkout Queue for 2 minutes, daily 09:00–23:00." Built from translation keys
 * under `preview.*`, so Arabic gets proper grammar (dual and plural forms via i18next plurals).
 */
import type { TFunction } from 'i18next';
import type { Channel, Rule, Schedule } from '../api/models';
import { fmtClock, fmtNumber, weekdayName, type FormatOptions } from './format';
import { timeToMinutes } from './time';

export interface PreviewRecipient {
  name: string;
  channel: Channel;
}

export interface PreviewContext extends FormatOptions {
  zoneName?: string | null;
  lineName?: string | null;
  recipients: PreviewRecipient[];
}

/** Saudi week order, Sunday first (ISO weekday numbers). */
export const WEEK_ORDER = [7, 1, 2, 3, 4, 5, 6] as const;

function n(value: number, o: FormatOptions): string {
  return fmtNumber(value, o, { maximumFractionDigits: 1 });
}

export function describeDuration(seconds: number, t: TFunction, o: FormatOptions): string {
  const s = Math.max(0, Math.round(seconds));
  const unit = (key: 'hours' | 'minutes' | 'seconds', count: number) =>
    t(`preview.unit.${key}`, { count, n: n(count, o) });
  if (s < 60) return unit('seconds', s);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const parts: string[] = [];
  if (h) parts.push(unit('hours', h));
  if (m) parts.push(unit('minutes', m));
  if (sec && !h) parts.push(unit('seconds', sec));
  return parts.reduce((a, b) => t('preview.unit.join', { a, b }));
}

function isAllDay(s: Schedule): boolean {
  return timeToMinutes(s.start) === 0 && timeToMinutes(s.end) >= 23 * 60 + 59;
}

export function describeSchedule(
  schedule: Schedule | null,
  t: TFunction,
  o: FormatOptions,
): string {
  if (!schedule) return t('preview.schedule.always');
  const days = [...new Set(schedule.days)];
  const allDays = days.length === 7;
  if (allDays && isAllDay(schedule)) return t('preview.schedule.always');
  const from = fmtClock(schedule.start, o);
  const to = fmtClock(schedule.end, o);
  const hours = isAllDay(schedule)
    ? t('preview.schedule.allDay')
    : t('preview.schedule.hours', { from, to });
  if (allDays) return t('preview.schedule.daily', { hours });
  // A contiguous run in Saudi week order (e.g. Sun–Thu) reads better as a range.
  const positions = days
    .map((d) => WEEK_ORDER.indexOf(d as (typeof WEEK_ORDER)[number]))
    .sort((a, b) => a - b);
  const contiguous = positions.every((p, i) => i === 0 || p === positions[i - 1]! + 1);
  if (contiguous && positions.length >= 3) {
    return t('preview.schedule.range', {
      first: weekdayName(WEEK_ORDER[positions[0]!]!, o),
      last: weekdayName(WEEK_ORDER[positions[positions.length - 1]!]!, o),
      hours,
    });
  }
  const list = new Intl.ListFormat(o.lang, { style: 'long', type: 'conjunction' }).format(
    positions.map((p) => weekdayName(WEEK_ORDER[p]!, o)),
  );
  return t('preview.schedule.days', { days: list, hours });
}

export function describeRecipients(
  recipients: PreviewRecipient[],
  t: TFunction,
  o: FormatOptions,
): string {
  if (recipients.length === 0) return t('preview.lead.logOnly');
  const list = (items: string[]) =>
    new Intl.ListFormat(o.lang, { style: 'long', type: 'conjunction' }).format(items);
  const channels = new Set(recipients.map((r) => r.channel));
  const who =
    channels.size === 1
      ? t('preview.lead.whoOn', {
          who: list(recipients.map((r) => r.name)),
          channel: t(`channel.${recipients[0]!.channel}`),
        })
      : list(
          recipients.map((r) =>
            t('preview.lead.nameVia', { name: r.name, channel: t(`channel.${r.channel}`) }),
          ),
        );
  return t('preview.lead.alert', { who });
}

function objectKind(rule: Rule): 'person' | 'vehicle' {
  return rule.classes.includes('person') ? 'person' : 'vehicle';
}

export function buildRulePreview(rule: Rule, ctx: PreviewContext, t: TFunction): string {
  const kind = objectKind(rule);
  const placeholder = t('preview.unnamed');
  const vars = {
    lead: describeRecipients(ctx.recipients, t, ctx),
    zone: ctx.zoneName?.trim() || placeholder,
    line: ctx.lineName?.trim() || placeholder,
    duration: describeDuration(rule.min_duration_s, t, ctx),
    window: describeDuration(rule.window_s, t, ctx),
    schedule: describeSchedule(rule.schedule, t, ctx),
    objects: t(`preview.objects.${kind}`, { count: rule.threshold, n: n(rule.threshold, ctx) }),
    anyone: t(`preview.any.${kind}`),
    direction: t(`preview.direction.${rule.direction}`),
    interpolation: { escapeValue: false },
  };
  switch (rule.type) {
    case 'presence_after_hours':
      return t(
        rule.threshold <= 1 ? 'preview.sentence.presence_any' : 'preview.sentence.presence_n',
        vars,
      );
    default:
      return t(`preview.sentence.${rule.type}`, vars);
  }
}
