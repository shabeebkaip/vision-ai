/**
 * In-memory implementation of ApiClient with Riyadh demo data. It validates writes the same way
 * the shared pydantic schemas do (normalised points, zone/line references), so the screens meet
 * the same errors they will meet on the real backend.
 */
import type { ApiClient, FeedbackInput } from '../client';
import { ApiError } from '../client';
import type {
  CameraView,
  EventFilters,
  EventView,
  GeometryUpdate,
  Page,
  Recipient,
  RuleType,
  RuleWithRecipients,
  Session,
  SiteOverview,
  SiteSummary,
} from '../models';
import { RULE_TYPES, ZONE_RULE_TYPES } from '../models';
import { isValidPolygon } from '../../lib/geometry';
import { localDateString, localParts } from '../../lib/time';
import {
  MOCK_TZ,
  buildEvents,
  buildSites,
  edgeMessage,
  footfallShape,
  mulberry32,
  objectsFor,
  type MockCamera,
  type MockSite,
  type SeedEvent,
} from './seed';
import { clipDataUrl, snapshotDataUrl } from './snapshots';

export const MOCK_PASSWORD = 'demo1234';

export interface MockOptions {
  now?: () => Date;
  latencyMs?: number;
  /** Add a new event roughly every 90 s so the feed's polling has something to show. */
  live?: boolean;
}

const clone = <T>(v: T): T => structuredClone(v);

function osdClock(iso: string): string {
  const p = localParts(iso, MOCK_TZ);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${p.year}-${pad(p.month)}-${pad(p.day)}  ${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
}

function isNight(iso: string): boolean {
  const h = localParts(iso, MOCK_TZ).hour;
  return h < 6 || h >= 23;
}

export class MockApiClient implements ApiClient {
  readonly mode = 'mock' as const;
  private readonly now: () => Date;
  private readonly latencyMs: number;
  private readonly live: boolean;
  private readonly sites: MockSite[];
  private events: SeedEvent[];
  private readonly media = new Map<string, string>();
  private lastLive: number;
  private liveCount = 0;
  private userName = 'Demo User';

  constructor(opts: MockOptions = {}) {
    this.now = opts.now ?? (() => new Date());
    this.latencyMs = opts.latencyMs ?? 250;
    this.live = opts.live ?? false;
    this.sites = buildSites();
    this.events = buildEvents(this.sites, this.now());
    this.lastLive = this.now().getTime();
  }

  private async delay<T>(value: T): Promise<T> {
    if (this.latencyMs > 0) await new Promise((r) => setTimeout(r, this.latencyMs));
    return clone(value);
  }

  private site(siteId: string): MockSite {
    const s = this.sites.find((x) => x.id === siteId);
    if (!s) throw new ApiError(404, `site ${siteId} not found`);
    return s;
  }

  private camera(cameraId: string): MockCamera {
    for (const s of this.sites) {
      const c = s.cameras.find((x) => x.config.id === cameraId);
      if (c) return c;
    }
    throw new ApiError(404, `camera ${cameraId} not found`);
  }

  private cameraView(c: MockCamera): CameraView {
    const now = this.now();
    const lastFrame =
      c.status === 'offline'
        ? new Date(now.getTime() - 26 * 3600000)
        : new Date(now.getTime() - (c.status === 'degraded' ? 95 : 4) * 1000);
    const key = `cam:${c.config.id}`;
    let url = this.media.get(key);
    if (!url) {
      url = snapshotDataUrl({
        scene: c.scene,
        label: `${c.osd}  ${c.config.name}`,
        clock: osdClock(lastFrame.toISOString()),
        objects: c.idle,
        night: isNight(lastFrame.toISOString()),
        seed: c.config.id,
      });
      this.media.set(key, url);
    }
    return {
      ...c.config,
      site_id: c.site_id,
      name_ar: c.name_ar,
      status: c.status,
      last_frame_at: lastFrame.toISOString(),
      snapshot_url: url,
      resolution: c.resolution,
    };
  }

  private eventView(e: SeedEvent): EventView {
    const cam = this.camera(e.camera_id);
    const opts = {
      scene: cam.scene,
      label: `${cam.osd}  ${cam.config.name}`,
      clock: osdClock(e.triggered_at),
      objects: e.objects,
      night: isNight(e.triggered_at),
      seed: e.id,
    };
    let snap = this.media.get(`snap:${e.id}`);
    if (!snap) {
      snap = snapshotDataUrl(opts);
      this.media.set(`snap:${e.id}`, snap);
    }
    let clip = this.media.get(`clip:${e.id}`);
    if (!clip) {
      clip = clipDataUrl(opts);
      this.media.set(`clip:${e.id}`, clip);
    }
    const { objects: _objects, ...rest } = e;
    return {
      ...rest,
      snapshot_url: e.snapshot_key ? snap : null,
      clip_url: e.clip_key ? clip : null,
    };
  }

  /** In live mode, append a fresh queue event every ~90 s of wall-clock time. */
  private maybeAddLiveEvent(): void {
    if (!this.live) return;
    const now = this.now();
    if (now.getTime() - this.lastLive < 90_000) return;
    this.lastLive = now.getTime();
    const site = this.sites[this.liveCount % 2 === 0 ? 0 : 1]!;
    const rr = site.rules.find((r) => r.rule.type === 'queue_length_over')!;
    const cam = this.camera(rr.rule.camera_id);
    const rng = mulberry32(now.getTime() & 0xffffffff);
    const value = rr.rule.threshold + 1 + Math.floor(rng() * 3);
    const held = rr.rule.min_duration_s + 15;
    const objects = objectsFor(rng, rr.rule, cam, value);
    const id = `evt-live-${++this.liveCount}-${rr.rule.id}`;
    this.events.unshift({
      schema_version: '1.0',
      id,
      site_id: site.id,
      camera_id: cam.config.id,
      rule_id: rr.rule.id,
      rule_type: rr.rule.type,
      severity: rr.rule.severity,
      state: 'triggered',
      condition_started_at: new Date(now.getTime() - held * 1000).toISOString(),
      triggered_at: now.toISOString(),
      cleared_at: null,
      value,
      message: edgeMessage(rr.rule, cam, value, held),
      attributes: { boxes: objects.map((o) => o.box), longest_wait_s: held + 120 },
      snapshot_key: `${site.id}/${cam.config.id}/${id}.jpg`,
      clip_key: `${site.id}/${cam.config.id}/${id}.mp4`,
      needs_verification: false,
      created_at: now.toISOString(),
      snapshot_url: null,
      clip_url: null,
      feedback: null,
      objects,
    });
  }

  async login(email: string, password: string): Promise<Session> {
    if (!email.includes('@') || password !== MOCK_PASSWORD) {
      await this.delay(null);
      throw new ApiError(401, 'Invalid email or password');
    }
    const name = email
      .split('@')[0]!
      .replace(/[._-]+/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
    this.userName = name;
    return this.delay({
      access_token: `mock.${btoa(email)}.${Date.now()}`,
      user: { id: 'usr-demo', name, email, role: 'owner' },
    });
  }

  async logout(): Promise<void> {
    await this.delay(null);
  }

  async listSites(): Promise<SiteSummary[]> {
    const today = localDateString(this.now(), MOCK_TZ);
    return this.delay(
      this.sites.map((s) => ({
        id: s.id,
        name: s.name,
        name_ar: s.name_ar,
        timezone: MOCK_TZ,
        industry: s.industry,
        city: s.city,
        events_only: false,
        cameras_total: s.cameras.length,
        cameras_online: s.cameras.filter((c) => c.status !== 'offline').length,
        alerts_today: this.events.filter(
          (e) => e.site_id === s.id && localDateString(e.triggered_at, MOCK_TZ) === today,
        ).length,
      })),
    );
  }

  async getOverview(siteId: string, localDate: string): Promise<SiteOverview> {
    const site = this.site(siteId);
    const now = this.now();
    const byType = Object.fromEntries(RULE_TYPES.map((t) => [t, 0])) as Record<RuleType, number>;
    let total = 0;
    for (const e of this.events) {
      if (e.site_id !== siteId || localDateString(e.triggered_at, MOCK_TZ) !== localDate) continue;
      byType[e.rule_type] += 1;
      total += 1;
    }
    const weekAgo = now.getTime() - 7 * 86400000;
    const reviewed = this.events.filter(
      (e) => e.site_id === siteId && e.feedback && new Date(e.triggered_at).getTime() >= weekAgo,
    );
    const falseAlarms = reviewed.filter((e) => e.feedback?.verdict === 'false_alarm').length;
    const isToday = localDate === localDateString(now, MOCK_TZ);
    const lastHour = isToday ? localParts(now, MOCK_TZ).hour : 23;
    const rng = mulberry32(
      [...`${siteId}${localDate}`].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) >>> 0, 7),
    );
    const footfall = [];
    for (let h = 0; h <= lastHour; h++) {
      const base = footfallShape(site.industry, h);
      const inCount = Math.max(0, Math.round(base * (0.8 + rng() * 0.4)));
      const outBase = footfallShape(site.industry, (h + 23) % 24);
      footfall.push({
        hour: h,
        in: inCount,
        out: Math.max(0, Math.round(outBase * (0.75 + rng() * 0.4))),
      });
    }
    return this.delay({
      site_id: siteId,
      date: localDate,
      alerts_total: total,
      alerts_by_type: byType,
      false_alert_rate_7d: reviewed.length ? falseAlarms / reviewed.length : null,
      reviewed_7d: reviewed.length,
      footfall_by_hour: footfall,
      cameras_online: site.cameras.filter((c) => c.status !== 'offline').length,
      cameras_total: site.cameras.length,
    });
  }

  async listCameras(siteId?: string): Promise<CameraView[]> {
    const sites = siteId ? [this.site(siteId)] : this.sites;
    return this.delay(sites.flatMap((s) => s.cameras.map((c) => this.cameraView(c))));
  }

  async getCamera(cameraId: string): Promise<CameraView> {
    return this.delay(this.cameraView(this.camera(cameraId)));
  }

  async saveGeometry(cameraId: string, geometry: GeometryUpdate): Promise<CameraView> {
    const cam = this.camera(cameraId);
    const site = this.site(cam.site_id);
    const inRange = (p: [number, number]) => p.every((v) => v >= 0 && v <= 1);
    const ids = [...geometry.zones.map((z) => z.id), ...geometry.lines.map((l) => l.id)];
    if (new Set(ids).size !== ids.length)
      throw new ApiError(422, 'zone and line ids must be unique');
    for (const z of geometry.zones) {
      if (!isValidPolygon(z.polygon) || !z.polygon.every(inRange))
        throw new ApiError(422, `zone ${z.id}: polygon needs 3+ points normalised to 0..1`);
    }
    for (const l of geometry.lines) {
      if (
        !inRange(l.start) ||
        !inRange(l.end) ||
        (l.start[0] === l.end[0] && l.start[1] === l.end[1])
      )
        throw new ApiError(
          422,
          `line ${l.id}: start and end must differ and be normalised to 0..1`,
        );
    }
    for (const { rule } of site.rules.filter((r) => r.rule.camera_id === cameraId)) {
      if (rule.zone_id && !geometry.zones.some((z) => z.id === rule.zone_id))
        throw new ApiError(409, `zone ${rule.zone_id} is used by rule "${rule.name}"`);
      if (rule.line_id && !geometry.lines.some((l) => l.id === rule.line_id))
        throw new ApiError(409, `line ${rule.line_id} is used by rule "${rule.name}"`);
    }
    cam.config = { ...cam.config, zones: clone(geometry.zones), lines: clone(geometry.lines) };
    return this.delay(this.cameraView(cam));
  }

  async listRules(siteId: string): Promise<RuleWithRecipients[]> {
    return this.delay(this.site(siteId).rules);
  }

  async createRule(siteId: string, body: RuleWithRecipients): Promise<RuleWithRecipients> {
    const site = this.site(siteId);
    const r = body.rule;
    const cam = site.cameras.find((c) => c.config.id === r.camera_id);
    if (!cam) throw new ApiError(422, `unknown camera ${r.camera_id}`);
    if (site.rules.some((x) => x.rule.id === r.id))
      throw new ApiError(409, `rule id ${r.id} exists`);
    if (ZONE_RULE_TYPES.has(r.type) && !cam.config.zones.some((z) => z.id === r.zone_id))
      throw new ApiError(422, `rule type ${r.type} needs zone_id`);
    if (r.type === 'line_crossing' && !cam.config.lines.some((l) => l.id === r.line_id))
      throw new ApiError(422, 'line_crossing needs line_id');
    if (r.type === 'presence_after_hours' && !r.schedule)
      throw new ApiError(422, 'presence_after_hours needs a schedule (the after-hours window)');
    site.rules.push(clone(body));
    return this.delay(body);
  }

  async listRecipients(siteId: string): Promise<Recipient[]> {
    return this.delay(this.site(siteId).recipients);
  }

  async listEvents(
    filters: EventFilters,
    cursor?: string | null,
    limit = 30,
  ): Promise<Page<EventView>> {
    this.maybeAddLiveEvent();
    const matching = this.events.filter((e) => {
      if (filters.site_id && e.site_id !== filters.site_id) return false;
      if (filters.camera_id && e.camera_id !== filters.camera_id) return false;
      if (filters.rule_type && e.rule_type !== filters.rule_type) return false;
      if (filters.severity && e.severity !== filters.severity) return false;
      if (filters.state && e.state !== filters.state) return false;
      if (filters.verdict === 'none' && e.feedback) return false;
      if (filters.verdict && filters.verdict !== 'none' && e.feedback?.verdict !== filters.verdict)
        return false;
      if (filters.from && e.triggered_at < filters.from) return false;
      if (filters.to && e.triggered_at >= filters.to) return false;
      return true;
    });
    const start = cursor ? Number(cursor) : 0;
    const items = matching.slice(start, start + limit).map((e) => this.eventView(e));
    const next = start + limit < matching.length ? String(start + limit) : null;
    return this.delay({ items, next_cursor: next });
  }

  async getEvent(eventId: string): Promise<EventView> {
    const e = this.events.find((x) => x.id === eventId);
    if (!e) {
      await this.delay(null);
      throw new ApiError(404, 'event not found');
    }
    return this.delay(this.eventView(e));
  }

  async submitFeedback(eventId: string, input: FeedbackInput): Promise<EventView> {
    const e = this.events.find((x) => x.id === eventId);
    if (!e) throw new ApiError(404, 'event not found');
    e.feedback = {
      verdict: input.verdict,
      note: input.note.trim(),
      by: this.userName,
      at: this.now().toISOString(),
    };
    return this.delay(this.eventView(e));
  }
}
