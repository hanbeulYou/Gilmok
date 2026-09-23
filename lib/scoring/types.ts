/** The v1.2 projection used by reference extraction; no scoring or IO here. */
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
