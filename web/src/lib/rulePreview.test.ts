import { describe, expect, it } from 'vitest';
import type { Rule } from '../api/models';
import { createI18n } from '../i18n';
import { buildRulePreview, describeDuration, type PreviewContext } from './rulePreview';

function rule(partial: Partial<Rule> & Pick<Rule, 'type'>): Rule {
  return {
    id: 'r1',
    name: 'test',
    camera_id: 'cam',
    zone_id: 'z',
    line_id: null,
    classes: ['person'],
    threshold: 1,
    min_duration_s: 0,
    window_s: 60,
    direction: 'any',
    clear_after_s: 10,
    cooldown_s: 300,
    min_confidence: 0.4,
    schedule: null,
    severity: 'warning',
    verify: false,
    enabled: true,
    ...partial,
  };
}

const queue = rule({
  type: 'queue_length_over',
  threshold: 5,
  min_duration_s: 120,
  schedule: { days: [1, 2, 3, 4, 5, 6, 7], start: '09:00:00', end: '23:00:00' },
});

const en = createI18n('en').t;
const ar = createI18n('ar').t;
const EN: Omit<PreviewContext, 'recipients'> = { lang: 'en', digits: 'latn' };
const AR: Omit<PreviewContext, 'recipients'> = { lang: 'ar', digits: 'latn' };

describe('rule preview sentence (English)', () => {
  it('matches the plan example for a queue rule', () => {
    const s = buildRulePreview(
      queue,
      {
        ...EN,
        zoneName: 'Checkout Queue',
        recipients: [{ name: 'Store Manager', channel: 'whatsapp' }],
      },
      en,
    );
    expect(s).toBe(
      'Alert Store Manager on WhatsApp when more than 5 people wait in Checkout Queue for 2 minutes, daily 09:00–23:00.',
    );
  });

  it('lists mixed channels per person and records only when nobody is alerted', () => {
    const mixed = buildRulePreview(
      queue,
      {
        ...EN,
        zoneName: 'Checkout Queue',
        recipients: [
          { name: 'Store Manager', channel: 'whatsapp' },
          { name: 'Owner', channel: 'email' },
        ],
      },
      en,
    );
    expect(mixed.startsWith('Alert Store Manager (WhatsApp) and Owner (email) when')).toBe(true);
    const empty = buildRulePreview(
      rule({
        type: 'zone_empty',
        min_duration_s: 300,
        schedule: { days: [1, 2, 3, 4, 5, 6, 7], start: '09:00:00', end: '23:30:00' },
      }),
      { ...EN, zoneName: 'Cashier Station', recipients: [] },
      en,
    );
    expect(empty).toBe(
      'Record an alert when nobody is in Cashier Station for 5 minutes, daily 09:00–23:30.',
    );
  });

  it('describes after-hours windows on Saudi working days and line crossings', () => {
    const afterHours = buildRulePreview(
      rule({
        type: 'presence_after_hours',
        min_duration_s: 30,
        schedule: { days: [7, 1, 2, 3, 4], start: '23:00:00', end: '07:00:00' },
      }),
      { ...EN, zoneName: 'Stock Room', recipients: [{ name: 'Owner', channel: 'whatsapp' }] },
      en,
    );
    expect(afterHours).toBe(
      'Alert Owner on WhatsApp when anyone is in Stock Room for 30 seconds after hours, Sun–Thu 23:00–07:00.',
    );
    const line = buildRulePreview(
      rule({
        type: 'line_crossing',
        zone_id: null,
        line_id: 'l',
        threshold: 30,
        window_s: 600,
        direction: 'in',
      }),
      {
        ...EN,
        lineName: 'Door Line',
        recipients: [{ name: 'Shift Supervisor', channel: 'telegram' }],
      },
      en,
    );
    expect(line).toBe(
      'Alert Shift Supervisor on Telegram when 30 people or more cross Door Line going in within 10 minutes, at any time.',
    );
  });

  it('counts vehicles and uses singular units', () => {
    const s = buildRulePreview(
      rule({
        type: 'zone_occupancy_over',
        threshold: 3,
        min_duration_s: 60,
        classes: ['car', 'truck'],
      }),
      { ...EN, zoneName: 'Dock', recipients: [] },
      en,
    );
    expect(s).toBe(
      'Record an alert when more than 3 vehicles are in Dock for 1 minute, at any time.',
    );
  });

  it('formats compound durations', () => {
    expect(describeDuration(90, en, EN)).toBe('1 minute 30 seconds');
    expect(describeDuration(5400, en, EN)).toBe('1 hour 30 minutes');
    expect(describeDuration(7200, en, EN)).toBe('2 hours');
  });

  it('shows a placeholder when no zone is chosen yet', () => {
    const s = buildRulePreview(queue, { ...EN, recipients: [] }, en);
    expect(s).toContain('wait in (choose one) for');
  });
});

describe('rule preview sentence (Arabic)', () => {
  it('builds the queue rule with correct plural and dual forms', () => {
    const s = buildRulePreview(
      queue,
      { ...AR, zoneName: 'طابور الدفع', recipients: [{ name: 'مدير الفرع', channel: 'whatsapp' }] },
      ar,
    );
    expect(s).toBe(
      'نبّه مدير الفرع عبر واتساب عندما ينتظر أكثر من 5 أشخاص في طابور الدفع لمدة دقيقتين، يوميًا من 09:00 إلى 23:00.',
    );
  });

  it('uses Arabic-Indic digits when chosen', () => {
    const s = buildRulePreview(
      queue,
      {
        lang: 'ar',
        digits: 'arab',
        zoneName: 'طابور الدفع',
        recipients: [{ name: 'مدير الفرع', channel: 'whatsapp' }],
      },
      ar,
    );
    expect(s).toBe(
      'نبّه مدير الفرع عبر واتساب عندما ينتظر أكثر من ٥ أشخاص في طابور الدفع لمدة دقيقتين، يوميًا من ٠٩:٠٠ إلى ٢٣:٠٠.',
    );
  });

  it('names the Sunday-to-Thursday window and the 11+ plural form', () => {
    const s = buildRulePreview(
      rule({
        type: 'presence_after_hours',
        threshold: 12,
        min_duration_s: 60,
        schedule: { days: [7, 1, 2, 3, 4], start: '23:00:00', end: '07:00:00' },
      }),
      { ...AR, zoneName: 'غرفة المخزون', recipients: [{ name: 'المالك', channel: 'whatsapp' }] },
      ar,
    );
    expect(s).toBe(
      'نبّه المالك عبر واتساب عند رصد 12 شخصًا أو أكثر في غرفة المخزون لمدة دقيقة واحدة خارج أوقات العمل، من الأحد إلى الخميس، من 23:00 إلى 07:00.',
    );
  });

  it('joins durations with و and uses the few form for 3..10', () => {
    expect(describeDuration(90, ar, AR)).toBe('دقيقة واحدة و30 ثانية');
    expect(describeDuration(180, ar, AR)).toBe('3 دقائق');
    expect(describeDuration(7200, ar, AR)).toBe('ساعتين');
  });
});
