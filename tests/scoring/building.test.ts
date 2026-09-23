import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { buildingAxis } from '../../lib/scoring/building.ts';
import type { ScoreInputs } from '../../lib/scoring/types.ts';
import { candidate, inputs } from './fixtures.ts';

const real = JSON.parse(readFileSync(new URL('../../docs/validation/pr7-building-all-floors-20260922.json', import.meta.url), 'utf8'));
describe('building rules and real register fixtures', () => {
  for (const path of ['footprint', 'address_cache']) for (const floor of [3, 4]) {
    it(`${path} 역삼로460 ${floor}층 = ${floor === 3 ? 100 : 90}`, () => {
      const p = structuredClone(real[path][floor].result) as ScoreInputs;
      // gross_area is the verified title field, not the 173.68m² floor-use area.
      p.building!.gross_area = 849.97;
      const result = buildingAxis(p, { ...candidate, floor, exclusive_area_m2: null });
      expect(result.axis.normalized).toBe(floor === 3 ? 100 : 90);
      expect(result.axis.evidence.values.other_academy_floor_count).toBe(3);
      expect(result.axis.evidence.rules_applied.filter(r => r.startsWith('R1:'))).toHaveLength(1);
    });
  }
  it('counts distinct other academy floors, excluding requested, unknown and roof', () => {
    const p = inputs(); const row = { floor_no: 3, floor_kind: '20', use_name: '학원', area_m2: 10 };
    p.building!.all_floors = [row, { ...row }, { ...row, floor_no: 2 }, { ...row, floor_kind: '30' },
      { ...row, floor_no: null }, { ...row, floor_kind: null }];
    expect(buildingAxis(p, candidate).axis.evidence.values.other_academy_floor_count).toBe(1);
  });
  it('does not stack elevator penalties and distinguishes unknown from zero', () => {
    const p = inputs();
    const six = buildingAxis(p, { ...candidate, floor: 6 });
    expect(six.axis.evidence.rules_applied.filter(r => r.startsWith('R3:'))).toEqual(['R3:-30']);
    p.building!.elevators.passenger = null;
    expect(buildingAxis(p, { ...candidate, floor: 6 }).axis.evidence.rules_applied).not.toContain('R3:-30');
  });
  it.each([-1, -2])('basement %s applies only R7 for floor preference, preserving other rules', floor => {
    const result = buildingAxis(inputs(), { ...candidate, floor });
    expect(result.axis.evidence.rules_applied.some(r => r.startsWith('R4:'))).toBe(false);
    expect(result.axis.evidence.rules_applied).toContain('R7:-25');
    expect(result.axis.evidence.rules_applied).toContain('R1:+25');
    expect(result.axis.normalized).toBe(60); // Base 60 + R1 25 - R7 25.
  });
  it.each([[1649, false], [1649.999, false], [1650, null], [1651, null], [null, null]] as const)(
    'R6 gross_area=%s -> eligible=%s, always -40, no room-distance calculation', (area, eligible) => {
      const p = inputs(); p.building!.gross_area = area;
      p.building!.all_floors = [{ floor_no: 1, floor_kind: '20', use_name: '노래연습장', area_m2: 1 }];
      const result = buildingAxis(p, candidate);
      expect(result.eligible).toBe(eligible); expect(result.axis.evidence.rules_applied).toContain('R6:-40');
    });
  it('applies R1/R2 and never uses register or floor area as exclusive area', () => {
    const p = inputs();
    expect(buildingAxis(p, { ...candidate, exclusive_area_m2: 500 }).eligible).toBe(false);
    p.building!.floor_use = [{ floor_no: 2, floor_kind: '20', use_name: '교육연구시설', area_m2: 10 }];
    expect(buildingAxis(p, { ...candidate, exclusive_area_m2: 500 }).eligible).toBe(true);
    p.building!.floor_use = [{ floor_no: 2, floor_kind: '20', use_name: '제1종근린생활시설', area_m2: 10 }];
    expect(buildingAxis(p, candidate).eligible).toBe(false);
  });
  it('holds missing floor use at 60 but preserves an observed R6 prohibition', () => {
    const p = inputs(); p.building!.floor_use = null;
    expect(buildingAxis(p, candidate).axis).toMatchObject({ normalized: 60, status: 'pending' });
    p.building!.all_floors = [{ floor_no: 1, floor_kind: '20', use_name: '숙박', area_m2: 20 }];
    expect(buildingAxis(p, candidate).axis.normalized).toBe(20);
    expect(buildingAxis(p, candidate).eligible).toBe(false);
  });
  it('education use does not require an invented exclusive area', () => {
    const p = inputs(); p.building!.floor_use = [{ floor_no: 2, floor_kind: '20', use_name: '교육연구시설', area_m2: null }];
    const result = buildingAxis(p, { ...candidate, exclusive_area_m2: null });
    expect(result.eligible).toBe(true);
    expect(result.reasons).not.toContain('exclusive_area_unknown');
  });
  it('recognizes the RPC all-null building placeholder as no candidate building', () => {
    const p = inputs(); p.building!.id = p.building!.register_pk = p.building!.location_basis = null;
    p.building!.floor_use = null;
    expect(buildingAxis(p, candidate).axis).toMatchObject({ normalized: null, status: 'missing' });
  });
  it('holds pending/processing at 60 even with no building; plain absence is missing', () => {
    const p = inputs(); p.building = null;
    expect(buildingAxis(p, candidate).axis.normalized).toBeNull();
    for (const status of ['pending', 'processing']) {
      p.meta.building_lookup.status = status;
      expect(buildingAxis(p, { ...candidate, floor: 6 }).axis).toMatchObject({ normalized: 60, status: 'pending' });
    }
  });
});
