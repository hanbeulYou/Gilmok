import { expect, it } from 'vitest';
import { bounds, covers, pushOutside } from '../../lib/visibility/geometry.ts';
import type { Footprint } from '../../lib/visibility/types.ts';
import { rectangle } from './fixtures.ts';
const shapes = (...polygons: Footprint[]) => polygons.map(p => ({ polygons: p, bounds: bounds(p) }));
it('pushes outward to the first opening in the union, not into a touching/overlapping building', () => {
  const walls = shapes(rectangle(25, -1, 40, 1), rectangle(40, -1, 50, 1), rectangle(45, -1, 55, 1));
  const p = pushOutside(walls, [0, 0], [30, 0])!;
  expect(p[0]).toBeCloseTo(55.001, 8); expect(p[1]).toBe(0);
  expect(walls.every(b => !covers(b.polygons, p))).toBe(true);
});
it('honors the 30m limit including a boundary exactly 30m away', () => {
  expect(pushOutside(shapes(rectangle(25, -1, 60, 1)), [0, 0], [30, 0])).toBeNull();
  const p = pushOutside(shapes(rectangle(25, -1, 59.999, 1)), [0, 0], [30, 0])!;
  expect(p[0]).toBeGreaterThan(59.999); expect(p[0]).toBeLessThanOrEqual(60);
});
it('finds narrow gaps and courtyard holes; does not step over them', () => {
  const p = pushOutside(shapes(rectangle(25, -1, 35, 1), rectangle(35.0005, -1, 70, 1)), [0, 0], [30, 0])!;
  expect(p[0]).toBeGreaterThan(35); expect(p[0]).toBeLessThan(35.0005);
  const courtyard = [[rectangle(20, -10, 80, 10)[0][0], rectangle(35, -5, 45, 5)[0][0]]];
  expect(pushOutside(shapes(courtyard), [0, 0], [30, 0])![0]).toBeCloseTo(35.001, 8);
});
it('keeps outside points, rejects undefined origin direction, handles boundary and negative directions', () => {
  expect(pushOutside([], [0, 0], [30, 0])).toEqual([30, 0]);
  expect(pushOutside(shapes(rectangle(-1, -1, 1, 1)), [0, 0], [0, 0])).toBeNull();
  expect(pushOutside(shapes(rectangle(25, 0, 40, 10)), [0, 0], [30, 0])![0]).toBeCloseTo(40.001);
  expect(pushOutside(shapes(rectangle(-40, -1, -25, 1)), [0, 0], [-30, 0])![0]).toBeCloseTo(-40.001);
});
