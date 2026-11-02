/**
 * Coordinate conversion for the zone and line editor. Configs store points normalised to 0..1
 * (x to the right, y downwards) so a zone drawn on one snapshot survives a change of stream
 * resolution; the editor works in stage pixels and converts at the edges.
 */
export type Point = [number, number];

export interface Size {
  width: number;
  height: number;
}

/** Saved coordinates keep 4 decimals: 0.1 px on a 1080p frame, and stable diffs. */
export const PRECISION = 4;

export function clamp01(v: number): number {
  if (Number.isNaN(v)) return 0;
  return Math.min(1, Math.max(0, v));
}

export function roundTo(v: number, digits = PRECISION): number {
  const f = 10 ** digits;
  return Math.round(v * f) / f;
}

/** Normalised (0..1) point to stage pixels. */
export function toPixels(p: Point, size: Size): Point {
  return [p[0] * size.width, p[1] * size.height];
}

/** Stage pixels to a normalised point, clamped to the frame and rounded for storage. */
export function toNormalised(p: Point, size: Size): Point {
  if (size.width <= 0 || size.height <= 0) throw new Error('stage size must be positive');
  return [roundTo(clamp01(p[0] / size.width)), roundTo(clamp01(p[1] / size.height))];
}

export function polygonToPixels(polygon: Point[], size: Size): Point[] {
  return polygon.map((p) => toPixels(p, size));
}

export function polygonToNormalised(polygon: Point[], size: Size): Point[] {
  return polygon.map((p) => toNormalised(p, size));
}

/** Konva wants a flat [x0, y0, x1, y1, ...] list. */
export function flatten(points: Point[]): number[] {
  return points.flatMap(([x, y]) => [x, y]);
}

/**
 * Moves a normalised polygon by (dx, dy), limiting the move so that every vertex stays inside
 * the frame (the shape stops at the border instead of being squashed against it).
 */
export function translateWithin(points: Point[], dx: number, dy: number): Point[] {
  if (points.length === 0) return points;
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const cdx = Math.min(Math.max(dx, -minX), 1 - maxX);
  const cdy = Math.min(Math.max(dy, -minY), 1 - maxY);
  return points.map(([x, y]) => [roundTo(x + cdx), roundTo(y + cdy)]);
}

export function centroid(points: Point[]): Point {
  if (points.length === 0) return [0, 0];
  const sx = points.reduce((s, p) => s + p[0], 0);
  const sy = points.reduce((s, p) => s + p[1], 0);
  return [sx / points.length, sy / points.length];
}

export function distance(a: Point, b: Point): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

/** Ray casting point-in-polygon test (any consistent coordinate space). */
export function pointInPolygon(p: Point, polygon: Point[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i]!;
    const [xj, yj] = polygon[j]!;
    const intersects = yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

/** A polygon is usable when it has 3+ distinct vertices and a non-zero area. */
export function isValidPolygon(points: Point[]): boolean {
  if (points.length < 3) return false;
  let area2 = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i]!;
    const [x2, y2] = points[(i + 1) % points.length]!;
    area2 += x1 * y2 - x2 * y1;
  }
  return Math.abs(area2) > 1e-6;
}

/**
 * Unit vector pointing to the "in" side of a counting line. The shared schema defines "in" as
 * crossing from the left to the right of start -> end in image coordinates (y down), and the
 * right-hand side of direction (dx, dy) is (-dy, dx).
 */
export function inwardNormal(start: Point, end: Point): Point {
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  const len = Math.hypot(dx, dy) || 1;
  return [-dy / len, dx / len];
}

/** Fits a frame of the given aspect ratio into the available width (and optional max height). */
export function fitStage(aspect: number, maxWidth: number, maxHeight = Infinity): Size {
  let width = Math.max(0, maxWidth);
  let height = width / aspect;
  if (height > maxHeight) {
    height = maxHeight;
    width = height * aspect;
  }
  return { width: Math.round(width), height: Math.round(height) };
}
