import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './client';
import { HttpApiClient, toCamera, toEvent, toOverview, toSite, type CloudEvent } from './http';
import type { Session } from './models';

type Handler = (url: URL, init: RequestInit) => { status: number; body?: unknown };

function mockFetch(handler: Handler) {
  const calls: { method: string; path: string; body: unknown; auth: string | null }[] = [];
  const fn = vi.fn(async (input: URL | string, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const headers = (init.headers ?? {}) as Record<string, string>;
    calls.push({
      method: init.method ?? 'GET',
      path: url.pathname + url.search,
      body: init.body ? JSON.parse(String(init.body)) : undefined,
      auth: headers.Authorization ?? null,
    });
    const { status, body } = handler(url, init);
    return new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  });
  vi.stubGlobal('fetch', fn);
  return calls;
}

function client(initial: Session | null) {
  let session = initial;
  const onUnauthorized = vi.fn();
  const c = new HttpApiClient({
    baseUrl: 'http://api.test/api/v1/',
    getSession: () => session,
    saveSession: (s) => {
      session = s;
    },
    onUnauthorized,
  });
  return { c, onUnauthorized, session: () => session };
}

const SESSION: Session = {
  access_token: 'old-access',
  refresh_token: 'refresh-1',
  user: { id: 'u1', name: 'Sara', email: 'sara@example.sa', role: 'owner' },
};

afterEach(() => vi.unstubAllGlobals());

describe('adapters', () => {
  it('maps a cloud site, falling back to "other" for unknown industries', () => {
    const site = toSite({
      id: 's1', name: 'Olaya', name_ar: '', industry: 'spaceport', city: 'Riyadh',
      timezone: 'Asia/Riyadh', events_only: false, cameras_total: 4, cameras_online: 3,
      alerts_today: 2,
    }); // prettier-ignore
    expect(site.name_ar).toBeNull();
    expect(site.industry).toBe('other');
    expect(site.cameras_online).toBe(3);
  });

  it('maps a cloud camera', () => {
    const cam = toCamera({
      id: 'c1', site_id: 's1', name: 'Counter', source_redacted: 'rtsp://nvr/102', fps: 5,
      width: null, height: null, status: 'error', status_at: '2026-11-05T09:00:00Z',
      enabled: true, zones: [], lines: [],
    }); // prettier-ignore
    expect(cam.status).toBe('degraded');
    expect(cam.source).toBe('rtsp://nvr/102');
    expect(cam.resolution).toEqual([1280, 720]);
    expect(cam.last_frame_at).toBe('2026-11-05T09:00:00Z');
    expect(
      toCamera({
        ...cam,
        source_redacted: '',
        width: 1,
        height: 1,
        status: 'unknown',
        status_at: null,
      } as never).status,
    ).toBe('offline');
  });

  const event: CloudEvent = {
    id: 'e1', schema_version: '1', site_id: 's1', camera_id: 'c1', rule_id: 'r1',
    rule_type: 'zone_empty', severity: 'warning', state: 'triggered',
    condition_started_at: '2026-11-05T09:00:00Z', triggered_at: '2026-11-05T09:01:00Z',
    value: 0, message: 'desk empty', attributes: {}, verified: null,
    updated_at: '2026-11-05T09:02:00Z',
  } as unknown as CloudEvent; // prettier-ignore

  it('takes the newest feedback and shows Telegram answers by their author', () => {
    const e = toEvent({
      ...event,
      verified: false,
      feedback: [
        { is_true: true, channel: 'dashboard', comment: 'checked', created_at: '2026-11-05T09:03:00Z' },
        { is_true: false, channel: 'telegram', comment: 'telegram:sara_k', created_at: '2026-11-05T09:04:00Z' },
      ],
    }); // prettier-ignore
    expect(e.feedback).toEqual({
      verdict: 'false_alarm',
      note: '',
      by: 'sara_k',
      at: '2026-11-05T09:04:00Z',
    });
    expect(e.snapshot_url).toBeNull();
    expect('verified' in e).toBe(false);
  });

  it('derives the verdict from the list endpoint, which has no feedback rows', () => {
    expect(toEvent(event).feedback).toBeNull();
    expect(toEvent({ ...event, verified: true }).feedback?.verdict).toBe('correct');
  });

  it('fills every rule type in the overview', () => {
    const o = toOverview({
      site_id: 's1', date: '2026-11-05', alerts_total: 2, alerts_by_type: { zone_empty: 2 },
      false_alert_rate_7d: null, reviewed_7d: 0, footfall_by_hour: [], cameras_online: 1,
      cameras_total: 1,
    }); // prettier-ignore
    expect(o.alerts_by_type.zone_empty).toBe(2);
    expect(o.alerts_by_type.queue_length_over).toBe(0);
  });
});

describe('HttpApiClient', () => {
  it('signs in with the token, then reads who the user is', async () => {
    const calls = mockFetch((url) => {
      if (url.pathname.endsWith('/auth/login'))
        return { status: 200, body: { access_token: 'a1', refresh_token: 'r1', expires_at: 'x', organisation_id: 'o', role: 'site_manager' } }; // prettier-ignore
      return { status: 200, body: { user_id: 'u9', email: 'sm@x.sa', full_name: '', role: 'site_manager' } }; // prettier-ignore
    });
    const { c } = client(null);
    const s = await c.login('sm@x.sa', 'pw');
    expect(s).toEqual({
      access_token: 'a1',
      refresh_token: 'r1',
      expires_at: 'x',
      user: { id: 'u9', name: 'sm@x.sa', email: 'sm@x.sa', role: 'site_manager' },
    });
    expect(calls.map((x) => x.path)).toEqual(['/api/v1/auth/login', '/api/v1/auth/me']);
    expect(calls[1]?.auth).toBe('Bearer a1');
  });

  it('refreshes an expired token once for parallel requests, then retries them', async () => {
    let refreshed = false;
    const calls = mockFetch((url, init) => {
      const auth = (init.headers as Record<string, string>).Authorization;
      if (url.pathname.endsWith('/auth/refresh')) {
        refreshed = true;
        return { status: 200, body: { access_token: 'new-access', refresh_token: 'refresh-2', expires_at: 'y', organisation_id: 'o', role: 'owner' } }; // prettier-ignore
      }
      if (auth !== 'Bearer new-access') return { status: 401, body: { error: { code: 'unauthorized', message: 'expired' } } }; // prettier-ignore
      return { status: 200, body: [] };
    });
    const { c, session, onUnauthorized } = client(SESSION);
    await Promise.all([c.listSites(), c.listCameras(), c.listSites()]);
    expect(refreshed).toBe(true);
    expect(calls.filter((x) => x.path.endsWith('/auth/refresh'))).toHaveLength(1);
    expect(calls.find((x) => x.path.endsWith('/auth/refresh'))?.body).toEqual({
      refresh_token: 'refresh-1',
    });
    expect(session()?.access_token).toBe('new-access');
    expect(session()?.refresh_token).toBe('refresh-2');
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it('signs out when the refresh token is no longer valid', async () => {
    mockFetch(() => ({ status: 401, body: { error: { code: 'unauthorized', message: 'nope' } } }));
    const { c, onUnauthorized } = client(SESSION);
    await expect(c.listSites()).rejects.toMatchObject({ status: 401, message: 'nope' });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("reads the cloud's error body and turns a zone still in use into a conflict", async () => {
    mockFetch(() => ({
      status: 422,
      body: {
        error: {
          code: 'invalid_site_config',
          message: 'the site configuration would be invalid',
          details: [{ msg: 'Value error, rule r1: camera c1 has no zone desk' }],
        },
      },
    }));
    const { c } = client(SESSION);
    const err = await c.saveGeometry('c1', { zones: [], lines: [] }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    expect((err as ApiError).message).toBe('rule r1: camera c1 has no zone desk');
  });

  it('sends feedback in the cloud shape and returns the event with it', async () => {
    const calls = mockFetch((_url, init) => {
      if (init.method === 'POST') return { status: 201, body: {} };
      return { status: 200, body: { id: 'e1', verified: false, updated_at: 'z', feedback: [{ is_true: false, channel: 'dashboard', comment: 'staff', created_at: 'z' }] } }; // prettier-ignore
    });
    const { c } = client(SESSION);
    const e = await c.submitFeedback('e1', { verdict: 'false_alarm', note: 'staff' });
    expect(calls[0]).toMatchObject({ method: 'POST', path: '/api/v1/events/e1/feedback', body: { is_true: false, comment: 'staff' } }); // prettier-ignore
    expect(e.feedback?.verdict).toBe('false_alarm');
  });

  it('sends a new rule without the fields the cloud assigns', async () => {
    const calls = mockFetch(() => ({ status: 201, body: { rule: {}, recipient_ids: [] } }));
    const { c } = client(SESSION);
    await c.createRule('s1', {
      rule: { id: 'draft', type: 'zone_empty', camera_id: 'c1', zone_id: 'desk' } as never,
      recipient_ids: ['p1'],
    });
    expect(calls[0]?.body).toEqual({
      rule: { type: 'zone_empty', camera_id: 'c1', zone_id: 'desk' },
      recipient_ids: ['p1'],
    });
  });

  it('logs out with the refresh token', async () => {
    const calls = mockFetch(() => ({ status: 204 }));
    const { c } = client(SESSION);
    await c.logout();
    expect(calls[0]).toMatchObject({ path: '/api/v1/auth/logout', body: { refresh_token: 'refresh-1' } }); // prettier-ignore
  });
});
