import type { ApiClient, FeedbackInput } from './client';
import { ApiError } from './client';
import type {
  CameraStatus,
  CameraView,
  EventFeedback,
  EventFilters,
  EventView,
  GeometryUpdate,
  Industry,
  Page,
  Recipient,
  Role,
  Rule,
  RuleType,
  RuleWithRecipients,
  Session,
  SiteOverview,
  SiteSummary,
} from './models';
import { RULE_TYPES } from './models';

type Query = Record<string, string | number | null | undefined>;

// --------------------------------------------------------------------------- cloud shapes
// What the FastAPI backend returns (cloud/src/vision_cloud/schemas.py and api/dashboard.py).
// The dashboard's view models differ in places; the adapters below translate.

export interface CloudToken {
  access_token: string;
  refresh_token: string;
  expires_at: string;
  organisation_id: string;
  role: Role;
}

export interface CloudMe {
  user_id: string;
  email: string;
  full_name: string;
  role: Role;
}

export interface CloudSite {
  id: string;
  name: string;
  name_ar: string;
  industry: string;
  city: string;
  timezone: string;
  events_only: boolean;
  cameras_total: number;
  cameras_online: number;
  alerts_today: number;
}

export interface CloudCamera {
  id: string;
  site_id: string;
  name: string;
  source_redacted: string;
  fps: number;
  width: number | null;
  height: number | null;
  status: string;
  status_at: string | null;
  enabled: boolean;
  zones: CameraView['zones'];
  lines: CameraView['lines'];
}

export interface CloudFeedback {
  is_true: boolean;
  channel: string;
  comment: string;
  created_at: string;
}

export type CloudEvent = Omit<EventView, 'snapshot_url' | 'clip_url' | 'feedback'> & {
  verified: boolean | null;
  updated_at: string;
  snapshot_url?: string | null;
  clip_url?: string | null;
  feedback?: CloudFeedback[];
};

export interface CloudOverview extends Omit<SiteOverview, 'alerts_by_type'> {
  alerts_by_type: Partial<Record<RuleType, number>>;
}

// --------------------------------------------------------------------------- adapters

const INDUSTRIES: readonly Industry[] = [
  'restaurant',
  'retail',
  'clinic',
  'hotel',
  'warehouse',
  'factory',
  'other',
];

export function toSite(s: CloudSite): SiteSummary {
  return {
    id: s.id,
    name: s.name,
    name_ar: s.name_ar || null,
    timezone: s.timezone,
    industry: (INDUSTRIES as readonly string[]).includes(s.industry)
      ? (s.industry as Industry)
      : 'other',
    city: s.city,
    events_only: s.events_only,
    cameras_total: s.cameras_total,
    cameras_online: s.cameras_online,
    alerts_today: s.alerts_today,
  };
}

/** The cloud knows online / offline / error and "unknown" before the first heartbeat. */
export function toCameraStatus(status: string): CameraStatus {
  if (status === 'online') return 'online';
  if (status === 'error') return 'degraded';
  return 'offline';
}

export function toCamera(c: CloudCamera): CameraView {
  return {
    id: c.id,
    site_id: c.site_id,
    name: c.name,
    name_ar: null,
    source: c.source_redacted,
    fps: c.fps,
    enabled: c.enabled,
    zones: c.zones,
    lines: c.lines,
    status: toCameraStatus(c.status),
    last_frame_at: c.status_at,
    snapshot_url: null, // the latest-frame snapshot arrives with the edge snapshot service (EDG-03)
    resolution: [c.width ?? 1280, c.height ?? 720],
  };
}

/** Telegram answers store "telegram:<who>" as the comment: show it as the author, not a note. */
export function toFeedback(f: CloudFeedback): EventFeedback {
  const fromTelegram = f.channel === 'telegram' && f.comment.startsWith('telegram:');
  return {
    verdict: f.is_true ? 'correct' : 'false_alarm',
    note: fromTelegram ? '' : f.comment,
    by: fromTelegram ? f.comment.slice('telegram:'.length) : '',
    at: f.created_at,
  };
}

export function toEvent(e: CloudEvent): EventView {
  const { verified, updated_at, feedback, snapshot_url, clip_url, ...event } = e;
  let latest: EventFeedback | null = null;
  const newest = (feedback ?? []).reduce<CloudFeedback | null>(
    (best, f) => (best === null || f.created_at > best.created_at ? f : best),
    null,
  );
  if (newest !== null) {
    latest = toFeedback(newest);
  } else if (verified !== null) {
    // the list endpoint carries only the verdict, not who gave it
    latest = { verdict: verified ? 'correct' : 'false_alarm', note: '', by: '', at: updated_at };
  }
  return {
    ...event,
    snapshot_url: snapshot_url ?? null,
    clip_url: clip_url ?? null,
    feedback: latest,
  };
}

export function toOverview(o: CloudOverview): SiteOverview {
  const byType = Object.fromEntries(RULE_TYPES.map((t) => [t, o.alerts_by_type[t] ?? 0]));
  return { ...o, alerts_by_type: byType as Record<RuleType, number> };
}

/** The rule the dashboard sends, without the fields the cloud assigns. */
function ruleBody(rule: Rule): Partial<Rule> {
  const { id: _id, ...rest } = rule as Rule & {
    site_id?: string;
    created_at?: string;
    updated_at?: string;
  };
  const clean: Record<string, unknown> = { ...rest };
  delete clean.site_id;
  delete clean.created_at;
  delete clean.updated_at;
  return clean as Partial<Rule>;
}

// --------------------------------------------------------------------------- the client

/**
 * Real backend client against the FastAPI cloud (VITE_API_BASE_URL, e.g.
 * http://localhost:8000/api/v1). Access tokens last 15 minutes: on a 401 the client refreshes
 * once with the stored refresh token and retries; if that fails the user is signed out.
 */
export class HttpApiClient implements ApiClient {
  readonly mode = 'http' as const;
  private readonly baseUrl: string;
  private readonly getSession: () => Session | null;
  private readonly saveSession: (s: Session | null) => void;
  private readonly onUnauthorized: () => void;
  private refreshing: Promise<boolean> | null = null;

  constructor(opts: {
    baseUrl: string;
    getSession: () => Session | null;
    saveSession: (s: Session | null) => void;
    onUnauthorized: () => void;
  }) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, '');
    this.getSession = opts.getSession;
    this.saveSession = opts.saveSession;
    this.onUnauthorized = opts.onUnauthorized;
  }

  private async send(
    method: string,
    path: string,
    body: unknown,
    query: Query | undefined,
    token: string | null,
  ): Promise<Response> {
    const url = new URL(this.baseUrl + path, window.location.origin);
    for (const [k, v] of Object.entries(query ?? {})) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
    }
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    return fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    query?: Query,
  ): Promise<T> {
    let res = await this.send(method, path, body, query, this.getSession()?.access_token ?? null);
    if (res.status === 401 && !path.startsWith('/auth/')) {
      if (await this.refresh()) {
        res = await this.send(method, path, body, query, this.getSession()?.access_token ?? null);
      }
      if (res.status === 401) this.onUnauthorized();
    }
    if (!res.ok) throw await toApiError(res);
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  /** One refresh at a time, however many requests failed together. */
  private refresh(): Promise<boolean> {
    if (!this.refreshing) {
      this.refreshing = this.doRefresh().finally(() => {
        this.refreshing = null;
      });
    }
    return this.refreshing;
  }

  private async doRefresh(): Promise<boolean> {
    const session = this.getSession();
    if (!session?.refresh_token) return false;
    const res = await this.send(
      'POST',
      '/auth/refresh',
      { refresh_token: session.refresh_token },
      undefined,
      null,
    );
    if (!res.ok) return false;
    const token = (await res.json()) as CloudToken;
    this.saveSession({
      ...session,
      access_token: token.access_token,
      refresh_token: token.refresh_token,
      expires_at: token.expires_at,
      user: { ...session.user, role: token.role },
    });
    return true;
  }

  async login(email: string, password: string): Promise<Session> {
    const token = await this.request<CloudToken>('POST', '/auth/login', { email, password });
    const meRes = await this.send('GET', '/auth/me', undefined, undefined, token.access_token);
    if (!meRes.ok) throw await toApiError(meRes);
    const me = (await meRes.json()) as CloudMe;
    return {
      access_token: token.access_token,
      refresh_token: token.refresh_token,
      expires_at: token.expires_at,
      user: { id: me.user_id, name: me.full_name || me.email, email: me.email, role: me.role },
    };
  }

  async logout(): Promise<void> {
    const refresh = this.getSession()?.refresh_token;
    if (!refresh) return;
    await this.request<void>('POST', '/auth/logout', { refresh_token: refresh }).catch(
      () => undefined,
    );
  }

  async listSites(): Promise<SiteSummary[]> {
    return (await this.request<CloudSite[]>('GET', '/sites')).map(toSite);
  }

  async getOverview(siteId: string, localDate: string): Promise<SiteOverview> {
    const o = await this.request<CloudOverview>(
      'GET',
      `/sites/${encodeURIComponent(siteId)}/overview`,
      undefined,
      { date: localDate },
    );
    return toOverview(o);
  }

  async listCameras(siteId?: string): Promise<CameraView[]> {
    const cams = await this.request<CloudCamera[]>('GET', '/cameras', undefined, {
      site_id: siteId,
    });
    return cams.map(toCamera);
  }

  async getCamera(cameraId: string): Promise<CameraView> {
    return toCamera(
      await this.request<CloudCamera>('GET', `/cameras/${encodeURIComponent(cameraId)}`),
    );
  }

  async saveGeometry(cameraId: string, geometry: GeometryUpdate): Promise<CameraView> {
    try {
      const cam = await this.request<CloudCamera>(
        'PATCH',
        `/cameras/${encodeURIComponent(cameraId)}`,
        { zones: geometry.zones, lines: geometry.lines },
      );
      return toCamera(cam);
    } catch (err) {
      // A rule still uses a zone or line the editor removed: the editor shows that as a conflict.
      if (err instanceof ApiError && err.code === 'invalid_site_config') {
        const inUse = err.details.find((d) => /has no (zone|line)/.test(d));
        if (inUse) throw new ApiError(409, inUse.replace(/^Value error, /, ''), err.code);
      }
      throw err;
    }
  }

  listRules(siteId: string): Promise<RuleWithRecipients[]> {
    return this.request('GET', `/sites/${encodeURIComponent(siteId)}/rules`);
  }

  createRule(siteId: string, body: RuleWithRecipients): Promise<RuleWithRecipients> {
    return this.request('POST', `/sites/${encodeURIComponent(siteId)}/rules`, {
      rule: ruleBody(body.rule),
      recipient_ids: body.recipient_ids,
    });
  }

  async listRecipients(siteId: string): Promise<Recipient[]> {
    const rows = await this.request<Recipient[]>(
      'GET',
      `/sites/${encodeURIComponent(siteId)}/recipients`,
    );
    return rows.map((r) => ({ ...r, name_ar: r.name_ar || null }));
  }

  async listEvents(
    filters: EventFilters,
    cursor?: string | null,
    limit = 30,
  ): Promise<Page<EventView>> {
    const page = await this.request<Page<CloudEvent>>('GET', '/events', undefined, {
      ...filters,
      cursor,
      limit,
    });
    return { items: page.items.map(toEvent), next_cursor: page.next_cursor };
  }

  async getEvent(eventId: string): Promise<EventView> {
    return toEvent(await this.request<CloudEvent>('GET', `/events/${encodeURIComponent(eventId)}`));
  }

  async submitFeedback(eventId: string, input: FeedbackInput): Promise<EventView> {
    await this.request('POST', `/events/${encodeURIComponent(eventId)}/feedback`, {
      is_true: input.verdict === 'correct',
      comment: input.note,
    });
    return this.getEvent(eventId);
  }
}

/** The cloud answers errors as {"error": {"code", "message", "details"}}; FastAPI's own
 *  validation errors as {"detail": ...}. */
async function toApiError(res: Response): Promise<ApiError> {
  let message = res.statusText;
  let code: string | undefined;
  let details: string[] = [];
  try {
    const data = (await res.json()) as {
      error?: { code?: string; message?: string; details?: { msg?: string }[] };
      detail?: unknown;
    };
    if (data.error) {
      message = data.error.message ?? message;
      code = data.error.code;
      details = (data.error.details ?? []).map((d) => String(d.msg ?? ''));
    } else if (typeof data.detail === 'string') {
      message = data.detail;
    }
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status, message, code, details);
}
