import { describe, expect, it } from 'vitest';
import { blocks, covers, nearestBoundary } from '../../lib/visibility/geometry.ts';
import { rectangle } from './fixtures.ts';
describe('closed 3D prism geometry', () => {
  it('handles concavity, holes, their boundaries and multi-polygons', () => {
    const donut = [[rectangle(-10, -10, 10, 10)[0][0], rectangle(-5, -5, 5, 5)[0][0]]];
    expect(covers(donut, [0, 0])).toBe(false);
    expect(covers(donut, [5, 0])).toBe(true);
    expect(blocks(donut, 10, [-4, 0], [4, 0], 1.5, 2)).toBe(false);
    expect(blocks(donut, 10, [-20, 0], [20, 0], 1.5, 2)).toBe(true);
    expect(nearestBoundary(donut, [0, 1])).toEqual([0, 5]);
    const l = [[[[0, 0], [10, 0], [10, 2], [2, 2], [2, 10], [0, 10], [0, 0]] as const]];
    expect(blocks(l, 10, [3, 8], [8, 3], 2, 2)).toBe(false);
    expect(blocks([...rectangle(-10, -10, -5, -5), ...rectangle(5, 5, 10, 10)], 10, [0, 0], [20, 20], 2, 2)).toBe(true);
  });
  it('tests the entire inside interval, including top equality and collinear boundary', () => {
    const wall = rectangle(4, -1, 6, 1);
    expect(blocks(wall, 5, [0, 0], [10, 0], 1, 11)).toBe(true);
    expect(blocks(wall, 4.99, [0, 0], [10, 0], 1, 11)).toBe(false);
    expect(blocks(wall, 10, [0, 1], [10, 1], 2, 2)).toBe(true);
    expect(blocks(wall, 10, [0, 2], [10, 2], 2, 2)).toBe(false);
    expect(blocks(wall, 10, [0, 0], [10, 0], -10, -1)).toBe(false);
  });
  it('preserves metric results at actual 5186 magnitudes', () => {
    const wall = rectangle(205004, 544999, 205006, 545001);
    expect(blocks(wall, 5, [205000, 545000], [205010, 545000], 1, 11)).toBe(true);
  });
});
