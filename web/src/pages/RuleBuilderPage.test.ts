import { describe, expect, it } from 'vitest';
import { defaultsFor, toRule, validateForm, type RuleForm } from './RuleBuilderPage';

const base: RuleForm = {
  type: 'queue_length_over',
  name: 'Checkout queue too long',
  cameraId: 'ngm-cashier',
  zoneId: 'checkout-queue',
  lineId: '',
  objects: 'person',
  threshold: 5,
  durationMin: 2,
  windowMin: 10,
  direction: 'in',
  scheduleOn: true,
  days: [7, 1, 2, 3, 4, 5, 6],
  start: '09:00',
  end: '23:00',
  cooldownMin: 10,
  severity: 'warning',
  verify: false,
  recipientIds: ['rcp-ngm-manager'],
};

describe('rule builder form -> shared Rule', () => {
  it('converts minutes to seconds, sorts days and formats the schedule like the schema', () => {
    const r = toRule(base, 'rule-1');
    expect(r).toMatchObject({
      id: 'rule-1',
      type: 'queue_length_over',
      zone_id: 'checkout-queue',
      line_id: null,
      classes: ['person'],
      threshold: 5,
      min_duration_s: 120,
      cooldown_s: 600,
      direction: 'any',
      schedule: { days: [1, 2, 3, 4, 5, 6, 7], start: '09:00:00', end: '23:00:00' },
    });
  });

  it('builds a line rule with a window and no zone', () => {
    const r = toRule(
      { ...base, type: 'line_crossing', lineId: 'door-line', scheduleOn: false },
      'r',
    );
    expect(r).toMatchObject({
      zone_id: null,
      line_id: 'door-line',
      window_s: 600,
      min_duration_s: 0,
      direction: 'in',
      schedule: null,
    });
  });

  it('always keeps a schedule for after-hours presence (schema requires one)', () => {
    const f = {
      ...base,
      type: 'presence_after_hours' as const,
      ...defaultsFor('presence_after_hours'),
      scheduleOn: false,
    };
    expect(toRule(f, 'r').schedule).toEqual({
      days: [1, 2, 3, 4, 5, 6, 7],
      start: '23:00:00',
      end: '06:00:00',
    });
  });

  it('validates required targets like the pydantic Rule validator', () => {
    expect(validateForm(base)).toEqual({});
    expect(validateForm({ ...base, zoneId: '' })).toHaveProperty('zoneId');
    expect(validateForm({ ...base, type: 'line_crossing', lineId: '' })).toHaveProperty('lineId');
    expect(validateForm({ ...base, name: ' ', days: [] })).toMatchObject({
      name: 'rules.err.name',
      days: 'rules.err.days',
    });
  });
});
