import { describe, expect, it } from 'vitest';
import {
  clamp01,
  fitStage,
  inwardNormal,
  isValidPolygon,
  pointInPolygon,
  polygonToNormalised,
  polygonToPixels,
  toNormalised,
  toPixels,
  translateWithin,
  type Point,
} from './geometry';

const HD = { width: 1280, height: 720 };

describe('pixels <-> normalised', () => {
  it('converts normalised points to stage pixels', () => {
    expect(toPixels([0.5, 0.5], HD)).toEqual([640, 360]);
    expect(toPixels([0, 1], HD)).toEqual([0, 720]);
    expect(toPixels([0.25, 0.1], { width: 400, height: 225 })).toEqual([100, 22.5]);
  });

  it('converts stage pixels to normalised points rounded to 4 decimals', () => {
    expect(toNormalised([640, 360], HD)).toEqual([0.5, 0.5]);
    expect(toNormalised([100, 100], { width: 300, height: 300 })).toEqual([0.3333, 0.3333]);
  });

  it('clamps points dragged outside the frame to 0..1', () => {
    expect(toNormalised([-20, 800], HD)).toEqual([0, 1]);
    expect(toNormalised([1300, -1], HD)).toEqual([1, 0]);
    expect(clamp01(Number.NaN)).toBe(0);
  });

  it('round-trips a polygon through any stage size within the stored precision', () => {
    const poly: Point[] = [
      [0.18, 0.66],
      [0.6, 0.66],
      [0.66, 0.99],
      [0.12, 0.99],
    ];
    for (const size of [HD, { width: 390, height: 219 }, { width: 1920, height: 1080 }]) {
      const back = polygonToNormalised(polygonToPixels(poly, size), size);
      back.forEach(([x, y], i) => {
        expect(x).toBeCloseTo(poly[i]![0], 4);
        expect(y).toBeCloseTo(poly[i]![1], 4);
      });
    }
  });

  it('is independent of the stage size: the same zone drawn at two sizes saves the same', () => {
    const small = toNormalised([195, 109.5], { width: 390, height: 219 });
    const large = toNormalised([640, 360], HD);
    expect(small).toEqual(large);
  });

  it('rejects an empty stage', () => {
    expect(() => toNormalised([1, 1], { width: 0, height: 10 })).toThrow();
  });
});

describe('editing helpers', () => {
  it('moves a polygon but stops it at the frame border', () => {
    const square: Point[] = [
      [0.8, 0.1],
      [0.9, 0.1],
      [0.9, 0.2],
      [0.8, 0.2],
    ];
    expect(translateWithin(square, 0.05, 0.05)).toEqual([
      [0.85, 0.15],
      [0.95, 0.15],
      [0.95, 0.25],
      [0.85, 0.25],
    ]);
    // Asked to move 0.5 right and 0.5 up: limited to 0.1 right and 0.1 up.
    const moved = translateWithin(square, 0.5, -0.5);
    expect(moved[1]).toEqual([1, 0]);
    expect(moved[3]).toEqual([0.9, 0.1]);
  });

  it('validates polygons', () => {
    expect(
      isValidPolygon([
        [0, 0],
        [1, 0],
      ] as Point[]),
    ).toBe(false);
    expect(
      isValidPolygon([
        [0, 0],
        [0.5, 0.5],
        [1, 1],
      ] as Point[]),
    ).toBe(false); // collinear
    expect(
      isValidPolygon([
        [0, 0],
        [1, 0],
        [1, 1],
      ] as Point[]),
    ).toBe(true);
  });

  it('tests points inside polygons', () => {
    const tri: Point[] = [
      [0, 0],
      [1, 0],
      [0, 1],
    ];
    expect(pointInPolygon([0.2, 0.2], tri)).toBe(true);
    expect(pointInPolygon([0.8, 0.8], tri)).toBe(false);
  });

  it('points the "in" arrow to the right of start -> end (image y down), like the edge', () => {
    // Walking left to right across the image: right-hand side is down (+y).
    expect(inwardNormal([0, 0.5], [1, 0.5])).toEqual([-0, 1]);
    // Walking downwards: right-hand side is left (-x).
    const [x, y] = inwardNormal([0.5, 0], [0.5, 1]);
    expect(x).toBeCloseTo(-1);
    expect(y).toBeCloseTo(0);
  });

  it('fits the stage to the container keeping the aspect ratio', () => {
    expect(fitStage(16 / 9, 800)).toEqual({ width: 800, height: 450 });
    expect(fitStage(16 / 9, 1600, 450)).toEqual({ width: 800, height: 450 });
  });
});
