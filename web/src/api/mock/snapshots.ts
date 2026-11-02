/**
 * Placeholder camera images for the mock API, drawn as SVG (no photos). Each scene is a simple
 * flat illustration of a CCTV view with an on-screen timestamp, so the dashboard looks and
 * behaves like it will with real snapshots. People are faceless silhouettes.
 */
import type { NormBox } from '../models';

export type Scene = 'entrance' | 'counter' | 'dining' | 'corridor' | 'dock' | 'aisle';

export interface SceneObject {
  box: NormBox;
  kind: 'person' | 'vehicle';
}

export interface SnapshotOptions {
  scene: Scene;
  label: string;
  /** Text for the on-screen clock, already formatted in the site's local time. */
  clock: string;
  night?: boolean;
  objects?: SceneObject[];
  seed?: string;
}

const W = 1280;
const H = 720;

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

interface Palette {
  wall: string;
  wall2: string;
  floor: string;
  floor2: string;
  wood: string;
  metal: string;
  dark: string;
  accent: string;
  glass: string;
  people: string[];
}

const DAY: Palette = {
  wall: '#d9d6cf',
  wall2: '#c7c3ba',
  floor: '#a9a397',
  floor2: '#9a9488',
  wood: '#8a6e52',
  metal: '#7d8790',
  dark: '#3b4148',
  accent: '#c9a34a',
  glass: '#b9cdd4',
  people: ['#efede6', '#2b2b30', '#1f6f68', '#e9e6dc', '#47505a', '#8c5a3c', '#f2f0ea', '#363a40'],
};

const NIGHT: Palette = {
  wall: '#5b5f60',
  wall2: '#4d5152',
  floor: '#3e4243',
  floor2: '#363a3b',
  wood: '#4a4c4d',
  metal: '#6a6e70',
  dark: '#232627',
  accent: '#7c8082',
  glass: '#6f7678',
  people: ['#b9bdbe', '#8f9394', '#a6aaab', '#c8cccd'],
};

const rect = (x: number, y: number, w: number, h: number, fill: string, extra = '') =>
  `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}" ${extra}/>`;
const poly = (pts: number[][], fill: string, extra = '') =>
  `<polygon points="${pts.map((p) => p.join(',')).join(' ')}" fill="${fill}" ${extra}/>`;

function sceneBody(scene: Scene, c: Palette, seed: number): string {
  const parts: string[] = [];
  switch (scene) {
    case 'entrance': {
      parts.push(rect(0, 0, W, 470, c.wall));
      parts.push(
        poly(
          [
            [0, 470],
            [W, 470],
            [W, H],
            [0, H],
          ],
          c.floor,
        ),
      );
      parts.push(rect(430, 110, 420, 360, c.dark));
      parts.push(rect(445, 125, 190, 345, c.glass, 'opacity="0.85"'));
      parts.push(rect(645, 125, 190, 345, c.glass, 'opacity="0.85"'));
      parts.push(rect(612, 270, 8, 60, c.metal));
      parts.push(rect(660, 270, 8, 60, c.metal));
      parts.push(
        poly(
          [
            [470, 480],
            [810, 480],
            [880, 560],
            [400, 560],
          ],
          c.dark,
          'opacity="0.55"',
        ),
      );
      parts.push(rect(140, 330, 90, 140, c.wood));
      parts.push(`<circle cx="185" cy="300" r="60" fill="#5d7a5a"/>`);
      parts.push(rect(1050, 330, 90, 140, c.wood));
      parts.push(`<circle cx="1095" cy="300" r="60" fill="#5d7a5a"/>`);
      parts.push(rect(520, 60, 240, 36, c.accent, 'rx="4"'));
      break;
    }
    case 'counter': {
      parts.push(rect(0, 0, W, 420, c.wall));
      for (let i = 0; i < 3; i++) {
        const x = 250 + i * 270;
        parts.push(rect(x, 60, 240, 130, c.dark, 'rx="6"'));
        for (let j = 0; j < 4; j++)
          parts.push(
            rect(x + 20, 85 + j * 25, 120 + ((seed >> (i + j)) % 80), 8, c.accent, 'opacity="0.8"'),
          );
      }
      parts.push(
        poly(
          [
            [0, 420],
            [W, 420],
            [W, H],
            [0, H],
          ],
          c.floor,
        ),
      );
      parts.push(rect(120, 300, 1040, 40, c.wood));
      parts.push(rect(120, 340, 1040, 130, c.wall2));
      parts.push(rect(330, 255, 90, 45, c.dark, 'rx="4"'));
      parts.push(rect(820, 255, 90, 45, c.dark, 'rx="4"'));
      for (let i = 0; i < 6; i++)
        parts.push(rect(150 + i * 170, 350, 120, 110, c.wall, 'opacity="0.5"'));
      break;
    }
    case 'dining': {
      parts.push(rect(0, 0, W, 300, c.wall));
      parts.push(rect(0, 120, W, 12, c.wood));
      parts.push(
        poly(
          [
            [0, 300],
            [W, 300],
            [W, H],
            [0, H],
          ],
          c.floor,
        ),
      );
      for (let r = 0; r < 2; r++) {
        for (let i = 0; i < 4; i++) {
          const cx = 220 + i * 280 + (r ? 60 : 0);
          const cy = 380 + r * 190;
          const rx = 70 + r * 20;
          parts.push(
            `<ellipse cx="${cx}" cy="${cy + 18}" rx="${rx}" ry="${22 + r * 6}" fill="${c.dark}" opacity="0.25"/>`,
          );
          parts.push(
            `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${22 + r * 6}" fill="${c.wood}"/>`,
          );
        }
      }
      parts.push(rect(40, 160, 160, 140, c.wall2));
      parts.push(rect(1080, 160, 160, 140, c.wall2));
      break;
    }
    case 'corridor': {
      parts.push(rect(0, 0, W, H, c.wall2));
      parts.push(
        poly(
          [
            [0, 0],
            [470, 200],
            [470, 470],
            [0, H],
          ],
          c.wall,
        ),
      );
      parts.push(
        poly(
          [
            [W, 0],
            [810, 200],
            [810, 470],
            [W, H],
          ],
          c.wall,
        ),
      );
      parts.push(
        poly(
          [
            [470, 470],
            [810, 470],
            [W, H],
            [0, H],
          ],
          c.floor,
        ),
      );
      parts.push(rect(470, 200, 340, 270, c.wall2));
      parts.push(rect(570, 250, 140, 220, c.metal));
      parts.push(rect(690, 350, 10, 30, c.dark));
      parts.push(rect(600, 215, 80, 26, '#2f8a4e', 'rx="3"'));
      parts.push(
        poly(
          [
            [880, 180],
            [960, 140],
            [960, 560],
            [880, 520],
          ],
          c.dark,
          'opacity="0.6"',
        ),
      );
      break;
    }
    case 'dock': {
      parts.push(rect(0, 0, W, 440, c.wall));
      for (let i = 0; i < 3; i++) {
        const x = 90 + i * 400;
        parts.push(rect(x, 90, 300, 350, c.metal));
        for (let j = 0; j < 14; j++)
          parts.push(rect(x, 95 + j * 25, 300, 3, c.dark, 'opacity="0.35"'));
        parts.push(rect(x - 12, 80, 324, 14, '#d1a12c'));
      }
      parts.push(
        poly(
          [
            [0, 440],
            [W, 440],
            [W, H],
            [0, H],
          ],
          c.floor,
        ),
      );
      parts.push(rect(0, 600, W, 8, '#d1a12c', 'opacity="0.8"'));
      for (let i = 0; i < 4; i++)
        parts.push(rect(70 + i * 360, 455, 6, 265, '#d1a12c', 'opacity="0.8"'));
      parts.push(rect(940, 520, 130, 60, c.wood));
      parts.push(rect(950, 470, 110, 50, '#b88e5e'));
      break;
    }
    case 'aisle': {
      parts.push(rect(0, 0, W, H, c.wall));
      parts.push(
        poly(
          [
            [540, 300],
            [740, 300],
            [1000, H],
            [280, H],
          ],
          c.floor,
        ),
      );
      parts.push(
        poly(
          [
            [0, 0],
            [540, 160],
            [540, 300],
            [280, H],
            [0, H],
          ],
          c.wall2,
        ),
      );
      parts.push(
        poly(
          [
            [W, 0],
            [740, 160],
            [740, 300],
            [1000, H],
            [W, H],
          ],
          c.wall2,
        ),
      );
      for (let j = 0; j < 4; j++) {
        const t = j / 4;
        parts.push(
          poly(
            [
              [0, 120 + j * 160],
              [540, 175 + j * 35],
              [540, 183 + j * 35],
              [0, 136 + j * 160],
            ],
            '#d2752c',
          ),
        );
        parts.push(
          poly(
            [
              [W, 120 + j * 160],
              [740, 175 + j * 35],
              [740, 183 + j * 35],
              [W, 136 + j * 160],
            ],
            '#d2752c',
          ),
        );
        for (let k = 0; k < 5; k++) {
          const x = 30 + k * 95 + t * 10;
          parts.push(rect(x, 60 + j * 150 + k * 6, 70 - k * 8, 50 - k * 4, '#b88e5e'));
          parts.push(
            rect(W - x - 70 + k * 8, 60 + j * 150 + k * 6, 70 - k * 8, 50 - k * 4, '#b88e5e'),
          );
        }
      }
      parts.push(
        poly(
          [
            [600, 300],
            [610, 300],
            [500, H],
            [480, H],
          ],
          '#e3c341',
        ),
      );
      parts.push(
        poly(
          [
            [670, 300],
            [680, 300],
            [800, H],
            [780, H],
          ],
          '#e3c341',
        ),
      );
      break;
    }
  }
  return parts.join('');
}

function personSvg(o: SceneObject, color: string, shadow: string): string {
  const [x1, y1, x2, y2] = o.box;
  const x = x1 * W;
  const y = y1 * H;
  const w = (x2 - x1) * W;
  const h = (y2 - y1) * H;
  if (o.kind === 'vehicle') {
    return (
      `<g><rect x="${x}" y="${y + h * 0.15}" width="${w}" height="${h * 0.7}" rx="${w * 0.04}" fill="${color}"/>` +
      `<rect x="${x + w * 0.65}" y="${y}" width="${w * 0.33}" height="${h * 0.5}" rx="${w * 0.03}" fill="${color}"/>` +
      `<rect x="${x + w * 0.7}" y="${y + h * 0.06}" width="${w * 0.22}" height="${h * 0.2}" fill="#6f7f88"/>` +
      `<circle cx="${x + w * 0.2}" cy="${y + h * 0.88}" r="${h * 0.12}" fill="${shadow}"/>` +
      `<circle cx="${x + w * 0.8}" cy="${y + h * 0.88}" r="${h * 0.12}" fill="${shadow}"/></g>`
    );
  }
  const r = Math.min(w * 0.32, h * 0.1);
  const bodyTop = y + r * 2.1;
  return (
    `<g><ellipse cx="${x + w / 2}" cy="${y + h}" rx="${w * 0.55}" ry="${h * 0.03}" fill="${shadow}" opacity="0.35"/>` +
    `<rect x="${x + w * 0.12}" y="${bodyTop}" width="${w * 0.76}" height="${y + h - bodyTop}" rx="${w * 0.3}" fill="${color}"/>` +
    `<circle cx="${x + w / 2}" cy="${y + r}" r="${r}" fill="${color}"/></g>`
  );
}

function escapeXml(s: string): string {
  return s.replace(/[<>&'"]/g, (ch) => `&#${ch.charCodeAt(0)};`);
}

function osd(label: string, clock: string): string {
  const style =
    'font-family="DejaVu Sans Mono, Menlo, Consolas, monospace" font-size="26" fill="#ffffff" stroke="#000" stroke-width="0.6" paint-order="stroke"';
  return (
    `<text x="24" y="44" ${style}>${escapeXml(clock)}</text>` +
    `<text x="${W - 24}" y="${H - 24}" text-anchor="end" ${style}>${escapeXml(label)}</text>`
  );
}

function svgDocument(inner: string, night: boolean): string {
  const tint = night ? '<rect width="100%" height="100%" fill="#0b1a12" opacity="0.18"/>' : '';
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">${inner}${tint}</svg>`;
}

function toDataUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

export function snapshotSvg(opts: SnapshotOptions): string {
  const palette = opts.night ? NIGHT : DAY;
  const seed = hash(opts.seed ?? opts.label);
  const objects = [...(opts.objects ?? [])].sort((a, b) => a.box[3] - b.box[3]);
  const people = objects
    .map((o, i) =>
      personSvg(
        o,
        o.kind === 'vehicle' ? '#e7e7e2' : palette.people[(seed + i) % palette.people.length]!,
        palette.dark,
      ),
    )
    .join('');
  return svgDocument(
    sceneBody(opts.scene, palette, seed) + people + osd(opts.label, opts.clock),
    !!opts.night,
  );
}

export function snapshotDataUrl(opts: SnapshotOptions): string {
  return toDataUrl(snapshotSvg(opts));
}

/**
 * Stand-in for an event clip: the same scene with people drifting back and forth for 6 s.
 * The real API returns an MP4 URL; the clip player shows SVG clips as an image.
 */
export function clipDataUrl(opts: SnapshotOptions): string {
  const palette = opts.night ? NIGHT : DAY;
  const seed = hash(opts.seed ?? opts.label);
  const objects = [...(opts.objects ?? [])].sort((a, b) => a.box[3] - b.box[3]);
  const people = objects
    .map((o, i) => {
      const dx = (((seed >> i) % 7) - 3) * 12;
      const dy = (((seed >> (i + 3)) % 3) - 1) * 6;
      const g = personSvg(
        o,
        o.kind === 'vehicle' ? '#e7e7e2' : palette.people[(seed + i) % palette.people.length]!,
        palette.dark,
      );
      return `<g><animateTransform attributeName="transform" type="translate" values="0 0;${dx} ${dy};0 0" dur="6s" repeatCount="indefinite"/>${g}</g>`;
    })
    .join('');
  const progress =
    `<rect x="0" y="${H - 6}" width="0" height="6" fill="#ef4444">` +
    `<animate attributeName="width" from="0" to="${W}" dur="6s" repeatCount="indefinite"/></rect>` +
    `<circle cx="${W - 40}" cy="40" r="10" fill="#ef4444"><animate attributeName="opacity" values="1;0.2;1" dur="1s" repeatCount="indefinite"/></circle>`;
  return toDataUrl(
    svgDocument(
      sceneBody(opts.scene, palette, seed) + people + osd(opts.label, opts.clock) + progress,
      !!opts.night,
    ),
  );
}
