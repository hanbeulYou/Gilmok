import { describe, expect, it } from 'vitest';
import { score, reweight } from '../../lib/scoring/score.ts';
import { academyV0 } from '../../lib/scoring/presets.ts';
import { inputs, reference, candidate, context } from './fixtures.ts';

describe('v0.3 fixed cluster scale', () => {
  it.each([[0, 0], [27, 0], [1070, 97.47740578011098], [1108, 98.41003619754657],
    [694, 85.91014431805633], [2000, 100]])('count %s gives %s independently of live percentiles', (n, expected) => {
    const p = inputs();
    p.compete.academies_by_field = { '입시.검정 및 보습': n };
    for (const ref of [reference(p), null]) {
      const r = score(p, inputs(1000), [], null, candidate, academyV0, ref, context);
      const c = r.axes.find(a => a.key === 'cluster')!;
      expect(c.normalized).toBeCloseTo(expected, 11);
      expect(c.raw).toBe(Math.log1p(n));
      expect(c.evidence.percentile).toBeNull();
      expect(c.evidence.values.fixed_scale).toMatchObject({ p50: 3.332204510175204,
        upper: 7.070653980704802, upper_percentile: 99.97, snapshot: '20260923T111436Z' });
    }
  });
  it('keeps missing academy data NULL and still counts it in the two-data-axis gate', () => {
    const p = inputs();
    p.compete.academies_by_field = null;
    const r = () => score(p, inputs(1000), [], null, candidate, academyV0, reference(p), context);
    expect(r().axes.find(a => a.key === 'cluster')).toMatchObject({ normalized: null, missing_reason: 'raw_missing' });
    expect(r().total).not.toBeNull();
    p.market.stores_by_lcls = null;
    expect(r().total).toBeNull();
  });
  it('rejects reuse of v0.2.1 scores and invalid anchors', () => {
    const p = inputs();
    const r = score(p, inputs(1000), [], null, candidate, academyV0, reference(p), context);
    expect(() => reweight({ ...r, preset: { ...r.preset, version: '0.2.1' } }, academyV0.weights)).toThrow('version');
    const invalid = { ...academyV0, cluster_scale: { ...academyV0.cluster_scale, upper: academyV0.cluster_scale.p50 } };
    expect(() => score(p, inputs(1000), [], null, candidate, invalid, reference(p), context)).toThrow('scale');
  });
});
