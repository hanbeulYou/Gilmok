import type { ComparisonCandidate } from '../compare/store';
import type { FeatureCollection, Point, Polygon } from 'geojson';

export interface MapProperties { kind: 'radius' | 'station' | 'school'; radius_m?: number; purpose?: string;
  source_id?: string; name?: string; line?: string; level?: 'elem' | 'mid' | 'high'; distance_m?: number; estimated?: boolean }
export interface MapSource { available: boolean; source_versions: string[]; sources: string[]; latest_ingested_at: string | null; unlocated_count: number }
export interface MapContext { schema_version: '1.0'; center: [number, number]; collection: FeatureCollection<Point | Polygon, MapProperties>;
  meta: { covered: boolean; crs: 'EPSG:4326'; sources: { transit_stops: MapSource; schools: MapSource } } }
export interface CandidateGroup { key: string; coordinate: [number, number]; members: { id: string; alias: string; floor: number; rank: number }[] }

/** Keep exact scoring coordinates. Different floors at the same point never get jittered. */
export function groupCandidates(rows: readonly ComparisonCandidate[]): CandidateGroup[] {
  const groups = new Map<string, CandidateGroup>();
  rows.forEach((row, index) => {
    const coordinate: [number, number] = [row.candidate.lng, row.candidate.lat];
    const key = JSON.stringify(coordinate);
    const group = groups.get(key) ?? { key, coordinate, members: [] };
    group.members.push({ id: row.id, alias: row.alias, floor: row.candidate.floor, rank: index + 1 });
    groups.set(key, group);
  });
  return [...groups.values()];
}

export function mapSourceFingerprint(row: ComparisonCandidate): string {
  const sources = row.inputs?.primary?.meta.sources;
  return JSON.stringify(['admin_boundaries', 'subway_positions', 'schools'].map(key => sources?.[key] ?? null));
}

export function contextSummary(context: MapContext): string {
  if (!context.meta.covered) return '서울 밖 지역으로 역·학교 자료를 제공하지 않습니다.';
  const { transit_stops: transit, schools } = context.meta.sources;
  const count = (kind: string) => context.collection.features.filter(f => f.properties.kind === kind).length;
  const stations = transit.available ? `역 ${count('station')}곳 (1.2km)` : '역 자료를 불러오지 못함';
  const school = schools.available ? `학교 ${count('school')}곳 (1km)` : '학교 자료를 불러오지 못함';
  return `${stations} · ${school}${schools.unlocated_count ? ` · 원천 전체 학교 좌표 미상 ${schools.unlocated_count}곳(반경 내 여부 미확인)` : ''}`;
}
