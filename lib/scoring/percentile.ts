import type { ReferenceKey } from './raw.ts';
import type { Evidence, ScoreInputs, ScoreReference, ScoringPreset } from './types.ts';

/** Exact IEEE equality, 1-based average rank for ties; strict-less for unseen values. */
export function percentile(values: readonly number[], value: number | null, direction: 1 | -1 = 1): number | null {
  if (value === null || values.length === 0) return null;
  if (!Number.isFinite(value) || values.some(v => !Number.isFinite(v)))
    throw new Error('Nonfinite percentile input');
  const sorted = [...values].sort((a, b) => a - b);
  const bound = (upper: boolean) => {
    let lo = 0, hi = sorted.length;
    while (lo < hi) {
      const mid = Math.floor((lo + hi) / 2);
      if (sorted[mid] < value || (upper && sorted[mid] === value)) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  };
  const less = bound(false), equal = bound(true) - less;
  const p = 100 * (equal ? less + (equal + 1) / 2 : less) / sorted.length;
  return direction === -1 ? 100 - p : p;
}
const sources: Record<ReferenceKey, readonly string[]> = {
  demand: ['resident_population', 'admin_boundaries', 'schools'],
  flow: ['living_population', 'population_grid'],
  'transit.nearest_subway_m': ['subway_positions'],
  'transit.subway_boardings_golden': ['subway_positions', 'transit_counts'],
  'transit.bus_stops': ['bus_positions'], cluster: ['academies'],
  'cluster.saturation': ['academies', 'resident_population', 'admin_boundaries'],
  'environment.stores_total': ['stores'],
};
function canonical(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') return '{' + Object.entries(value)
    .sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => JSON.stringify(k) + ':' + canonical(v)).join(',') + '}';
  return JSON.stringify(value) ?? 'undefined';
}
export interface ReferenceValue {
  value: number | null; reason: string | null; reference: Evidence['reference'];
}
export function referencePercentile(key: ReferenceKey, raw: number | null,
  primary: ScoreInputs, school: ScoreInputs, preset: ScoringPreset,
  reference: ScoreReference | null, direction: 1 | -1 = 1): ReferenceValue {
  const fail = (reason: string): ReferenceValue => ({ value: null, reason, reference: null });
  if (reference === null) return fail('reference_missing');
  if (reference.preset.id !== preset.id || reference.preset.version !== preset.reference_version)
    return fail('reference_preset_version_mismatch');
  if (reference.inputs_schema_version !== preset.schema_version)
    return fail('reference_schema_version_mismatch');
  const distribution = reference.distributions.filter(d => d.key === key && d.radius_m === primary.meta.radius_m);
  if (distribution.length !== 1) return fail('reference_radius_or_key_missing');
  for (const sourceKey of sources[key]) {
    const expected = reference.sources[sourceKey];
    const actual = (sourceKey === 'schools' ? school : primary).meta.sources[sourceKey];
    const members = Array.isArray(expected) ? expected : [expected];
    if (!actual || !expected || !members.some(member => canonical(member) === canonical(actual)))
      return fail('reference_source_mismatch:' + sourceKey);
  }
  const d = distribution[0];
  if (!Number.isSafeInteger(d.cell_count) || d.cell_count <= 0 || d.values.length > d.cell_count ||
    d.values.some(v => !Number.isFinite(v) || v < 0)) return fail('invalid_reference_distribution');
  const info = { population_size: d.values.length, coverage: d.values.length / d.cell_count };
  return { value: percentile(d.values, raw, direction), reason: raw === null ? 'raw_missing' :
    d.values.length === 0 ? 'reference_empty' : null, reference: info };
}
