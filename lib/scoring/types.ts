/** The v1.3 projection used by reference extraction; no scoring or IO here. */
export type NullableNumber = number | null;
export interface SourceMetadata {
  available: boolean;
  [key: string]: unknown;
}
export interface ReferenceInputs {
  demand: {
    pop_5_9: NullableNumber;
    pop_10_14: NullableNumber;
    pop_15_18: NullableNumber;
    schools: { elem: NullableNumber; mid: NullableNumber; high: NullableNumber };
  };
  flow: {
    weekday: { golden_avg_pop: NullableNumber };
    weekend: { golden_avg_pop: NullableNumber };
  };
  transit: {
    nearest_subway_m: NullableNumber;
    subway_boardings_golden: NullableNumber;
    bus_stops: NullableNumber;
  };
  compete: { academies_by_field: Readonly<Record<string, number>> | null };
  market: { stores_total: NullableNumber };
  meta: {
    schema_version: string;
    radius_m: number;
    floor: number;
    sources: Readonly<Record<string, SourceMetadata>>;
  };
}
export interface RawContext {
  /** Same ST_Covers(admin_dongs, point) predicate as score_inputs. Unknown is not false. */
  inside_seoul: boolean | null;
}
export interface RawValue {
  value: NullableNumber;
  notes: string[];
}

export type AxisKey = 'demand' | 'flow' | 'transit' | 'cluster' | 'exposure' |
  'building' | 'environment' | 'rent_efficiency';
export type Weights = Readonly<Record<AxisKey, number>>;
export interface RawPreset {
  id: string; version: string; schema_version: string;
  radii: readonly number[]; school_radius_m: number;
  demand_coef: Readonly<Record<'pop_5_9' | 'pop_10_14' | 'pop_15_18' |
    'school_elem' | 'school_mid' | 'school_high', number>>;
  weekday_weight: number; weekend_weight: number; cluster_field: string;
}
export interface ScoringPreset extends RawPreset {
  reference_version: string; radius_primary_m: number; weights: Weights;
  signs: Readonly<Record<AxisKey, 1 | -1>>;
  saturation: { readonly high: number; readonly mid: number };
  rent_range: { readonly lo: number; readonly hi: number } | null;
}
export interface FloorUse {
  floor_no: number | null; floor_kind: string | null; use_name: string | null;
  other_use?: string | null; use_code?: string | null; area_m2: number | null;
}
export interface BuildingInput {
  id: string | null; register_pk: string | null; location_basis: string | null;
  main_use: { code: string | null; name: string | null; other_use: string | null };
  gross_area: number | null; floors_above: number | null; floors_below: number | null;
  floor_use: readonly FloorUse[] | null; all_floors: readonly FloorUse[];
  elevators: { passenger: number | null; emergency: number | null };
}
export interface RentInput {
  trade_median_per_m2: number | null; trade_building_type: string | null;
  trade_sample_count: number | null; survey_rent_per_m2: number | null;
  survey_vacancy: number | null; survey_building_class: string | null;
  rent_level: string | null; survey_by_building_class: Readonly<Record<string, unknown>>;
}
export type ScoreInputs = ReferenceInputs & {
  demand: { estimated: boolean };
  flow: { estimated: boolean; low_coverage: boolean };
  transit: { subway_units_missing_golden: number | null };
  market: { stores_by_lcls: Readonly<Record<string, number>> | null };
  building: BuildingInput | null; rent: RentInput;
  meta: {
    computed_at: string; legal_dong_code: string | null;
    building_lookup: { status: string };
    height_quality: { unknown_ratio: number | null };
    flow_coverage: { weekday: { coverage_ratio: readonly (number | null)[] };
      weekend: { coverage_ratio: readonly (number | null)[] } };
  };
};
export interface Candidate {
  lat: number; lng: number; floor: number; address?: string | null;
  exclusive_area_m2?: number | null; deposit_krw?: number | null;
  monthly_rent_krw?: number | null; maintenance_krw?: number | null;
}
export interface ScoreContext extends RawContext {
  seoul_boundary_distance_m?: number | null;
  legal_dong_names?: Readonly<Record<string, string>>; computed_at?: string;
}
export interface ReferenceDistribution {
  radius_m: number; key: string; cell_count: number; values: readonly number[];
}
export interface ScoreReference {
  preset: { id: string; version: string }; inputs_schema_version: string;
  snapshot: string; source_fingerprint: string;
  sources: Readonly<Record<string, SourceMetadata | readonly SourceMetadata[]>>;
  distributions: readonly ReferenceDistribution[];
}
export interface Evidence {
  values: Record<string, unknown>; percentile: number | null;
  rules_applied: string[]; reference: { population_size: number; coverage: number } | null;
  notes: string[];
}
export interface AxisResult {
  key: AxisKey; label: string; weight: number; effective_weight: number;
  status: 'scored' | 'missing' | 'pending';
  raw: number | null; normalized: number | null; contribution: number | null;
  evidence: Evidence; missing_reason: string | null;
}
export interface ScoreResult {
  preset: { id: string; version: string }; inputs_schema_version: string;
  total: number | null; confidence: { value: number; reasons: string[] };
  axes: AxisResult[];
  derived: { academy_eligible: boolean | null; academy_eligible_reasons: string[] };
  computed_at: string;
}
export type ExposureInput = ({ status: 'ready'; model_version: '0.2.1'; visible_ratio: number } |
  { status: 'pending' | 'missing'; reason: string }) & {
    evidence?: { values: Record<string, unknown>; notes: readonly string[] };
  } | null;
