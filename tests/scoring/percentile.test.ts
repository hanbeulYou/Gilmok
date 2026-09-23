import { describe, expect, it } from 'vitest';
import { percentile, referencePercentile } from '../../lib/scoring/percentile.ts';
import { academyV0 } from '../../lib/scoring/presets.ts';
import { inputs, reference } from './fixtures.ts';

describe('percentile contract', () => {
  it('averages 1-based ties and uses strict-less for unseen values', () => {
    const values = [30, 10, 20, 20];
    expect(percentile(values, 10)).toBe(25);
    expect(percentile(values, 20)).toBe(62.5);
    expect(percentile(values, 30)).toBe(100);
    expect(percentile(values, 25)).toBe(75);
    expect(percentile(values, 0)).toBe(0);
    expect(percentile(values, 40)).toBe(100);
    expect(values).toEqual([30, 10, 20, 20]);
    expect(percentile([7, 7, 7], 7)).toBeCloseTo(66.6666667);
  });
  it('handles empty/null without zero substitution and rejects nonfinite values', () => {
    expect(percentile([], 1)).toBeNull(); expect(percentile([1], null)).toBeNull();
    expect(() => percentile([NaN], 1)).toThrow(); expect(() => percentile([1], Infinity)).toThrow();
  });
  it('keeps exact floats, monotonic direction, and log1p ranks', () => {
    const x = Math.log1p(2), rounded = Number(x.toPrecision(15));
    expect(percentile([x, x, x], x)).not.toBe(percentile([rounded, rounded, rounded], x));
    const values = [0, 1, 1, 9];
    const scores = [0, 1, 2, 9, 10].map(x => percentile(values, x)!);
    expect(scores).toEqual([...scores].sort((a, b) => a - b));
    for (const x of [0, 1, 2, 9]) {
      expect(percentile(values, x, -1)).toBe(100 - percentile(values, x)!);
      expect(percentile(values.map(Math.log1p), Math.log1p(x))).toBe(percentile(values, x));
    }
  });
  it('isolates radius, preset/schema/source and empty-population mismatches', () => {
    const p = inputs(), s = inputs(1000), r = reference(p);
    const get = () => referencePercentile('demand', 2, p, s, academyV0, r);
    expect(get().reference).toEqual({ population_size: 3, coverage: .75 });
    r.preset.version = 'old'; expect(get().reason).toBe('reference_preset_version_mismatch');
    r.preset.version = academyV0.reference_version; r.inputs_schema_version = '1.2';
    expect(get().reason).toBe('reference_schema_version_mismatch'); r.inputs_schema_version = '1.3';
    p.meta.radius_m = 500; expect(get().reason).toBe('reference_radius_or_key_missing'); p.meta.radius_m = 800;
    s.meta.sources = { ...s.meta.sources, schools: { available: true, source_version: 'changed' } };
    expect(get().reason).toBe('reference_source_mismatch:schools'); s.meta.sources = { ...s.meta.sources, schools: p.meta.sources.schools };
    r.distributions = r.distributions.map(d => d.key === 'demand' ? { ...d, values: [] } : d);
    expect(get().reason).toBe('reference_empty');
  });
});
