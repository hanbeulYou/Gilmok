import { describe, expect, it } from "vitest";
import { academyV0 } from "../../lib/scoring/presets.ts";
import { extractReferenceRaw, parseReferenceInputs } from "../../lib/scoring/raw.ts";
import type { ReferenceInputs } from "../../lib/scoring/types.ts";

function inputs(radius = 800): ReferenceInputs {
  return {
    demand: { pop_5_9: 100, pop_10_14: 200, pop_15_18: 300, schools: { elem: 1, mid: 2, high: 3 } },
    flow: { weekday: { golden_avg_pop: 80 }, weekend: { golden_avg_pop: 100 } },
    transit: { nearest_subway_m: 200, subway_boardings_golden: 1000, bus_stops: 5 },
    compete: { academies_by_field: { "입시.검정 및 보습": 10 } },
    market: { stores_total: 50 },
    meta: { schema_version: "1.3", radius_m: radius, floor: 2, sources: { subway_positions: { available: true } } },
  };
}
const context = { inside_seoul: true };

describe("approved reference raw formulas", () => {
  it("pairs primary population with 1km schools, preserving input objects", () => {
    const primary = inputs(), school = inputs(1000);
    primary.demand.schools = { elem: 999, mid: 999, high: 999 };
    const before = JSON.stringify([primary, school]);
    const raw = extractReferenceRaw(primary, school, context);
    expect(raw.demand.value).toBe(1870);
    expect(raw.flow.value).toBe(86);
    expect(raw.cluster.value).toBe(Math.log1p(10));
    expect(raw["transit.subway_boardings_golden"].value).toBe(1000);
    expect(JSON.stringify([primary, school])).toBe(before);
    expect(extractReferenceRaw(primary, school, context)).toEqual(raw);
    expect(academyV0.version).toBe("0.1.2");
  });
  it("retains population null but excludes only missing school terms", () => {
    const p = inputs(), s = inputs(1000);
    s.demand.schools.mid = null;
    expect(extractReferenceRaw(p, s, context).demand).toEqual({ value: 1270, notes: ["school_mid_missing"] });
    p.demand.pop_15_18 = null;
    expect(extractReferenceRaw(p, s, context).demand.value).toBeNull();
  });
  it("renormalizes one available day group, including an observed zero", () => {
    const p = inputs(), s = inputs(1000);
    p.flow.weekday.golden_avg_pop = 0;
    p.flow.weekend.golden_avg_pop = null;
    expect(extractReferenceRaw(p, s, context).flow.value).toBe(0);
    p.flow.weekday.golden_avg_pop = null;
    expect(extractReferenceRaw(p, s, context).flow.value).toBeNull();
  });
  it("distinguishes observed missing category from unavailable academy source", () => {
    const p = inputs(), s = inputs(1000);
    p.compete.academies_by_field = {};
    expect(extractReferenceRaw(p, s, context).cluster.value).toBe(0);
    p.compete.academies_by_field = null;
    expect(extractReferenceRaw(p, s, context).cluster.value).toBeNull();
  });
  it("keeps saturation as separate evidence with paired null and zero guards", () => {
    const p = inputs(), s = inputs(1000);
    expect(extractReferenceRaw(p, s, context)["cluster.saturation"].value).toBeCloseTo(10 / 0.6);
    const cluster = extractReferenceRaw(p, s, context).cluster;
    p.demand.pop_5_9 = null;
    expect(extractReferenceRaw(p, s, context)["cluster.saturation"].value).toBeNull();
    expect(extractReferenceRaw(p, s, context).cluster).toEqual(cluster);
    p.demand.pop_5_9 = p.demand.pop_10_14 = p.demand.pop_15_18 = 0;
    expect(extractReferenceRaw(p, s, context)["cluster.saturation"].value).toBeNull();
    p.demand.pop_10_14 = 100;
    p.compete.academies_by_field = {};
    expect(extractReferenceRaw(p, s, context)["cluster.saturation"].value).toBe(0);
    p.compete.academies_by_field = null;
    expect(extractReferenceRaw(p, s, context)["cluster.saturation"].value).toBeNull();
  });
  it("uses 2000m only with both verified spatial coverage and source availability", () => {
    const p = inputs(), s = inputs(1000);
    p.transit.nearest_subway_m = null;
    expect(extractReferenceRaw(p, s, context)["transit.nearest_subway_m"].value).toBe(2000);
    for (const inside_seoul of [false, null])
      expect(extractReferenceRaw(p, s, { inside_seoul })["transit.nearest_subway_m"].value).toBeNull();
    p.meta.sources.subway_positions.available = false;
    expect(extractReferenceRaw(p, s, context)["transit.nearest_subway_m"].value).toBeNull();
  });
  it("rejects unsupported radii, missing keys, nonfinite and wrong schema", () => {
    expect(() => extractReferenceRaw(inputs(500), inputs(1000), context)).toThrow();
    expect(() => extractReferenceRaw(inputs(), inputs(), context)).toThrow();
    const p = inputs();
    p.meta.schema_version = "1.1";
    expect(() => parseReferenceInputs(p)).toThrow();
    p.meta.schema_version = "1.3";
    p.demand.pop_5_9 = Infinity;
    expect(() => parseReferenceInputs(p)).toThrow();
    expect(() => parseReferenceInputs({})).toThrow();
  });
});
