/**
 * Dashboard view models. The core shapes (Zone, Line, Rule, CameraConfig, Event, ...) come from
 * `types.ts`, which is generated from the shared pydantic schemas; the types below only add what
 * the cloud API returns *around* them (status, signed media URLs, feedback). Field names are
 * snake_case to match the FastAPI responses one to one.
 */
import type {
  CameraConfig,
  Direction,
  Event,
  EventState,
  Line,
  Rule,
  RuleType,
  Schedule,
  Severity,
  Zone,
} from './types';

export type {
  CameraConfig,
  Direction,
  Event,
  EventState,
  Line,
  Rule,
  RuleType,
  Schedule,
  Severity,
  Zone,
};

export const RULE_TYPES: readonly RuleType[] = [
  'queue_length_over',
  'zone_occupancy_over',
  'zone_empty',
  'presence_after_hours',
  'dwell_over',
  'line_crossing',
] as const;

export const SEVERITIES: readonly Severity[] = ['critical', 'warning', 'info'] as const;
export const EVENT_STATES: readonly EventState[] = ['triggered', 'cleared'] as const;

/** Rule types that need a zone (mirrors ZONE_RULES in vision_shared.schemas). */
export const ZONE_RULE_TYPES: ReadonlySet<RuleType> = new Set<RuleType>([
  'zone_occupancy_over',
  'zone_empty',
  'queue_length_over',
  'dwell_over',
  'presence_after_hours',
]);

/** The cloud's industries: those of the rule templates (DET-08) plus "other". */
export type Industry =
  'restaurant' | 'retail' | 'clinic' | 'hotel' | 'warehouse' | 'factory' | 'other';
export type CameraStatus = 'online' | 'degraded' | 'offline';
/** Roles inside one organisation, as the cloud defines them. */
export type Role = 'owner' | 'manager' | 'site_manager' | 'viewer';
export type Channel = 'whatsapp' | 'telegram' | 'email';
export type Verdict = 'correct' | 'false_alarm';

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
}

export interface Session {
  access_token: string;
  user: User;
  /** Long-lived token for POST /auth/refresh (real backend only; the mock has none). */
  refresh_token?: string;
  /** When the access token expires, ISO 8601. */
  expires_at?: string;
}

export interface SiteSummary {
  id: string;
  name: string;
  /** Optional Arabic display name, shown when the dashboard is in Arabic. */
  name_ar: string | null;
  timezone: string;
  industry: Industry;
  city: string;
  events_only: boolean;
  cameras_total: number;
  cameras_online: number;
  alerts_today: number;
}

export interface CameraView extends CameraConfig {
  site_id: string;
  name_ar: string | null;
  status: CameraStatus;
  last_frame_at: string | null;
  /** Signed URL of the latest snapshot, or null when the camera has never sent one. */
  snapshot_url: string | null;
  /** Pixel size of the analysed stream, used only to keep the editor's aspect ratio. */
  resolution: [number, number];
}

export interface GeometryUpdate {
  zones: Zone[];
  lines: Line[];
}

export interface EventFeedback {
  verdict: Verdict;
  note: string;
  by: string;
  at: string;
}

/** Normalised (0..1) box of a detected object, drawn over the snapshot in the event detail. */
export type NormBox = [number, number, number, number];

export interface AiCheck {
  verdict: 'confirmed' | 'rejected' | 'unsure';
  reason: string;
}

export interface EventView extends Event {
  snapshot_url: string | null;
  clip_url: string | null;
  feedback: EventFeedback | null;
}

export interface EventFilters {
  site_id?: string;
  camera_id?: string;
  rule_type?: RuleType;
  severity?: Severity;
  state?: EventState;
  verdict?: Verdict | 'none';
  /** Inclusive lower bound, ISO 8601 UTC. */
  from?: string;
  /** Exclusive upper bound, ISO 8601 UTC. */
  to?: string;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface Recipient {
  id: string;
  name: string;
  name_ar: string | null;
  channel: Channel;
}

/** A rule as stored by the cloud: the shared Rule plus who is alerted. */
export interface RuleWithRecipients {
  rule: Rule;
  recipient_ids: string[];
}

export interface HourlyFootfall {
  /** Local hour of day in the site's timezone, 0..23. */
  hour: number;
  in: number;
  out: number;
}

export interface SiteOverview {
  site_id: string;
  /** Local date (YYYY-MM-DD) in the site's timezone. */
  date: string;
  alerts_total: number;
  alerts_by_type: Record<RuleType, number>;
  /** Share of reviewed alerts marked "False alarm" over the last 7 days, 0..1, or null if none reviewed. */
  false_alert_rate_7d: number | null;
  reviewed_7d: number;
  footfall_by_hour: HourlyFootfall[];
  cameras_online: number;
  cameras_total: number;
}
