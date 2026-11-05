import { describe, expect, it } from 'vitest';
import { RULE_TYPES } from '../models';
import { ApiError } from '../client';
import { MockApiClient } from './mockClient';

const NOW = new Date('2026-11-02T15:00:00Z');
const api = () => new MockApiClient({ latencyMs: 0, now: () => NOW });

describe('MockApiClient demo data', () => {
  it('has three Riyadh sites and about 60 events covering all six rule types', async () => {
    const client = api();
    const sites = await client.listSites();
    expect(sites.map((s) => s.industry)).toEqual(['restaurant', 'retail', 'warehouse']);
    expect(sites.every((s) => s.timezone === 'Asia/Riyadh' && s.name_ar)).toBe(true);
    const all = await client.listEvents({}, null, 500);
    expect(all.items.length).toBe(60);
    expect(new Set(all.items.map((e) => e.rule_type))).toEqual(new Set(RULE_TYPES));
    expect(all.items.every((e) => new Date(e.triggered_at) <= NOW)).toBe(true);
  });

  it('pages with a cursor', async () => {
    const client = api();
    const first = await client.listEvents({}, null, 25);
    const second = await client.listEvents({}, first.next_cursor, 25);
    expect(first.items).toHaveLength(25);
    expect(second.items[0]!.id).not.toBe(first.items[0]!.id);
  });

  it('refuses to delete a zone that a rule still uses (like SiteConfig validation)', async () => {
    const client = api();
    const cam = await client.getCamera('ngm-cashier');
    await expect(client.saveGeometry(cam.id, { zones: [], lines: [] })).rejects.toBeInstanceOf(
      ApiError,
    );
  });

  it('rejects coordinates outside 0..1 and saves valid ones', async () => {
    const client = api();
    const cam = await client.getCamera('ngm-cashier');
    const bad = {
      ...cam.zones[0]!,
      polygon: [
        [0, 0],
        [1.2, 0],
        [1, 1],
      ] as [number, number][],
    };
    await expect(
      client.saveGeometry(cam.id, { zones: [bad, cam.zones[1]!], lines: [] }),
    ).rejects.toThrow(/normalised/);
    const moved = {
      ...cam.zones[0]!,
      polygon: [
        [0.1, 0.6],
        [0.5, 0.6],
        [0.5, 0.95],
      ] as [number, number][],
    };
    const saved = await client.saveGeometry(cam.id, { zones: [moved, cam.zones[1]!], lines: [] });
    expect(saved.zones[0]!.polygon).toEqual(moved.polygon);
  });

  it('stores feedback on an event', async () => {
    const client = api();
    const { items } = await client.listEvents({ verdict: 'none' }, null, 1);
    const updated = await client.submitFeedback(items[0]!.id, {
      verdict: 'false_alarm',
      note: ' cleaner ',
    });
    expect(updated.feedback).toMatchObject({ verdict: 'false_alarm', note: 'cleaner' });
  });
});
