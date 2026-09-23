import { describe, expect, it, vi } from 'vitest';
import { computeVisibility } from '../../lib/visibility/compute.ts';
import { generateSamples } from '../../lib/visibility/samples.ts';
import { FOOTPRINT_MISSING } from '../../lib/visibility/types.ts';
import { building, rectangle, scene } from './fixtures.ts';
describe('metric visibility, spec 0.1.4', () => {
  it.each([[7, 79 / 81, 2], [9, 19 / 36, 85]])('single wall h=%s has hand-calculated ratio %s', (height, expected, blocked) => {
    const s = scene(); s.buildings = [building('wall', rectangle(1, -12, 2, 12), height)];
    const before = structuredClone(s);
    const clock = vi.spyOn(Date, 'now').mockImplementation(() => { throw new Error('clock forbidden'); });
    try {
      const r = computeVisibility(s);
      expect(r.status).toBe('ready');
      if (r.status !== 'ready') throw new Error(r.reason);
      expect(r.visible_ratio).toBeCloseTo(expected, 12);
      expect(r.summary.all.total_weight).toBeCloseTo(162, 12);
      expect(r.summary.all.blocked).toBe(blocked);
      expect(r.summary.all.excluded).toBe(0);
      expect(r.evidence.notes).toContain(FOOTPRINT_MISSING);
      expect(r.evidence.values.estimated).toBe(true);
      expect(r.evidence.values.target_height_estimated).toBe(true);
      expect(computeVisibility(s)).toEqual(r); expect(s).toEqual(before);
    } finally { clock.mockRestore(); }
  });
  it('uses nearest candidate boundary and excludes the whole candidate from occlusion', () => {
    const s = scene(); s.candidate_building_id = 'self'; s.containing_building_count = 1;
    s.buildings = [building('self', rectangle(-5, -5, 5, 5), 100)];
    const r = computeVisibility(s);
    expect(r.status === 'ready' && r.visible_ratio).toBe(1);
    expect(r.evidence.notes).not.toContain(FOOTPRINT_MISSING);
    const target = r.samples.find(p => p.id === 'ring:90:50')!.target!;
    expect(target[0]).toBeCloseTo(5); expect(target[1]).toBeCloseTo(0);
  });
  it('removes footprint interior and boundary samples from the denominator', () => {
    const s = scene(); s.buildings = [building('wall', rectangle(49, -1, 100, 1), 100)];
    const r = computeVisibility(s);
    expect(r.summary.all.excluded).toBe(2);
    expect(r.summary.all.total_weight).toBeCloseTo(159);
    expect(r.samples.find(p => p.id === 'ring:90:100')!.status).toBe('excluded');
  });
  it('generates 180 rings, 20 station samples and 10 per school with independent weights', () => {
    const s = scene(); s.station = { id: 'station', name: '역', point: [400, 0], distance_m: 400 };
    s.schools = [{ id: 'school1', name: '학교1', point: [0, 500], distance_m: 500 },
      { id: 'school2', name: '학교2', point: [0, 500], distance_m: 500 }];
    const all = generateSamples(s);
    expect(all).toHaveLength(220);
    expect(all.find(p => p.id === 'station:station:1')!.point).toEqual([20, 0]);
    expect(all.find(p => p.id === 'station:station:20')!.point).toEqual([400, 0]);
    const r = computeVisibility(s);
    expect(r.summary.station).toMatchObject({ generated: 20, visible: 20, total_weight: 60 });
    expect(r.summary.school).toMatchObject({ generated: 20, visible: 20, total_weight: 40 });
    expect(r.status === 'ready' && r.visible_ratio).toBe(1);
  });
  it('includes WFS and unknown 4m prisms, retaining height provenance', () => {
    const s = scene(); s.floor = 1;
    s.buildings = [{ ...building('wfs', rectangle(1, -12, 2, 12), 4),
      height_source: 'unknown', estimated: true, source: 'vworld_wfs_supplement' }];
    const r = computeVisibility(s);
    expect(r.summary.all.blocked).toBe(85);
    expect(r.evidence.values).toMatchObject({ unknown_count: 1, wfs_count: 1, estimated: true });
    s.buildings = [{ ...s.buildings[0], height_m: 3 }];
    expect(() => computeVisibility(s)).toThrow('height');
  });
  it('distinguishes unavailable sources from confirmed absence and no valid samples', () => {
    const s = scene(); s.sources = { ...s.sources, schools: { available: false } };
    const missing = computeVisibility(s);
    expect(missing).toMatchObject({ status: 'missing', reason: 'visibility_sources_missing:schools' });
    expect(missing.evidence.notes).not.toContain(FOOTPRINT_MISSING);
    const full = scene(); full.candidate_building_id = 'self'; full.containing_building_count = 1;
    full.buildings = [building('self', rectangle(-400, -400, 400, 400))];
    expect(computeVisibility(full)).toMatchObject({ status: 'missing', reason: 'no_valid_samples', summary: { all: { excluded: 180 } } });
  });
  it('rejects mixed CRS/floor/identity and malformed geometry instead of showing clear sight', () => {
    expect(() => computeVisibility({ ...scene(), srid: 4326 } as never)).toThrow('contract');
    expect(() => computeVisibility({ ...scene(), floor: 0 })).toThrow('floor');
    expect(() => computeVisibility({ ...scene(), candidate_building_id: 'absent' })).toThrow('identity');
    expect(() => computeVisibility({ ...scene(), buildings: [building('bad', [[[[1, 1], [2, 2], [3, 3], [4, 4]]]])] })).toThrow('ring');
  });
});
