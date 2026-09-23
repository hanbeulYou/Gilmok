import { academyV0 } from '../../lib/scoring/presets.ts';
import { referenceKeys } from '../../lib/scoring/raw.ts';
import type { Candidate, ScoreContext, ScoreInputs, ScoreReference } from '../../lib/scoring/types.ts';

export const candidate: Candidate = { lat: 37.494612, lng: 127.063642, floor: 2, exclusive_area_m2: 100 };
export const context: ScoreContext = { inside_seoul: true, seoul_boundary_distance_m: 2000 };
export function inputs(radius = 800): ScoreInputs {
  const sources = Object.fromEntries(['resident_population', 'admin_boundaries', 'schools',
    'living_population', 'population_grid', 'subway_positions', 'bus_positions', 'transit_counts',
    'academies', 'stores'].map(k => [k, { available: true, source: k, source_version: 'fixture' }]));
  return {
    demand: { pop_5_9: 100, pop_10_14: 200, pop_15_18: 300, schools: { elem: 1, mid: 2, high: 3 }, estimated: false },
    flow: { weekday: { golden_avg_pop: 80 }, weekend: { golden_avg_pop: 100 }, low_coverage: false, estimated: false },
    transit: { nearest_subway_m: 200, subway_boardings_golden: 1000, bus_stops: 5, subway_units_missing_golden: 0 },
    market: { stores_total: 50, stores_by_lcls: { P1: 50 } },
    compete: { academies_by_field: { '입시.검정 및 보습': 10 } },
    building: { id: 'fixture', register_pk: 'fixture', location_basis: 'footprint', gross_area: 1000,
      main_use: { code: '04', name: '제2종근린생활시설', other_use: null }, floors_above: 5, floors_below: 1,
      floor_use: [{ floor_no: 2, floor_kind: '20', use_name: '학원', other_use: '제2종근린생활시설(학원)', area_m2: 100 }],
      all_floors: [], elevators: { passenger: 0, emergency: 0 } },
    rent: { trade_median_per_m2: 12340000, trade_building_type: 'collective', trade_sample_count: 5,
      survey_rent_per_m2: null, survey_vacancy: null, survey_building_class: null, rent_level: null, survey_by_building_class: {} },
    meta: { schema_version: '1.3', radius_m: radius, floor: 2, computed_at: '2026-09-23T00:00:00Z',
      sources, legal_dong_code: '11680106', building_lookup: { status: 'not_requested' },
      height_quality: { unknown_ratio: 0 }, flow_coverage: {
        weekday: { coverage_ratio: Array(24).fill(1) }, weekend: { coverage_ratio: Array(24).fill(1) } } },
  };
}
export function reference(primary = inputs()): ScoreReference {
  return { preset: { id: academyV0.id, version: academyV0.version }, inputs_schema_version: academyV0.schema_version,
    snapshot: '20260923T000000Z', source_fingerprint: 'fixture', sources: structuredClone(primary.meta.sources),
    distributions: referenceKeys.map(key => ({ radius_m: primary.meta.radius_m, key, cell_count: 4, values: [1, 2, 3] })) };
}
