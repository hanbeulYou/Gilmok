/** Approved raw formula inputs. Full axis scoring is S2-2. */
export const academyV0 = Object.freeze({
  id: "academy_v0",
  version: "0.1.1",
  schema_version: "1.2",
  radii: Object.freeze([800, 1000] as const),
  school_radius_m: 1000,
  demand_coef: Object.freeze({ pop_5_9: 0.8, pop_10_14: 1, pop_15_18: 0.8,
    school_elem: 300, school_mid: 300, school_high: 150 }),
  weekday_weight: 0.7,
  weekend_weight: 0.3,
  cluster_field: "입시.검정 및 보습",
});
export type RawPreset = typeof academyV0;
