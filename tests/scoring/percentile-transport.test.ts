import { describe, expect, it } from 'vitest';
import { percentile, referencePercentile } from '../../lib/scoring/percentile.ts';
import { extractReferenceRaw, referenceKeys } from '../../lib/scoring/raw.ts';
import { score, reweight } from '../../lib/scoring/score.ts';
import { academyV0 } from '../../lib/scoring/presets.ts';
import type { PercentileReference } from '../../lib/scoring/types.ts';
import { candidate, context, inputs, reference } from './fixtures.ts';

function resolved(raw: number | null = 2): PercentileReference {
  const { distributions, ...metadata } = reference();
  return { ...metadata, kind: 'percentiles', percentiles: distributions.map(d => ({
    key: d.key, radius_m: d.radius_m, raw, percentile: percentile(d.values, raw),
    cell_count: d.cell_count, population_size: d.values.length,
    histogram: { min: 1, max: 3, bins: [] },
  })) };
}

describe('compact reference transport preserves v0.3', () => {
  it('keeps the complete score and reweight output identical to the full-distribution path', () => {
    const p = inputs(), school = inputs(1000), full = reference(p), compact = resolved();
    const raw = extractReferenceRaw(p, school, context, academyV0);
    compact.percentiles = full.distributions.map(d => {
      const x = raw[d.key as typeof referenceKeys[number]].value;
      return { ...compact.percentiles.find(v => v.key === d.key)!, raw: x, percentile: percentile(d.values, x) };
    });
    const before = structuredClone(compact);
    const a = score(p, school, [], null, candidate, academyV0, full, context);
    const b = score(p, school, [], null, candidate, academyV0, compact, context);
    expect(b).toEqual(a);
    expect(reweight(b, { ...academyV0.weights, demand: 40 })).toEqual(
      reweight(a, { ...academyV0.weights, demand: 40 }));
    expect(compact).toEqual(before);
  });

  it.each([null, 0, 1, 2, 2.0000000000000004, 4])('preserves nullable rank and reverse direction for %s', raw => {
    const p = inputs(), s = inputs(1000);
    for (const direction of [1, -1] as const) expect(
      referencePercentile('demand', raw, p, s, academyV0, resolved(raw), direction),
    ).toEqual(referencePercentile('demand', raw, p, s, academyV0, reference(p), direction));
  });

  it('refuses another raw, radius, source, or version rather than reusing a cached percentile', () => {
    const p = inputs(), school = inputs(1000), r = resolved();
    const call = () => referencePercentile('demand', 2, p, school, academyV0, r).reason;
    r.percentiles = r.percentiles.map(x => ({ ...x, raw: 3 }));
    expect(call()).toBe('reference_raw_mismatch');
    r.percentiles = resolved().percentiles;
    r.preset.version = 'old'; expect(call()).toBe('reference_preset_version_mismatch');
    r.preset.version = academyV0.reference_version;
    r.sources = {}; expect(call()).toBe('reference_source_mismatch:resident_population');
    r.sources = reference().sources;
    r.percentiles = r.percentiles.map(x => ({ ...x, radius_m: 1000 }));
    expect(call()).toBe('reference_radius_or_key_missing');
  });

  it('keeps empty populations missing and rejects malformed compact counts/scores', () => {
    const p = inputs(), s = inputs(1000), r = resolved();
    const row = { ...r.percentiles[0], population_size: 0, percentile: null };
    r.percentiles = [row];
    const call = () => referencePercentile('demand', 2, p, s, academyV0, r);
    expect(call()).toEqual({ value: null, reason: 'reference_empty', reference: { population_size: 0, coverage: 0 } });
    for (const invalid of [{ population_size: -1 }, { population_size: 5 }, { cell_count: 0 },
      { population_size: 3, percentile: null }, { percentile: 101 }, { percentile: NaN }]) {
      r.percentiles = [{ ...row, ...invalid }];
      expect(call().reason).toBe('invalid_reference_distribution');
    }
  });
});
