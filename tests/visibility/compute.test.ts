import { describe, expect, it, vi } from 'vitest';
import { computeVisibility } from '../../lib/visibility/compute.ts';
import { generateSamples } from '../../lib/visibility/samples.ts';
import { FOOTPRINT_MISSING } from '../../lib/visibility/types.ts';
import { building, rectangle, scene } from './fixtures.ts';
describe('metric visibility, spec 0.2.1', () => {
  it('requires score ring coverage independently of full approach coverage and building count', () => {
    const s = scene();
    s.coverage.query_within_loaded_region = false;
    expect(computeVisibility(s)).toMatchObject({ status: 'ready', visible_ratio: 1 });
    for (const loaded of [false, undefined]) {
      s.coverage.score_ring_within_loaded_region = loaded as boolean;
      for (const buildings of [[], [building('wall', rectangle(1, -12, 2, 12), 9)]]) {
        s.buildings = buildings;
        const r = computeVisibility(s);
        expect(r).toMatchObject({ status: 'missing', reason: 'building_coverage_insufficient', samples: [] });
        expect(r.evidence.notes).not.toContain(FOOTPRINT_MISSING);
      }
    }
  });
  it.each([[7, 61 / 66, 6], [9, 19 / 36, 51]])('single wall h=%s has hand-calculated ratio %s', (height, expected, blocked) => {
    const s = scene(); s.buildings = [building('wall', rectangle(1, -12, 2, 12), height)];
    const before = structuredClone(s);
    const clock = vi.spyOn(Date, 'now').mockImplementation(() => { throw new Error('clock forbidden'); });
    try {
      const r = computeVisibility(s);
      expect(r.status).toBe('ready');
      if (r.status !== 'ready') throw new Error(r.reason);
      expect(r.visible_ratio).toBeCloseTo(expected, 12);
      expect(r.summary.all.total_weight).toBeCloseTo(330, 12);
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
    const target = r.samples.find(p => p.id === 'ring:90:20')!.target!;
    expect(target[0]).toBeCloseTo(5); expect(target[1]).toBeCloseTo(0);
  });
  it('pushes indoor/boundary samples outward up to 30m, retaining original weights', () => {
    const s = scene(); s.buildings = [building('wall', rectangle(19, -1, 65, 1), 100)];
    const r = computeVisibility(s);
    const a = r.samples.find(p => p.id === 'ring:90:20')!;
    const b = r.samples.find(p => p.id === 'ring:90:60')!;
    expect(a.status).toBe('excluded'); // 45m needed.
    expect(b.status).toBe('blocked'); expect(b.moved_m).toBeCloseTo(5.001, 6);
    expect(b.point[0]).toBeCloseTo(65.001, 6); expect(b.original_point[0]).toBeCloseTo(60);
    expect(b.weight).toBe(100 / 60);
    expect(r.summary.all.excluded).toBe(1); expect(r.summary.all.moved).toBe(2);
    expect(r.summary.all.excluded_ratio).toBeCloseTo(1 / 108);
    expect(r.summary.all.total_weight).toBeCloseTo(330 - 100 / 20);
  });
  it('generates 108 rings, 20 samples per station and 10 per school as score rings and evidence-only approaches', () => {
    const s = scene(); s.stations = [{ id: 'station', name: '역', point: [400, 0], distance_m: 400 }, { id: 'station2', name: '역2', point: [-400, 0], distance_m: 400 }];
    s.schools = [{ id: 'school1', name: '학교1', point: [0, 500], distance_m: 500 },
      { id: 'school2', name: '학교2', point: [0, 500], distance_m: 500 }];
    const all = generateSamples(s);
    expect(all).toHaveLength(168);
    expect(all.find(p => p.id === 'station:station:1')!.point).toEqual([20, 0]);
    expect(all.find(p => p.id === 'station:station:20')!.point).toEqual([400, 0]);
    const r = computeVisibility(s);
    expect(r.summary.station).toMatchObject({ generated: 40, visible: 40, total_weight: 0 });
    expect(r.summary.school).toMatchObject({ generated: 20, visible: 20, total_weight: 0 });
    expect(r.status === 'ready' && r.visible_ratio).toBe(1);
  });
  it('includes WFS and unknown 4m prisms, retaining height provenance', () => {
    const s = scene(); s.floor = 1;
    s.buildings = [{ ...building('wfs', rectangle(1, -12, 2, 12), 4),
      height_source: 'unknown', estimated: true, source: 'vworld_wfs_supplement' }];
    const r = computeVisibility(s);
    expect(r.summary.all.blocked).toBe(51);
    expect(r.evidence.values).toMatchObject({ unknown_count: 1, wfs_count: 1, estimated: true });
    s.buildings = [{ ...s.buildings[0], height_m: 3 }];
    expect(() => computeVisibility(s)).toThrow('height');
  });
  it('distinguishes unavailable sources from confirmed absence and no valid samples', () => {
    const s = scene(); s.sources = { ...s.sources, building_shp: { available: false } };
    const missing = computeVisibility(s);
    expect(missing).toMatchObject({ status: 'missing', reason: 'visibility_sources_missing:building_shp' });
    expect(missing.evidence.notes).not.toContain(FOOTPRINT_MISSING);
    const full = scene(); full.candidate_building_id = 'self'; full.containing_building_count = 1;
    full.buildings = [building('self', rectangle(-400, -400, 400, 400))];
    expect(computeVisibility(full)).toMatchObject({ status: 'missing', reason: 'no_valid_ring_samples', summary: { all: { excluded: 108 } } });
  });
  it('rejects mixed CRS/floor/identity and malformed geometry instead of showing clear sight', () => {
    expect(() => computeVisibility({ ...scene(), srid: 4326 } as never)).toThrow('contract');
    expect(() => computeVisibility({ ...scene(), floor: 0 })).toThrow('floor');
    expect(() => computeVisibility({ ...scene(), candidate_building_id: 'absent' })).toThrow('identity');
    expect(() => computeVisibility({ ...scene(), buildings: [building('bad', [[[[1, 1], [2, 2], [3, 3], [4, 4]]]])] })).toThrow('ring');
  });
});
