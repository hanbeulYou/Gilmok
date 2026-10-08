import { describe, expect, it } from 'vitest';
import { sliderPolicy, summarizeSliderSets } from '../e2e/slider-performance';

const set = (p95: number, max = p95) => [...Array<number>(95).fill(p95), ...Array<number>(5).fill(max)];

describe('slider performance policy', () => {
  it('uses three p95 values, retains the outlier/max, and keeps production strict', () => {
    const sets = [set(50, 180), set(126, 240), set(66, 160)];
    const ci = summarizeSliderSets(sets, 'ci');
    expect(ci.passed).toBe(true);
    expect(ci.medianP95).toBe(66);
    expect(ci.max).toBe(240);
    expect(ci.sets.map(set => [set.samples, set.p95, set.max])).toEqual([
      [100, 50, 180], [100, 126, 240], [100, 66, 160],
    ]);
    expect(summarizeSliderSets(sets, 'production').passed).toBe(false);
  });
  it('fails two slow sets, includes 100ms, and uses nearest-rank p95', () => {
    expect(summarizeSliderSets([set(50), set(101), set(102)], 'ci').passed).toBe(false);
    expect(summarizeSliderSets([set(100), set(100), set(100)], 'production').passed).toBe(true);
    const descending = Array.from({ length:100 }, (_, i) => 100 - i);
    expect(summarizeSliderSets([descending, descending, descending], 'ci').medianP95).toBe(95);
    expect(descending[0]).toBe(100);
  });
  it('rejects missing samples, missing sets, and nonfinite durations', () => {
    for (const sets of [[set(30)], [set(30), set(30), [30]], [set(30), set(30), set(NaN)]]) {
      expect(() => summarizeSliderSets(sets, 'ci')).toThrow();
    }
    expect(sliderPolicy()).toBe('production');
    expect(() => sliderPolicy('relaxed')).toThrow();
  });
});
