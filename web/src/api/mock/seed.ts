/**
 * Demo data for the mock API: three Riyadh sites (a restaurant, a pharmacy and a warehouse) with
 * cameras, zones, lines, rules, recipients and about 60 events over the last 7 days. Names are
 * fictional. Everything is generated from a fixed seed relative to "now", so the overview always
 * has a today and screenshots are repeatable within a day.
 */
import type {
  CameraConfig,
  CameraStatus,
  EventView,
  Industry,
  NormBox,
  Recipient,
  Rule,
  RuleType,
  RuleWithRecipients,
  Severity,
} from '../models';
import { pointInPolygon, type Point } from '../../lib/geometry';
import { localParts, timeToMinutes, zonedToUtc } from '../../lib/time';
import type { Scene, SceneObject } from './snapshots';

export const MOCK_TZ = 'Asia/Riyadh';

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface MockCamera {
  config: CameraConfig;
  site_id: string;
  name_ar: string;
  status: CameraStatus;
  scene: Scene;
  resolution: [number, number];
  osd: string;
  /** Typical people in the latest snapshot. */
  idle: SceneObject[];
}

export interface MockSite {
  id: string;
  name: string;
  name_ar: string;
  industry: Industry;
  city: string;
  cameras: MockCamera[];
  rules: RuleWithRecipients[];
  recipients: Recipient[];
}

const ALL_DAYS = [1, 2, 3, 4, 5, 6, 7];
const SUN_THU = [1, 2, 3, 4, 7];

const person = (cx: number, bottom: number, h: number): SceneObject => {
  const w = h * 0.36;
  return { kind: 'person', box: [cx - w / 2, bottom - h, cx + w / 2, bottom] };
};

function rule(partial: Partial<Rule> & Pick<Rule, 'id' | 'name' | 'type' | 'camera_id'>): Rule {
  return {
    zone_id: null,
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

function camera(
  site_id: string,
  id: string,
  name: string,
  name_ar: string,
  scene: Scene,
  status: CameraStatus,
  osd: string,
  geometry: Pick<CameraConfig, 'zones' | 'lines'>,
  idle: SceneObject[],
): MockCamera {
  return {
    site_id,
    name_ar,
    status,
    scene,
    osd,
    idle,
    resolution: [1280, 720],
    config: {
      id,
      name,
      source: `rtsp://***@nvr.local:554/Streaming/Channels/${osd.replace(/\D/g, '')}02`,
      fps: 5,
      enabled: true,
      ...geometry,
    },
  };
}

export function buildSites(): MockSite[] {
  const restaurant: MockSite = {
    id: 'najd-grill-malqa',
    name: 'Najd Grill House – Al Malqa',
    name_ar: 'مطعم مشويات نجد – الملقا',
    industry: 'restaurant',
    city: 'Riyadh',
    recipients: [
      { id: 'rcp-ngm-manager', name: 'Store Manager', name_ar: 'مدير الفرع', channel: 'whatsapp' },
      {
        id: 'rcp-ngm-shift',
        name: 'Shift Supervisor',
        name_ar: 'مشرف الوردية',
        channel: 'whatsapp',
      },
      { id: 'rcp-ngm-owner', name: 'Owner', name_ar: 'المالك', channel: 'email' },
    ],
    cameras: [
      camera(
        'najd-grill-malqa',
        'ngm-entrance',
        'Main entrance',
        'المدخل الرئيسي',
        'entrance',
        'online',
        'CAM 01',
        {
          zones: [
            {
              id: 'waiting-lobby',
              name: 'Waiting Lobby',
              polygon: [
                [0.28, 0.66],
                [0.72, 0.66],
                [0.8, 0.98],
                [0.2, 0.98],
              ],
            },
          ],
          lines: [{ id: 'door-line', name: 'Door Line', start: [0.33, 0.7], end: [0.67, 0.7] }],
        },
        [person(0.42, 0.9, 0.36), person(0.6, 0.82, 0.32)],
      ),
      camera(
        'najd-grill-malqa',
        'ngm-cashier',
        'Cashier counter',
        'كاونتر الكاشير',
        'counter',
        'online',
        'CAM 02',
        {
          zones: [
            {
              id: 'checkout-queue',
              name: 'Checkout Queue',
              polygon: [
                [0.18, 0.66],
                [0.6, 0.66],
                [0.66, 0.99],
                [0.12, 0.99],
              ],
            },
            {
              id: 'cashier-station',
              name: 'Cashier Station',
              polygon: [
                [0.22, 0.24],
                [0.42, 0.24],
                [0.42, 0.44],
                [0.22, 0.44],
              ],
            },
          ],
          lines: [],
        },
        [person(0.3, 0.42, 0.22), person(0.32, 0.92, 0.34), person(0.42, 0.88, 0.32)],
      ),
      camera(
        'najd-grill-malqa',
        'ngm-dining',
        'Family dining hall',
        'صالة العائلات',
        'dining',
        'online',
        'CAM 03',
        {
          zones: [
            {
              id: 'dining-floor',
              name: 'Dining Floor',
              polygon: [
                [0.03, 0.44],
                [0.97, 0.44],
                [0.99, 0.99],
                [0.01, 0.99],
              ],
            },
          ],
          lines: [],
        },
        [person(0.2, 0.55, 0.2), person(0.25, 0.56, 0.2), person(0.62, 0.84, 0.28)],
      ),
      camera(
        'najd-grill-malqa',
        'ngm-backdoor',
        'Kitchen back door',
        'الباب الخلفي للمطبخ',
        'corridor',
        'degraded',
        'CAM 04',
        {
          zones: [
            {
              id: 'back-door',
              name: 'Back Door',
              polygon: [
                [0.4, 0.64],
                [0.6, 0.64],
                [0.72, 0.94],
                [0.3, 0.94],
              ],
            },
          ],
          lines: [],
        },
        [],
      ),
    ],
    rules: [],
  };
  restaurant.rules = [
    {
      rule: rule({
        id: 'ngm-queue',
        name: 'Checkout queue too long',
        type: 'queue_length_over',
        camera_id: 'ngm-cashier',
        zone_id: 'checkout-queue',
        threshold: 5,
        min_duration_s: 120,
        cooldown_s: 600,
        schedule: { days: ALL_DAYS, start: '09:00:00', end: '23:00:00' },
        severity: 'warning',
      }),
      recipient_ids: ['rcp-ngm-manager'],
    },
    {
      rule: rule({
        id: 'ngm-cashier-empty',
        name: 'Cashier station unattended',
        type: 'zone_empty',
        camera_id: 'ngm-cashier',
        zone_id: 'cashier-station',
        min_duration_s: 300,
        schedule: { days: ALL_DAYS, start: '09:00:00', end: '23:30:00' },
        severity: 'warning',
      }),
      recipient_ids: ['rcp-ngm-manager', 'rcp-ngm-shift'],
    },
    {
      rule: rule({
        id: 'ngm-dining-full',
        name: 'Dining hall crowded',
        type: 'zone_occupancy_over',
        camera_id: 'ngm-dining',
        zone_id: 'dining-floor',
        threshold: 40,
        min_duration_s: 300,
        schedule: { days: ALL_DAYS, start: '12:00:00', end: '23:30:00' },
        severity: 'info',
      }),
      recipient_ids: ['rcp-ngm-shift'],
    },
    {
      rule: rule({
        id: 'ngm-backdoor-dwell',
        name: 'Loitering at back door',
        type: 'dwell_over',
        camera_id: 'ngm-backdoor',
        zone_id: 'back-door',
        min_duration_s: 180,
        severity: 'critical',
        verify: true,
      }),
      recipient_ids: ['rcp-ngm-manager', 'rcp-ngm-owner'],
    },
    {
      rule: rule({
        id: 'ngm-after-hours',
        name: 'Presence after closing',
        type: 'presence_after_hours',
        camera_id: 'ngm-dining',
        zone_id: 'dining-floor',
        threshold: 1,
        min_duration_s: 60,
        schedule: { days: ALL_DAYS, start: '01:30:00', end: '07:00:00' },
        severity: 'critical',
        verify: true,
      }),
      recipient_ids: ['rcp-ngm-owner', 'rcp-ngm-manager'],
    },
    {
      rule: rule({
        id: 'ngm-entrance-rush',
        name: 'Entrance rush',
        type: 'line_crossing',
        camera_id: 'ngm-entrance',
        line_id: 'door-line',
        threshold: 30,
        window_s: 600,
        direction: 'in',
        severity: 'info',
      }),
      recipient_ids: ['rcp-ngm-shift'],
    },
  ];

  const pharmacy: MockSite = {
    id: 'olaya-pharmacy',
    name: 'Olaya Family Pharmacy',
    name_ar: 'صيدلية العليا العائلية',
    industry: 'pharmacy',
    city: 'Riyadh',
    recipients: [
      {
        id: 'rcp-op-manager',
        name: 'Pharmacy Manager',
        name_ar: 'مدير الصيدلية',
        channel: 'whatsapp',
      },
      { id: 'rcp-op-owner', name: 'Owner', name_ar: 'المالك', channel: 'whatsapp' },
    ],
    cameras: [
      camera(
        'olaya-pharmacy',
        'op-counter',
        'Dispensing counter',
        'كاونتر الصرف',
        'counter',
        'online',
        'CAM 01',
        {
          zones: [
            {
              id: 'rx-queue',
              name: 'طابور الوصفات',
              polygon: [
                [0.38, 0.66],
                [0.86, 0.66],
                [0.92, 0.99],
                [0.34, 0.99],
              ],
            },
            {
              id: 'pharmacist-desk',
              name: 'مكتب الصيدلي',
              polygon: [
                [0.6, 0.22],
                [0.8, 0.22],
                [0.8, 0.44],
                [0.6, 0.44],
              ],
            },
          ],
          lines: [],
        },
        [person(0.7, 0.42, 0.22), person(0.55, 0.9, 0.34)],
      ),
      camera(
        'olaya-pharmacy',
        'op-entrance',
        'Entrance',
        'المدخل',
        'entrance',
        'online',
        'CAM 02',
        {
          zones: [],
          lines: [{ id: 'entry-line', name: 'خط الدخول', start: [0.3, 0.72], end: [0.7, 0.72] }],
        },
        [person(0.5, 0.88, 0.34)],
      ),
      camera(
        'olaya-pharmacy',
        'op-stock',
        'Stock room',
        'غرفة المخزون',
        'aisle',
        'offline',
        'CAM 03',
        {
          zones: [
            {
              id: 'stock-room',
              name: 'غرفة المخزون',
              polygon: [
                [0.25, 0.5],
                [0.75, 0.5],
                [0.85, 0.99],
                [0.15, 0.99],
              ],
            },
          ],
          lines: [],
        },
        [],
      ),
    ],
    rules: [],
  };
  pharmacy.rules = [
    {
      rule: rule({
        id: 'op-rx-queue',
        name: 'طابور الوصفات طويل',
        type: 'queue_length_over',
        camera_id: 'op-counter',
        zone_id: 'rx-queue',
        threshold: 4,
        min_duration_s: 90,
        schedule: { days: ALL_DAYS, start: '08:00:00', end: '23:59:00' },
        severity: 'warning',
      }),
      recipient_ids: ['rcp-op-manager'],
    },
    {
      rule: rule({
        id: 'op-desk-empty',
        name: 'مكتب الصيدلي بدون موظف',
        type: 'zone_empty',
        camera_id: 'op-counter',
        zone_id: 'pharmacist-desk',
        min_duration_s: 240,
        severity: 'critical',
      }),
      recipient_ids: ['rcp-op-manager', 'rcp-op-owner'],
    },
    {
      rule: rule({
        id: 'op-stock-after-hours',
        name: 'تواجد في المخزون بعد الدوام',
        type: 'presence_after_hours',
        camera_id: 'op-stock',
        zone_id: 'stock-room',
        threshold: 1,
        min_duration_s: 30,
        schedule: { days: SUN_THU, start: '23:00:00', end: '07:00:00' },
        severity: 'critical',
        verify: true,
      }),
      recipient_ids: ['rcp-op-owner'],
    },
    {
      rule: rule({
        id: 'op-entrance-count',
        name: 'زحمة عند المدخل',
        type: 'line_crossing',
        camera_id: 'op-entrance',
        line_id: 'entry-line',
        threshold: 20,
        window_s: 900,
        direction: 'in',
        severity: 'info',
      }),
      recipient_ids: ['rcp-op-manager'],
    },
  ];

  const warehouse: MockSite = {
    id: 'sulay-dc',
    name: 'Al Sulay Distribution Centre',
    name_ar: 'مركز توزيع السلي',
    industry: 'warehouse',
    city: 'Riyadh',
    recipients: [
      {
        id: 'rcp-sd-supervisor',
        name: 'Warehouse Supervisor',
        name_ar: 'مشرف المستودع',
        channel: 'whatsapp',
      },
      { id: 'rcp-sd-security', name: 'Security Desk', name_ar: 'مكتب الأمن', channel: 'telegram' },
      { id: 'rcp-sd-ops', name: 'Operations Manager', name_ar: 'مدير العمليات', channel: 'email' },
    ],
    cameras: [
      camera(
        'sulay-dc',
        'sd-dock',
        'Loading dock 2',
        'رصيف التحميل ٢',
        'dock',
        'online',
        'CAM 07',
        {
          zones: [
            {
              id: 'dock-apron',
              name: 'Dock Apron',
              polygon: [
                [0.38, 0.62],
                [0.68, 0.62],
                [0.72, 0.98],
                [0.34, 0.98],
              ],
            },
            {
              id: 'pedestrian-walkway',
              name: 'Pedestrian Walkway',
              polygon: [
                [0.0, 0.84],
                [1.0, 0.84],
                [1.0, 0.99],
                [0.0, 0.99],
              ],
            },
          ],
          lines: [],
        },
        [{ kind: 'vehicle', box: [0.4, 0.5, 0.66, 0.84] }, person(0.8, 0.86, 0.3)],
      ),
      camera(
        'sulay-dc',
        'sd-aisle',
        'Aisle C racking',
        'ممر الرفوف C',
        'aisle',
        'online',
        'CAM 08',
        {
          zones: [
            {
              id: 'aisle-c',
              name: 'Aisle C',
              polygon: [
                [0.42, 0.44],
                [0.58, 0.44],
                [0.78, 0.99],
                [0.22, 0.99],
              ],
            },
          ],
          lines: [],
        },
        [person(0.46, 0.7, 0.24), person(0.58, 0.92, 0.34)],
      ),
      camera(
        'sulay-dc',
        'sd-cash',
        'Cash office corridor',
        'ممر مكتب النقد',
        'corridor',
        'online',
        'CAM 09',
        {
          zones: [
            {
              id: 'cash-office-door',
              name: 'Cash Office Door',
              polygon: [
                [0.38, 0.64],
                [0.62, 0.64],
                [0.74, 0.96],
                [0.28, 0.96],
              ],
            },
          ],
          lines: [],
        },
        [],
      ),
      camera(
        'sulay-dc',
        'sd-gate',
        'Staff gate',
        'بوابة الموظفين',
        'entrance',
        'online',
        'CAM 10',
        {
          zones: [
            {
              id: 'gate-area',
              name: 'Gate Area',
              polygon: [
                [0.25, 0.66],
                [0.75, 0.66],
                [0.82, 0.98],
                [0.18, 0.98],
              ],
            },
          ],
          lines: [{ id: 'gate-line', name: 'Gate Line', start: [0.68, 0.74], end: [0.32, 0.74] }],
        },
        [person(0.36, 0.92, 0.36)],
      ),
    ],
    rules: [],
  };
  warehouse.rules = [
    {
      rule: rule({
        id: 'sd-truck-dwell',
        name: 'Truck waiting at dock 2',
        type: 'dwell_over',
        camera_id: 'sd-dock',
        zone_id: 'dock-apron',
        classes: ['car', 'truck', 'bus'],
        min_duration_s: 1800,
        cooldown_s: 1800,
        severity: 'warning',
      }),
      recipient_ids: ['rcp-sd-supervisor'],
    },
    {
      rule: rule({
        id: 'sd-aisle-crowd',
        name: 'Too many people in Aisle C',
        type: 'zone_occupancy_over',
        camera_id: 'sd-aisle',
        zone_id: 'aisle-c',
        threshold: 6,
        min_duration_s: 60,
        severity: 'warning',
      }),
      recipient_ids: ['rcp-sd-supervisor'],
    },
    {
      rule: rule({
        id: 'sd-cash-loiter',
        name: 'Loitering at cash office',
        type: 'dwell_over',
        camera_id: 'sd-cash',
        zone_id: 'cash-office-door',
        min_duration_s: 120,
        severity: 'critical',
        verify: true,
      }),
      recipient_ids: ['rcp-sd-security', 'rcp-sd-ops'],
    },
    {
      rule: rule({
        id: 'sd-after-hours',
        name: 'After-hours presence on dock',
        type: 'presence_after_hours',
        camera_id: 'sd-dock',
        zone_id: 'pedestrian-walkway',
        threshold: 1,
        min_duration_s: 60,
        schedule: { days: [1, 2, 3, 4, 6, 7], start: '22:00:00', end: '05:00:00' },
        severity: 'critical',
        verify: true,
      }),
      recipient_ids: ['rcp-sd-security'],
    },
    {
      rule: rule({
        id: 'sd-gate-exit',
        name: 'Shift change at staff gate',
        type: 'line_crossing',
        camera_id: 'sd-gate',
        line_id: 'gate-line',
        threshold: 25,
        window_s: 600,
        direction: 'out',
        severity: 'info',
      }),
      recipient_ids: ['rcp-sd-supervisor'],
    },
    {
      rule: rule({
        id: 'sd-gate-empty',
        name: 'Gate guard post unattended',
        type: 'zone_empty',
        camera_id: 'sd-gate',
        zone_id: 'gate-area',
        min_duration_s: 600,
        schedule: { days: ALL_DAYS, start: '06:00:00', end: '22:00:00' },
        severity: 'warning',
      }),
      recipient_ids: ['rcp-sd-security'],
    },
  ];

  return [restaurant, pharmacy, warehouse];
}

/** How many events of each rule type the seed generates (about 60 in total). */
const EVENTS_PER_TYPE: Record<RuleType, number> = {
  queue_length_over: 14,
  zone_empty: 10,
  zone_occupancy_over: 8,
  dwell_over: 10,
  line_crossing: 8,
  presence_after_hours: 10,
};

function inSchedule(rule: Rule, minutes: number): boolean {
  const s = rule.schedule;
  if (!s) return true;
  const a = timeToMinutes(s.start);
  const b = timeToMinutes(s.end);
  return a <= b ? minutes >= a && minutes <= b : minutes >= a || minutes <= b;
}

function sampleInPolygon(rng: () => number, polygon: Point[]): Point {
  const xs = polygon.map((p) => p[0]);
  const ys = polygon.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [
    Math.min(...xs),
    Math.max(...xs),
    Math.min(...ys),
    Math.max(...ys),
  ];
  for (let i = 0; i < 50; i++) {
    const p: Point = [minX + rng() * (maxX - minX), minY + rng() * (maxY - minY)];
    if (pointInPolygon(p, polygon)) return p;
  }
  return [(minX + maxX) / 2, (minY + maxY) / 2];
}

export function objectsFor(
  rng: () => number,
  rule: Rule,
  cam: MockCamera,
  count: number,
): SceneObject[] {
  const vehicle = !rule.classes.includes('person');
  const zone = cam.config.zones.find((z) => z.id === rule.zone_id);
  const line = cam.config.lines.find((l) => l.id === rule.line_id);
  const area: Point[] =
    (zone?.polygon as Point[] | undefined) ??
    (line
      ? [
          [Math.min(line.start[0], line.end[0]), line.start[1] + 0.02],
          [Math.max(line.start[0], line.end[0]), line.start[1] + 0.02],
          [Math.max(line.start[0], line.end[0]), 0.98],
          [Math.min(line.start[0], line.end[0]), 0.98],
        ]
      : [
          [0.2, 0.6],
          [0.8, 0.6],
          [0.8, 0.98],
          [0.2, 0.98],
        ]);
  const out: SceneObject[] = [];
  const placed: Point[] = [];
  for (let i = 0; i < count; i++) {
    // Keep people apart a little so the snapshot reads like a real queue, not a pile.
    let [cx, bottom] = sampleInPolygon(rng, area);
    for (
      let tries = 0;
      tries < 12 && placed.some(([x, y]) => Math.abs(x - cx) < 0.06 && Math.abs(y - bottom) < 0.08);
      tries++
    ) {
      [cx, bottom] = sampleInPolygon(rng, area);
    }
    placed.push([cx, bottom]);
    if (vehicle) {
      out.push({
        kind: 'vehicle',
        box: [Math.max(0, cx - 0.14), Math.max(0, bottom - 0.32), Math.min(1, cx + 0.14), bottom],
      });
    } else {
      const h = 0.14 + bottom * 0.24;
      const w = h * 0.36;
      out.push({
        kind: 'person',
        box: [cx - w / 2, Math.max(0, bottom - h), cx + w / 2, bottom] as NormBox,
      });
    }
  }
  return out;
}

function fmtDuration(seconds: number): string {
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, '0')}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
}

/** Edge-style English message, as vision_edge's rule evaluators write it. */
export function edgeMessage(rule: Rule, cam: MockCamera, value: number, held: number): string {
  const zone = cam.config.zones.find((z) => z.id === rule.zone_id)?.name ?? '';
  const line = cam.config.lines.find((l) => l.id === rule.line_id)?.name ?? '';
  const noun = rule.classes.includes('person') ? (value === 1 ? 'person' : 'people') : 'vehicles';
  switch (rule.type) {
    case 'queue_length_over':
      return `Queue of ${value} in '${zone}' for ${fmtDuration(held)} (limit ${rule.threshold}), longest wait ${fmtDuration(held + 140)}`;
    case 'zone_occupancy_over':
      return `${value} ${noun} in '${zone}' for ${fmtDuration(held)} (limit ${rule.threshold})`;
    case 'zone_empty':
      return `'${zone}' unattended for ${fmtDuration(value)}`;
    case 'dwell_over':
      return `${rule.classes.includes('person') ? 'Person' : 'Truck'} in '${zone}' for ${fmtDuration(value)} (limit ${fmtDuration(rule.min_duration_s)})`;
    case 'line_crossing':
      return `${value} crossings of '${line}' (${rule.direction}) in ${fmtDuration(held)}`;
    case 'presence_after_hours':
      return `${value} ${noun} in '${zone}' outside opening hours (${fmtDuration(held)})`;
  }
}

const AI_REASONS = {
  confirmed: [
    'One person is standing beside the door and not passing through.',
    'A person is clearly visible inside the zone; the area should be empty at this hour.',
    'The same person has stayed near the office door for the whole clip.',
  ],
  rejected: [
    'The shape in the zone is a reflection on the glass, not a person.',
    'A cleaner with a trolley is moving through; this matches the scheduled cleaning round.',
  ],
};

export interface SeedEvent extends EventView {
  /** Objects drawn in the snapshot (also kept in attributes.boxes). */
  objects: SceneObject[];
}

/** ~60 events across the six rule types over the 7 days up to `now`. */
export function buildEvents(sites: MockSite[], now: Date, seed = 20261102): SeedEvent[] {
  const rng = mulberry32(seed);
  const rulesByType = new Map<RuleType, { site: MockSite; rr: RuleWithRecipients }[]>();
  for (const site of sites) {
    for (const rr of site.rules) {
      const list = rulesByType.get(rr.rule.type) ?? [];
      list.push({ site, rr });
      rulesByType.set(rr.rule.type, list);
    }
  }
  const nowLocal = localParts(now, MOCK_TZ);
  const events: SeedEvent[] = [];
  let n = 0;
  for (const [type, count] of Object.entries(EVENTS_PER_TYPE) as [RuleType, number][]) {
    const candidates = rulesByType.get(type) ?? [];
    for (let i = 0; i < count; i++) {
      const { site, rr } = candidates[i % candidates.length]!;
      const r = rr.rule;
      const cam = site.cameras.find((c) => c.config.id === r.camera_id)!;
      // Pick a day (today weighted more) and a time inside the rule's schedule, before now.
      let when: Date | null = null;
      for (let attempt = 0; attempt < 40 && !when; attempt++) {
        const dayBack = rng() < 0.32 ? 0 : 1 + Math.floor(rng() * 6);
        const minutes = Math.floor(rng() * 1440);
        if (!inSchedule(r, minutes)) continue;
        const base = new Date(Date.UTC(nowLocal.year, nowLocal.month - 1, nowLocal.day - dayBack));
        const t = zonedToUtc(
          base.getUTCFullYear(),
          base.getUTCMonth() + 1,
          base.getUTCDate(),
          Math.floor(minutes / 60),
          minutes % 60,
          Math.floor(rng() * 60),
          MOCK_TZ,
        );
        if (t.getTime() < now.getTime() - 3 * 60000) when = t;
      }
      if (!when) when = new Date(now.getTime() - (2 + rng() * 120) * 3600000);

      let value: number;
      let held: number;
      let objectCount: number;
      switch (type) {
        case 'queue_length_over':
        case 'zone_occupancy_over':
          value = r.threshold + 1 + Math.floor(rng() * 4);
          held = r.min_duration_s + Math.floor(rng() * 90);
          objectCount = Math.min(value, 9);
          break;
        case 'zone_empty':
          value = r.min_duration_s + Math.floor(rng() * 400);
          held = value;
          objectCount = 0;
          break;
        case 'dwell_over':
          value = r.min_duration_s + Math.floor(rng() * r.min_duration_s * 0.8);
          held = value;
          objectCount = 1;
          break;
        case 'line_crossing':
          value = r.threshold + Math.floor(rng() * 12);
          held = Math.floor(r.window_s * (0.5 + rng() * 0.5));
          objectCount = 3;
          break;
        case 'presence_after_hours':
          value = 1 + Math.floor(rng() * 2);
          held = r.min_duration_s + Math.floor(rng() * 120);
          objectCount = value;
          break;
      }
      const triggered = when;
      const started = new Date(triggered.getTime() - held * 1000);
      const ageMin = (now.getTime() - triggered.getTime()) / 60000;
      const cleared =
        ageMin > 25 || rng() < 0.4
          ? new Date(triggered.getTime() + (60 + rng() * 600) * 1000)
          : null;
      const objects = objectsFor(rng, r, cam, objectCount);
      const id = `evt-${String(++n).padStart(3, '0')}-${r.id}`;

      const attributes: Record<string, unknown> = {
        boxes: objects.map((o) => o.box.map((v) => Math.round(v * 10000) / 10000)),
      };
      if (type === 'queue_length_over') attributes.longest_wait_s = held + 140;
      if (type === 'line_crossing') attributes.direction = r.direction;
      if (r.verify) {
        const rejected = rng() < 0.25;
        const pool = rejected ? AI_REASONS.rejected : AI_REASONS.confirmed;
        attributes.ai_check = {
          verdict: rejected ? 'rejected' : 'confirmed',
          reason: pool[Math.floor(rng() * pool.length)],
        };
      }

      // Feedback: most older events were reviewed; a few were false alarms.
      let feedback: EventView['feedback'] = null;
      if (ageMin > 90 && rng() < 0.7) {
        const falseAlarm = rng() < (r.verify ? 0.12 : 0.18);
        feedback = {
          verdict: falseAlarm ? 'false_alarm' : 'correct',
          note: falseAlarm
            ? rng() < 0.5
              ? 'Staff member on break, not a customer.'
              : 'Cleaner moving furniture.'
            : '',
          by: site.recipients[0]!.name,
          at: new Date(triggered.getTime() + (5 + rng() * 120) * 60000).toISOString(),
        };
      }
      events.push({
        schema_version: '1.0',
        id,
        site_id: site.id,
        camera_id: cam.config.id,
        rule_id: r.id,
        rule_type: type,
        severity: r.severity as Severity,
        state: cleared ? 'cleared' : 'triggered',
        condition_started_at: started.toISOString(),
        triggered_at: triggered.toISOString(),
        cleared_at: cleared ? cleared.toISOString() : null,
        value,
        message: edgeMessage(r, cam, value, held),
        attributes,
        snapshot_key: `${site.id}/${cam.config.id}/${id}.jpg`,
        clip_key: `${site.id}/${cam.config.id}/${id}.mp4`,
        needs_verification: r.verify,
        created_at: new Date(triggered.getTime() + 1500).toISOString(),
        snapshot_url: null,
        clip_url: null,
        feedback,
        objects,
      });
    }
  }
  events.sort((a, b) => b.triggered_at.localeCompare(a.triggered_at));
  return events;
}

/** Expected visitors per local hour for a site, used for the footfall chart. */
export function footfallShape(industry: Industry, hour: number): number {
  const bump = (h: number, centre: number, width: number, height: number) =>
    height * Math.exp(-((h - centre) ** 2) / (2 * width * width));
  switch (industry) {
    case 'restaurant':
      return hour < 11 && hour > 1
        ? 0
        : bump(hour, 14, 1.4, 55) + bump(hour, 21, 1.8, 95) + bump(hour, 0.5, 0.8, 30);
    case 'pharmacy':
      return hour < 8 ? 3 : bump(hour, 12, 2.5, 22) + bump(hour, 20, 2.2, 38);
    case 'warehouse':
      return (
        bump(hour, 6, 0.5, 70) +
        bump(hour, 14, 0.5, 60) +
        bump(hour, 22, 0.5, 45) +
        (hour >= 6 && hour <= 22 ? 6 : 1)
      );
    default:
      return bump(hour, 13, 3, 30);
  }
}
