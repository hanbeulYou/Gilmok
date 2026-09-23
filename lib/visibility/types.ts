/** All XY coordinates are EPSG:5186 metres, including holes and multi-polygons. */
export type XY = readonly [number, number];
export type Ring = readonly XY[];
export type Polygon = readonly Ring[];
export type Footprint = readonly Polygon[];
export interface VisibilityBuilding {
  id: string; polygons: Footprint; height_m: number;
  height_source: 'source' | 'floors_estimate' | 'unknown';
  estimated: boolean; source: string; source_version: string;
}
export interface Anchor {
  id: string; name: string; point: XY; distance_m: number;
  line?: string | null; level?: string;
}
export interface VisibilityScene {
  schema_version: '0.1'; srid: 5186; units: 'm'; radius_m: 1000;
  candidate: XY; candidate_wgs84: { lat: number; lng: number }; floor: number;
  candidate_building_id: string | null; containing_building_count: number;
  buildings: readonly VisibilityBuilding[];
  station: Anchor | null; schools: readonly Anchor[];
  sources: Readonly<Record<string, { available: boolean; [key: string]: unknown } | null>>;
  coverage: { building_region: string; query_within_loaded_region: boolean };
}
export interface VisibilitySample {
  id: string; group: 'ring' | 'station' | 'school'; point: XY; weight: number;
  bearing_deg?: number; radius_m?: number; anchor_id?: string; step?: number;
}
export interface SampleResult extends VisibilitySample {
  status: 'visible' | 'blocked' | 'excluded';
  target: XY | null; building_id: string | null;
}
export interface SampleSummary {
  generated: number; excluded: number; visible: number; blocked: number;
  total_weight: number; visible_weight: number;
}
export interface VisibilityEvidence {
  values: Record<string, unknown>;
  notes: readonly string[];
}
export type VisibilityResult = {
  status: 'ready'; visible_ratio: number; evidence: VisibilityEvidence;
  samples: SampleResult[]; summary: Record<'all' | 'ring' | 'station' | 'school', SampleSummary>;
} | { status: 'missing'; reason: string; evidence: VisibilityEvidence;
  samples: SampleResult[]; summary: Record<'all' | 'ring' | 'station' | 'school', SampleSummary> };
export const FOOTPRINT_MISSING = 'candidate_footprint_missing_self_occlusion_unaccounted';
export interface VisibilityRequest { requestId: string; scene: VisibilityScene }
export type VisibilityResponse = { requestId: string; result: VisibilityResult; computeMs: number } |
  { requestId: string; error: string };
