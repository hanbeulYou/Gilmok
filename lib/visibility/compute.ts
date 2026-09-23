import { blocks, bounds, covers, nearestBoundary, overlaps } from './geometry.ts';
import { generateSamples } from './samples.ts';
import { FOOTPRINT_MISSING } from './types.ts';
import type { SampleResult, SampleSummary, VisibilityResult, VisibilityScene, XY } from './types.ts';
function validate(scene: VisibilityScene): void {
  const point = (p: XY) => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite);
  if (scene.schema_version !== '0.1' || scene.srid !== 5186 || scene.units !== 'm' || scene.radius_m !== 1000 ||
    !point(scene.candidate) || !Number.isInteger(scene.floor) || scene.floor === 0 || scene.floor < -100 || scene.floor > 200)
    throw new Error('Invalid visibility scene coordinate contract/floor');
  if (!Number.isFinite(scene.candidate_wgs84.lat) || !Number.isFinite(scene.candidate_wgs84.lng)) throw new Error('Invalid candidate identity');
  const ids = new Set<string>();
  for (const b of scene.buildings) {
    if (!b.id || ids.has(b.id) || !Number.isFinite(b.height_m) || b.height_m <= 0 ||
      !['source', 'floors_estimate', 'unknown'].includes(b.height_source) ||
      (b.height_source === 'unknown' && (b.height_m !== 4 || !b.estimated)) || !b.polygons.length)
      throw new Error('Invalid visibility building identity/height');
    ids.add(b.id);
    for (const polygon of b.polygons) {
      if (!polygon.length) throw new Error('Empty visibility polygon');
      for (const ring of polygon) if (ring.length < 4 || !ring.every(point) ||
        ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1])
        throw new Error('Invalid visibility polygon ring');
    }
  }
  const candidate = scene.buildings.find(b => b.id === scene.candidate_building_id);
  if (!Number.isInteger(scene.containing_building_count) || scene.containing_building_count < 0 ||
    (scene.candidate_building_id !== null && (scene.containing_building_count !== 1 ||
      !candidate || !covers(candidate.polygons, scene.candidate))))
    throw new Error('Candidate footprint identity mismatch');
  if (scene.candidate_building_id === null && scene.containing_building_count === 1)
    throw new Error('Candidate footprint unexpectedly missing');
  for (const a of [...(scene.station ? [scene.station] : []), ...scene.schools])
    if (!a.id || !point(a.point) || !Number.isFinite(a.distance_m) || a.distance_m < 0) throw new Error('Invalid visibility anchor');
}
const emptySummary = (): SampleSummary => ({ generated: 0, excluded: 0, visible: 0, blocked: 0, total_weight: 0, visible_weight: 0 });
/** Pure and deterministic. Worker/Node adapters own IO and timing. */
export function computeVisibility(scene: VisibilityScene): VisibilityResult {
  validate(scene);
  const summary = { all: emptySummary(), ring: emptySummary(), station: emptySummary(), school: emptySummary() };
  const samples: SampleResult[] = [], notes: string[] = [];
  const targetZ = (scene.floor - 1) * 3.3 + 2;
  const evidence = { values: { srid: 5186, radius_m: 1000, eye_height_m: 1.5, target_height_m: targetZ,
    target_height_estimated: true,
    candidate_wgs84: { ...scene.candidate_wgs84 }, floor: scene.floor,
    candidate_building_id: scene.candidate_building_id, containing_building_count: scene.containing_building_count,
    building_count: scene.buildings.length, unknown_count: scene.buildings.filter(b => b.height_source === 'unknown').length,
    wfs_count: scene.buildings.filter(b => b.source === 'vworld_wfs_supplement').length,
    estimated: true, // Target height is the specified floor-based estimate, not a survey.
    estimated_building_count: scene.buildings.filter(b => b.estimated).length,
    station: scene.station ? structuredClone(scene.station) : null, schools: structuredClone(scene.schools),
    sources: structuredClone(scene.sources), coverage: { ...scene.coverage }, summary }, notes };
  const missing = ['building_shp', 'building_wfs', 'subway_positions', 'schools'].filter(k => !scene.sources[k]?.available);
  if (missing.length) return { status: 'missing', reason: 'visibility_sources_missing:' + missing.join(','), evidence, samples, summary };
  if (!scene.coverage.query_within_loaded_region) notes.push('building_query_extends_beyond_loaded_region');
  if (scene.station && scene.station.distance_m > scene.radius_m) notes.push('station_path_extends_beyond_building_radius');
  if (!scene.station) notes.push('no_station_within_2km');
  if (!scene.schools.length) notes.push('no_located_school_within_1km');
  notes.push('straight_paths_from_representative_points_not_walk_routes', 'flat_ground_no_terrain_model');
  const prepared = scene.buildings.map(b => ({ ...b, bounds: bounds(b.polygons) }));
  const candidate = prepared.find(b => b.id === scene.candidate_building_id);
  for (const sample of generateSamples(scene)) {
    const containing = prepared.find(b => overlaps(b.bounds, sample.point) && covers(b.polygons, sample.point));
    let result: SampleResult;
    if (containing) result = { ...sample, status: 'excluded', target: null, building_id: containing.id };
    else {
      const target = candidate ? nearestBoundary(candidate.polygons, sample.point) : scene.candidate;
      const blocker = prepared.find(b => b.id !== scene.candidate_building_id && overlaps(b.bounds, sample.point, target) &&
        blocks(b.polygons, b.height_m, sample.point, target, 1.5, targetZ));
      result = { ...sample, status: blocker ? 'blocked' : 'visible', target, building_id: blocker?.id ?? null };
    }
    samples.push(result);
    for (const s of [summary.all, summary[sample.group]]) {
      s.generated++; s[result.status]++;
      if (result.status !== 'excluded') s.total_weight += sample.weight;
      if (result.status === 'visible') s.visible_weight += sample.weight;
    }
  }
  if (summary.all.total_weight === 0) return { status: 'missing', reason: 'no_valid_samples', evidence, samples, summary };
  if (scene.candidate_building_id === null) notes.push(FOOTPRINT_MISSING);
  return { status: 'ready', visible_ratio: summary.all.visible_weight / summary.all.total_weight, evidence, samples, summary };
}
