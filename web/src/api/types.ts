/* Generated from src/api/schema.json by json-schema-to-typescript (npm run gen:types). Do not edit. */

/**
 * This interface was referenced by `VisionShared`'s JSON-Schema
 * via the `definition` "Direction".
 */
export type Direction = 'in' | 'out' | 'any';
/**
 * This interface was referenced by `VisionShared`'s JSON-Schema
 * via the `definition` "RuleType".
 */
export type RuleType =
  | 'zone_occupancy_over'
  | 'zone_empty'
  | 'queue_length_over'
  | 'dwell_over'
  | 'line_crossing'
  | 'presence_after_hours';
/**
 * This interface was referenced by `VisionShared`'s JSON-Schema
 * via the `definition` "Severity".
 */
export type Severity = 'info' | 'warning' | 'critical';
export type EventState = 'triggered' | 'cleared';
/**
 * This interface was referenced by `VisionShared`'s JSON-Schema
 * via the `definition` "EventState".
 */
export type EventState1 = 'triggered' | 'cleared';
export type Direction1 = 'in' | 'out' | 'any';
export type Severity1 = 'info' | 'warning' | 'critical';

/**
 * Generated from vision_shared.schemas (schema_version 1.0) by scripts/export_json_schema.py. Do not edit by hand.
 */
export interface VisionShared {
  CameraConfig?: CameraConfig;
  Detection?: Detection;
  Direction?: Direction;
  Event?: Event;
  EventState?: EventState1;
  Line?: Line;
  Rule?: Rule;
  RuleType?: RuleType;
  Schedule?: Schedule;
  Severity?: Severity;
  SiteConfig?: SiteConfig;
  Zone?: Zone;
}
/**
 * This interface was referenced by `VisionShared`'s JSON-Schema
 * via the `definition` "CameraConfig".
 */
export interface CameraConfig {
  enabled: boolean;
  fps: number;
  id: string;
  lines: Line[];
  name: string;
  /**
   * rtsp:// URL, file path, or replay JSONL
   */
  source: string;
  zones: Zone[];
}
/**
 * A counting line. "in" means crossing from the left side to the right side when walking
 * from `start` to `end` (the dashboard draws an arrow to show it).
 *
 * This interface was referenced by `VisionShared`'s JSON-Schema
 * via the `definition` "Line".
 */
export interface Line {
  /**
   * @minItems 2
   * @maxItems 2
   */
  end: [number, number];
  id: string;
  name: string;
  /**
   * @minItems 2
   * @maxItems 2
   */
  start: [number, number];
}
/**
 * This interface was referenced by `VisionShared`'s JSON-Schema
 * via the `definition` "Zone".
 */
export interface Zone {
  id: string;
  name: string;
  /**
   * @minItems 3
   */
  polygon: [number, number][];
}
/**
 * One detected object in pixel coordinates (x1, y1, x2, y2) of the analysed frame.
 *
 * This interface was referenced by `VisionShared`'s JSON-Schema
 * via the `definition` "Detection".
 */
export interface Detection {
  /**
   * @minItems 4
   * @maxItems 4
   */
  box: [number, number, number, number];
  class_name: string;
  confidence: number;
  track_id: number | null;
}
/**
 * This interface was referenced by `VisionShared`'s JSON-Schema
 * via the `definition` "Event".
 */
export interface Event {
  attributes: {
    [k: string]: unknown;
  };
  camera_id: string;
  cleared_at: string | null;
  clip_key: string | null;
  condition_started_at: string;
  created_at: string;
  id: string;
  message: string;
  needs_verification: boolean;
  rule_id: string;
  rule_type: RuleType;
  schema_version: string;
  severity: Severity;
  site_id: string;
  snapshot_key: string | null;
  state: EventState;
  triggered_at: string;
  /**
   * count, seconds of dwell, or number of crossings
   */
  value: number;
}
/**
 * One alert rule on one camera.
 *
 * Meaning of `threshold` and `min_duration_s` per type:
 *   zone_occupancy_over / queue_length_over: more than `threshold` objects in the zone for
 *       at least `min_duration_s`.
 *   zone_empty: no object in the zone for at least `min_duration_s` (threshold unused).
 *   dwell_over: any single object stays in the zone longer than `min_duration_s`.
 *   line_crossing: at least `threshold` crossings in `direction` within `window_s`.
 *   presence_after_hours: at least `threshold` objects in the zone for `min_duration_s` while
 *       the schedule (the after-hours window) is active.
 *
 * This interface was referenced by `VisionShared`'s JSON-Schema
 * via the `definition` "Rule".
 */
export interface Rule {
  camera_id: string;
  /**
   * @minItems 1
   */
  classes: string[];
  clear_after_s: number;
  cooldown_s: number;
  direction: Direction1;
  enabled: boolean;
  id: string;
  line_id: string | null;
  min_confidence: number;
  min_duration_s: number;
  name: string;
  schedule: Schedule | null;
  severity: Severity1;
  threshold: number;
  type: RuleType;
  verify: boolean;
  window_s: number;
  zone_id: string | null;
}
/**
 * Active window in the site's local time. `start > end` means the window crosses midnight
 * (e.g. 23:00 to 06:00). `days` are ISO weekdays of the window's start: 1=Monday .. 7=Sunday.
 *
 * This interface was referenced by `VisionShared`'s JSON-Schema
 * via the `definition` "Schedule".
 */
export interface Schedule {
  days: number[];
  end: string;
  start: string;
}
/**
 * This interface was referenced by `VisionShared`'s JSON-Schema
 * via the `definition` "SiteConfig".
 */
export interface SiteConfig {
  cameras: CameraConfig[];
  /**
   * sensitive sites: upload events without snapshots or clips
   */
  events_only: boolean;
  id: string;
  name: string;
  rules: Rule[];
  timezone: string;
  version: number;
}
