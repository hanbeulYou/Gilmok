import type { ScoringPreset } from './types.ts';
export type { RawPreset } from './types.ts';

/** Versioned immutable rules. No inferred calibration or environment/IO. */
export const academyV0: ScoringPreset = Object.freeze({
  id: 'academy_v0', version: '0.2', reference_version: '0.1.2', schema_version: '1.3', radius_primary_m: 800,
  radii: Object.freeze([800, 1000]), school_radius_m: 1000,
  demand_coef: Object.freeze({ pop_5_9: 0.8, pop_10_14: 1, pop_15_18: 0.8,
    school_elem: 300, school_mid: 300, school_high: 150 }),
  weekday_weight: 0.7, weekend_weight: 0.3, cluster_field: '입시.검정 및 보습',
  weights: Object.freeze({ demand: 30, flow: 15, transit: 15, cluster: 15,
    exposure: 5, building: 10, environment: 5, rent_efficiency: 5 }),
  signs: Object.freeze({ demand: 1, flow: 1, transit: 1, cluster: 1,
    exposure: 1, building: 1, environment: 1, rent_efficiency: 1 } as const),
  saturation: Object.freeze({ high: 60, mid: 25 }), rent_range: null,
});
export function loadPreset(id: string, radius_m = 800): ScoringPreset {
  if (id !== academyV0.id || !academyV0.radii.includes(radius_m))
    throw new Error('Unsupported preset/radius');
  return Object.freeze({ ...academyV0, radius_primary_m: radius_m });
}
