import type { ApiClient, FeedbackInput } from './client';
import { ApiError } from './client';
import type {
  CameraView,
  EventFilters,
  EventView,
  GeometryUpdate,
  Page,
  Recipient,
  RuleWithRecipients,
  Session,
  SiteOverview,
  SiteSummary,
} from './models';

type Query = Record<string, string | number | null | undefined>;

/**
 * Real backend client. Endpoint paths are the dashboard's expectation of the FastAPI routes
 * (see web/README.md, "API contract"); they are relative to VITE_API_BASE_URL.
 */
export class HttpApiClient implements ApiClient {
  readonly mode = 'http' as const;
  private readonly baseUrl: string;
  private readonly getToken: () => string | null;
  private readonly onUnauthorized: () => void;

  constructor(opts: {
    baseUrl: string;
    getToken: () => string | null;
    onUnauthorized: () => void;
  }) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, '');
    this.getToken = opts.getToken;
    this.onUnauthorized = opts.onUnauthorized;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    query?: Query,
  ): Promise<T> {
    const url = new URL(this.baseUrl + path, window.location.origin);
    for (const [k, v] of Object.entries(query ?? {})) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
    }
    const headers: Record<string, string> = { Accept: 'application/json' };
    const token = this.getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const res = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.status === 401) this.onUnauthorized();
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const data = (await res.json()) as { detail?: unknown };
        if (typeof data.detail === 'string') detail = data.detail;
      } catch {
        /* not JSON */
      }
      throw new ApiError(res.status, detail);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  login(email: string, password: string): Promise<Session> {
    return this.request('POST', '/auth/login', { email, password });
  }
  async logout(): Promise<void> {
    await this.request<void>('POST', '/auth/logout').catch(() => undefined);
  }
  listSites(): Promise<SiteSummary[]> {
    return this.request('GET', '/sites');
  }
  getOverview(siteId: string, localDate: string): Promise<SiteOverview> {
    return this.request('GET', `/sites/${encodeURIComponent(siteId)}/overview`, undefined, {
      date: localDate,
    });
  }
  listCameras(siteId?: string): Promise<CameraView[]> {
    return this.request('GET', '/cameras', undefined, { site_id: siteId });
  }
  getCamera(cameraId: string): Promise<CameraView> {
    return this.request('GET', `/cameras/${encodeURIComponent(cameraId)}`);
  }
  saveGeometry(cameraId: string, geometry: GeometryUpdate): Promise<CameraView> {
    return this.request('PUT', `/cameras/${encodeURIComponent(cameraId)}/geometry`, geometry);
  }
  listRules(siteId: string): Promise<RuleWithRecipients[]> {
    return this.request('GET', `/sites/${encodeURIComponent(siteId)}/rules`);
  }
  createRule(siteId: string, body: RuleWithRecipients): Promise<RuleWithRecipients> {
    return this.request('POST', `/sites/${encodeURIComponent(siteId)}/rules`, body);
  }
  listRecipients(siteId: string): Promise<Recipient[]> {
    return this.request('GET', `/sites/${encodeURIComponent(siteId)}/recipients`);
  }
  listEvents(filters: EventFilters, cursor?: string | null, limit = 30): Promise<Page<EventView>> {
    return this.request('GET', '/events', undefined, { ...filters, cursor, limit });
  }
  getEvent(eventId: string): Promise<EventView> {
    return this.request('GET', `/events/${encodeURIComponent(eventId)}`);
  }
  submitFeedback(eventId: string, input: FeedbackInput): Promise<EventView> {
    return this.request('POST', `/events/${encodeURIComponent(eventId)}/feedback`, input);
  }
}
