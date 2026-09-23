import { academyV0, type RawPreset } from "./presets.ts";
import type { RawContext, RawValue, ReferenceInputs } from "./types.ts";

export const referenceKeys = Object.freeze([
  "demand", "flow", "transit.nearest_subway_m", "transit.subway_boardings_golden",
  "transit.bus_stops", "cluster", "cluster.saturation", "environment.stores_total",
] as const);
export type ReferenceKey = typeof referenceKeys[number];
export type ReferenceRaw = Record<ReferenceKey, RawValue>;

function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value))
    throw new Error("Expected input object");
  return value as Record<string, unknown>;
}
function field(root: unknown, path: string): unknown {
  let value = root;
  for (const part of path.split(".")) {
    const parent = object(value);
    if (!Object.hasOwn(parent, part)) throw new Error(`Missing input key: ${path}`);
    value = parent[part];
  }
  return value;
}
function nonnegative(value: unknown): void {
  if (value !== null && (typeof value !== "number" || !Number.isFinite(value) || value < 0))
    throw new Error("Expected finite nonnegative number or explicit null");
}
export function parseReferenceInputs(value: unknown): ReferenceInputs {
  const numbers = [
    "demand.pop_5_9", "demand.pop_10_14", "demand.pop_15_18", "demand.schools.elem",
    "demand.schools.mid", "demand.schools.high", "flow.weekday.golden_avg_pop",
    "flow.weekend.golden_avg_pop", "transit.nearest_subway_m", "transit.subway_boardings_golden",
    "transit.bus_stops", "market.stores_total",
  ];
  for (const key of numbers) nonnegative(field(value, key));
  const counts = field(value, "compete.academies_by_field");
  if (counts !== null) for (const count of Object.values(object(counts))) {
    if (typeof count !== "number" || !Number.isSafeInteger(count) || count < 0)
      throw new Error("Invalid observed academy count");
  }
  const sources = object(field(value, "meta.sources"));
  if (typeof object(sources.subway_positions).available !== "boolean")
    throw new Error("Missing subway source availability");
  for (const key of ["meta.floor", "meta.radius_m"]) {
    if (!Number.isSafeInteger(field(value, key))) throw new Error("Invalid input radius/floor");
  }
  if (field(value, "meta.schema_version") !== academyV0.schema_version)
    throw new Error("Reference input schema differs from preset");
  return value as ReferenceInputs;
}

/** One implementation used by both the Python batch bridge and S2-2 scoring. */
export function extractReferenceRaw(
  primary: ReferenceInputs, school: ReferenceInputs, context: RawContext,
  preset: RawPreset = academyV0,
): ReferenceRaw {
  parseReferenceInputs(primary);
  parseReferenceInputs(school);
  if (!preset.radii.some(r => r === primary.meta.radius_m) ||
      school.meta.radius_m !== preset.school_radius_m || primary.meta.floor !== school.meta.floor)
    throw new Error("Reference radius/floor mismatch");
  if (context.inside_seoul !== null && typeof context.inside_seoul !== "boolean")
    throw new Error("Missing verified Seoul coverage context");
  const c = preset.demand_coef, d = primary.demand;
  const population = [d.pop_5_9, d.pop_10_14, d.pop_15_18];
  const demand: RawValue = { value: null, notes: [] };
  if (population.some(v => v === null)) demand.notes.push("missing_population_coverage");
  else {
    demand.value = d.pop_5_9! * c.pop_5_9 + d.pop_10_14! * c.pop_10_14 + d.pop_15_18! * c.pop_15_18;
    for (const [key, weight] of [["elem", c.school_elem], ["mid", c.school_mid], ["high", c.school_high]] as const) {
      const count = school.demand.schools[key];
      if (count === null) demand.notes.push(`school_${key}_missing`);
      else demand.value += count * weight;
    }
  }
  const weekday = primary.flow.weekday.golden_avg_pop, weekend = primary.flow.weekend.golden_avg_pop;
  const flow: RawValue = { value: null, notes: [] };
  if (weekday !== null && weekend !== null)
    flow.value = weekday * preset.weekday_weight + weekend * preset.weekend_weight;
  else if (weekday !== null || weekend !== null) {
    flow.value = weekday ?? weekend;
    flow.notes.push(weekday === null ? "weekday_missing" : "weekend_missing");
  } else flow.notes.push("flow_missing");
  const nearest: RawValue = { value: primary.transit.nearest_subway_m, notes: [] };
  if (nearest.value === null && context.inside_seoul === true && primary.meta.sources.subway_positions.available) {
    nearest.value = 2000;
    nearest.notes.push("no_subway_within_2000m");
  } else if (nearest.value === null) nearest.notes.push("subway_source_or_coverage_missing");
  const byField = primary.compete.academies_by_field;
  const n = byField === null ? null : (byField[preset.cluster_field] ?? 0);
  const students = population.some(v => v === null) ? null :
    d.pop_5_9! + d.pop_10_14! + d.pop_15_18!;
  // Evidence only: never contributes to the cluster score.
  const saturation: RawValue = {
    value: n === null || students === null || students === 0 ? null : n / (students / 1000),
    notes: n === null ? ["academy_source_missing"] : students === null ?
      ["missing_population_coverage"] : students === 0 ? ["zero_students"] : [],
  };
  const result: ReferenceRaw = {
    demand, flow,
    "transit.nearest_subway_m": nearest,
    "transit.subway_boardings_golden": { value: primary.transit.subway_boardings_golden, notes: [] },
    "transit.bus_stops": { value: primary.transit.bus_stops, notes: [] },
    cluster: { value: n === null ? null : Math.log1p(n), notes: n === null ? ["academy_source_missing"] : [] },
    "cluster.saturation": saturation,
    "environment.stores_total": { value: primary.market.stores_total, notes: [] },
  };
  for (const { value } of Object.values(result)) nonnegative(value);
  return result;
}
