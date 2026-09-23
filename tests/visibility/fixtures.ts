import type { Footprint, VisibilityBuilding, VisibilityScene } from '../../lib/visibility/types.ts';
export const rectangle = (x1: number, y1: number, x2: number, y2: number): Footprint =>
  [[[[x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]]]];
export const building = (id: string, polygons: Footprint, height_m = 9): VisibilityBuilding =>
  ({ id, polygons, height_m, height_source: 'source', estimated: false, source: 'gis_buildings_shp', source_version: 'fixture' });
export const scene = (): VisibilityScene => ({ schema_version: '0.1', srid: 5186, units: 'm', radius_m: 1000,
  candidate: [0, 0], candidate_wgs84: { lat: 37.5, lng: 127.05 }, floor: 3, candidate_building_id: null,
  containing_building_count: 0, buildings: [], station: null, schools: [],
  sources: Object.fromEntries(['building_shp', 'building_wfs', 'subway_positions', 'schools'].map(k => [k, { available: true }])),
  coverage: { building_region: 'Gangnam-gu', query_within_loaded_region: true } });
