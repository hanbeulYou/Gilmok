import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import type { ScoreResult } from '../../lib/scoring/types.ts';
import { score, reweight } from '../../lib/scoring/score.ts';
import { academyV0, loadPreset } from '../../lib/scoring/presets.ts';
import { inputs, reference, context, candidate } from './fixtures.ts';
const run = (p = inputs(), s = inputs(1000)) => score(p, s, [], null, candidate, academyV0, reference(p), context);

describe('pure ScoreResult v0.2', () => {
  it('is deterministic, does not mutate inputs, and does not read the clock', () => {
    const p = inputs(), s = inputs(1000), r = reference(p), before = JSON.stringify([p, s, r, candidate, academyV0]);
    const clock = vi.spyOn(Date, 'now').mockImplementation(() => { throw new Error('clock forbidden'); });
    try {
      const a = score(p, s, [], null, candidate, academyV0, r, context);
      expect(score(p, s, [], null, candidate, academyV0, r, context)).toEqual(a);
      expect(JSON.stringify([p, s, r, candidate, academyV0])).toBe(before);
      expect(a.computed_at).toBe(p.meta.computed_at);
      expect(a.axes).toHaveLength(8); expect(a.total).not.toBeNull();
    } finally { clock.mockRestore(); }
  });
  it('reallocates missing axes until two percentile axes are missing; zero available weight gives NULL', () => {
    const p = inputs(), s = inputs(1000), r = reference(p);
    const one = score(p, s, [], { status: 'ready', model_version: '0.2', visible_ratio: .5 }, candidate, academyV0, r, context);
    expect(one.axes.filter(a => a.normalized === null)).toHaveLength(1);
    const two = run(p, s); expect(two.axes.filter(a => a.normalized === null)).toHaveLength(2);
    expect(two.axes.reduce((sum, a) => sum + a.effective_weight, 0)).toBeCloseTo(100);
    p.demand.pop_5_9 = null; const three = run(p, s);
    expect(three.total).not.toBeNull(); expect(three.axes.find(a => a.key === 'flow')!.normalized).not.toBeNull();
    p.market.stores_by_lcls = null;
    expect(run(p, s).total).toBeNull();
    const zero = Object.fromEntries(Object.keys(academyV0.weights).map(k => [k, 0])) as unknown as typeof academyV0.weights;
    expect(reweight(two, zero).total).toBeNull();
  });
  it('scores with all three rule axes missing, retaining missing values and redistribution evidence', () => {
    const p = inputs(); p.building = null;
    const result = run(p);
    expect(result.axes.filter(a => a.normalized === null).map(a => a.key)).toEqual(['exposure', 'building', 'rent_efficiency']);
    expect(result.total).not.toBeNull();
    expect(result.axes.reduce((sum, a) => sum + a.effective_weight, 0)).toBeCloseTo(100);
    for (const a of result.axes.filter(a => a.normalized === null)) {
      expect(a.effective_weight).toBe(0); expect(a.contribution).toBeNull();
      expect(a.evidence.notes.some(n => n.includes('재배분'))).toBe(true);
    }
    expect(reweight(result, academyV0.weights)).toEqual(result);
  });
  const actualResults = JSON.parse(readFileSync(new URL('../../docs/validation/s2-2-score-results.json', import.meta.url), 'utf8')) as
    { name: string; candidate: { lat: number; lng: number }; radius_m: number; result: ScoreResult }[];
  it.each(actualResults.filter(c => c.name === '학여울'))('학여울 $radius_m m: recorded axes produce a total with rule axes missing', c => {
    expect(c.candidate).toMatchObject({ lat: 37.496663, lng: 127.070594 });
    expect(() => reweight(c.result, academyV0.weights)).toThrow('axis contract mismatch');
    // Reuse only the historical normalized observations as a v0.2 reweight fixture.
    const updated = { ...c.result, preset: { id: academyV0.id, version: academyV0.version },
      axes: c.result.axes.map(a => ({ ...a, key: (String(a.key) === 'visibility' ? 'exposure' : a.key) as typeof a.key })) };
    const result = reweight(updated, academyV0.weights);
    const available = result.axes.filter(a => a.normalized !== null);
    expect(available.map(a => a.key)).toEqual(['demand', 'flow', 'transit', 'cluster', 'environment']);
    const expected = available.reduce((sum, a) => sum + a.normalized! * a.weight, 0) / 80;
    expect(result.total).toBeCloseTo(expected, 10);
    expect(result.confidence).toEqual(c.result.confidence);
    expect(reweight(result, { ...academyV0.weights, building: 100 }).total).toBeCloseTo(expected, 10);
  });
  it.each(['demand', 'flow', 'transit', 'cluster', 'environment'] as const)(
    '%s counts toward the percentile missing threshold even with zero weight', key => {
      const result = run();
      for (const a of result.axes) { a.normalized = 50; a.status = 'scored'; }
      result.axes.find(a => a.key === key)!.normalized = null;
      expect(reweight(result, academyV0.weights).total).toBeCloseTo(50, 10);
      result.axes.find(a => a.key === (key === 'demand' ? 'environment' : 'demand'))!.normalized = null;
      expect(reweight(result, { ...academyV0.weights, [key]: 0 }).total).toBeNull();
    });
  it('sliders change total/contributions only; normalized/raw/reference/confidence are invariant', () => {
    const result = run(), before = structuredClone(result);
    const changed = reweight(result, { ...academyV0.weights, building: 100, demand: 0 });
    expect(result).toEqual(before); expect(changed.confidence).toEqual(result.confidence);
    expect(changed.total).not.toBe(result.total);
    for (let i = 0; i < result.axes.length; i++) {
      expect(changed.axes[i].normalized).toBe(result.axes[i].normalized);
      expect(changed.axes[i].raw).toBe(result.axes[i].raw);
      expect(changed.axes[i].evidence).toEqual(result.axes[i].evidence);
    }
    for (const value of [-1, NaN, Infinity]) expect(() => reweight(result, { ...academyV0.weights, demand: value })).toThrow();
  });
  it('keeps a genuine zero score available and handles observed-zero category maps', () => {
    const p = inputs(), s = inputs(1000);
    p.demand.pop_5_9 = p.demand.pop_10_14 = p.demand.pop_15_18 = 0;
    s.demand.schools = { elem: 0, mid: 0, high: 0 }; p.market.stores_total = 0; p.market.stores_by_lcls = {};
    const result = run(p, s), demand = result.axes.find(a => a.key === 'demand')!;
    expect(demand.normalized).toBe(0); expect(demand.status).toBe('scored');
    expect(result.axes.find(a => a.key === 'environment')!.normalized).toBe(20);
    expect(result.axes.find(a => a.key === 'cluster')!.evidence.values.saturation).toBeNull();
  });
  it('keeps other bundles alive when school input, category map or one day group is missing', () => {
    const p = inputs(), s = inputs(1000); s.meta.schema_version = 'old';
    p.flow.weekend.golden_avg_pop = null; p.market.stores_by_lcls = null;
    const result = run(p, s);
    expect(result.axes.find(a => a.key === 'demand')!.normalized).toBeNull();
    expect(result.axes.find(a => a.key === 'environment')!.normalized).toBeNull();
    expect(result.axes.find(a => a.key === 'flow')!.raw).toBe(80);
    expect(result.axes.find(a => a.key === 'transit')!.normalized).not.toBeNull();
  });
  it('applies confidence deductions once and independently of slider weights', () => {
    const p = inputs(); p.demand.estimated = p.flow.estimated = true; p.flow.low_coverage = true;
    p.meta.flow_coverage.weekday.coverage_ratio = Array(24).fill(.79);
    p.meta.height_quality.unknown_ratio = .31; p.transit.subway_units_missing_golden = 1;
    p.meta.building_lookup.status = 'pending'; p.building = null;
    const result = score(p, inputs(1000), [], null, candidate, academyV0, reference(p), { ...context, seoul_boundary_distance_m: 999 });
    // Missing exposure/rent=10, estimate=5, flow=10, height=10, pending=15, subway=5, boundary=5.
    expect(result.confidence.value).toBe(40);
    expect(result.confidence.reasons.filter(r => r.includes('면적 비례'))).toHaveLength(1);
    expect(result.confidence.reasons.some(r => r.includes('대장 미연결'))).toBe(false);
    expect(reweight(result, { ...academyV0.weights, exposure: 0 }).confidence).toEqual(result.confidence);
  });
  it('uses v0.1.2 saturation thresholds; values never alter cluster scoring', () => {
    const p = inputs(); p.demand.pop_5_9 = p.demand.pop_10_14 = 0; p.demand.pop_15_18 = 1000;
    for (const [n, level] of [[24, 'low'], [25, 'mid'], [59, 'mid'], [60, 'high']] as const) {
      p.compete.academies_by_field = { '입시.검정 및 보습': n };
      const c = run(p).axes.find(a => a.key === 'cluster')!;
      expect(c.evidence.values.saturation_level).toBe(level);
      expect(c.normalized).toBe(100);
      expect(c.evidence.notes.some(n => n.includes('외부 통학 수요'))).toBe(true);
    }
  });
  it('keeps uncalibrated rent NULL and attaches trade values only as evidence', () => {
    const c = { ...candidate, deposit_krw: 0, monthly_rent_krw: 1000000, maintenance_krw: 0 };
    const p = inputs();
    const result = score(p, inputs(1000), [], null, c, academyV0, reference(p), context);
    const rent = result.axes.find(a => a.key === 'rent_efficiency')!;
    expect(rent.normalized).toBeNull(); expect(rent.missing_reason).toBe('rent_range_uncalibrated');
    expect(rent.evidence.values.trade_median_per_m2_manwon).toBe(1234);
    expect(rent.evidence.values.legal_dong).toBe('11680106');
    expect(rent.evidence.values.rent_per_m2).toBe(10000);
    expect(() => score(p, inputs(1000), [], null, { ...c, exclusive_area_m2: 0 }, academyV0, reference(p), context)).toThrow();
  });
  it('rejects input-version/radius mixing and honors negative preset signs', () => {
    const p = inputs(); p.meta.schema_version = '1.2'; expect(run(p).total).toBeNull();
    p.meta.schema_version = '1.3'; p.meta.radius_m = 500; expect(run(p).total).toBeNull();
    p.meta.radius_m = 800;
    const preset = { ...academyV0, signs: { ...academyV0.signs, cluster: -1 as const } };
    const result = score(p, inputs(1000), [], null, candidate, preset, reference(p), context);
    expect(result.axes.find(a => a.key === 'cluster')!.normalized).toBe(100 - run(p).axes.find(a => a.key === 'cluster')!.normalized!);
    expect(loadPreset('academy_v0', 1000).radius_primary_m).toBe(1000);
    expect(() => loadPreset('other')).toThrow();
  });
  it('uses oriented demand/flow scores in a supplied calibrated rent range', () => {
    const p = inputs(), c = { ...candidate, deposit_krw: 0, maintenance_krw: 0, monthly_rent_krw: 100 };
    const preset = { ...academyV0, rent_range: { lo: 0, hi: 100 }, signs: { ...academyV0.signs, demand: -1 as const } };
    const result = score(p, inputs(1000), [], null, c, preset, reference(p), context);
    expect(result.axes.find(a => a.key === 'rent_efficiency')!.normalized).toBe(50);
    expect(() => score(p, inputs(1000), [], null, { ...c, monthly_rent_krw: Number.MAX_VALUE, maintenance_krw: Number.MAX_VALUE }, preset, reference(p), context)).toThrow('overflow');
  });
  it('treats source changes as local to the affected axis, without guessing a neighbor reference', () => {
    const p = inputs(), ref = reference(p); p.meta.sources = { ...p.meta.sources, living_population: { available: false } };
    const r = score(p, inputs(1000), [], null, candidate, academyV0, ref, context);
    expect(r.axes.find(a => a.key === 'flow')!.missing_reason).toContain('source_mismatch');
    expect(r.axes.find(a => a.key === 'demand')!.normalized).not.toBeNull();
  });
});
