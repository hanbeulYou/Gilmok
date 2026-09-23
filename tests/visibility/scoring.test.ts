import { expect, it } from 'vitest';
import { score, reweight } from '../../lib/scoring/score.ts';
import { academyV0 } from '../../lib/scoring/presets.ts';
import { computeVisibility } from '../../lib/visibility/compute.ts';
import { FOOTPRINT_MISSING } from '../../lib/visibility/types.ts';
import { inputs, candidate, context, reference } from '../scoring/fixtures.ts';
import { scene, building, rectangle } from './fixtures.ts';
it('injects ready evidence and deducts missing self occlusion once, invariant under sliders', () => {
  const s = scene(); s.floor = candidate.floor; s.candidate_wgs84 = { lat: candidate.lat, lng: candidate.lng };
  const p = inputs(), visibility = computeVisibility(s);
  const result = score(p, inputs(1000), [], visibility, candidate, academyV0, reference(p), context);
  const axis = result.axes.find(a => a.key === 'exposure')!;
  expect(axis.normalized).toBe(100); expect(axis.evidence.notes).toContain(FOOTPRINT_MISSING);
  expect(result.confidence.reasons.filter(r => r.includes(FOOTPRINT_MISSING))).toHaveLength(1);
  const changed = reweight(result, { ...academyV0.weights, exposure: 0 });
  expect(changed.confidence).toEqual(result.confidence); expect(changed.axes.find(a => a.key === 'exposure')!.evidence).toEqual(axis.evidence);
  s.candidate_building_id = 'self'; s.containing_building_count = 1; s.buildings = [building('self', rectangle(-1, -1, 1, 1))];
  const complete = score(p, inputs(1000), [], computeVisibility(s), candidate, academyV0, reference(p), context);
  expect(complete.confidence.value - result.confidence.value).toBe(5);
  const pending = score(p, inputs(1000), [], null, candidate, academyV0, reference(p), context);
  expect(pending.confidence.reasons.some(r => r.includes(FOOTPRINT_MISSING))).toBe(false);
});

it('always shows the field limitation and rejects an old computed visibility result', () => {
  const p = inputs();
  for (const v of [null, { status: 'missing', reason: 'fixture' }] as const) {
    const r = score(p, inputs(1000), [], v, candidate, academyV0, reference(p), context);
    expect(r.axes.find(a => a.key === 'exposure')!.evidence.notes).toContain('가로수·가로시설물·간판 크기 미반영, 현장 확인 필요');
    expect(r.axes.some(a => String(a.key) === 'visibility')).toBe(false);
  }
  const r = score(p, inputs(1000), [], { status: 'ready', visible_ratio: 1 } as never, candidate, academyV0, reference(p), context);
  expect(r.axes.find(a => a.key === 'exposure')!.missing_reason).toBe('exposure_model_version_mismatch');
  expect(academyV0.weights.demand).toBe(30); expect(academyV0.weights.exposure).toBe(5);
  expect(Object.values(academyV0.weights).reduce((a, b) => a + b, 0)).toBe(100);
  expect(r.preset.version).toBe('0.2');
  expect(academyV0.reference_version).toBe('0.1.2');
});
