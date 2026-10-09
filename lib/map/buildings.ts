import type { FeatureCollection, MultiPolygon, Geometry } from 'geojson';
import type { VisibilityBuilding, VisibilityScene } from '../visibility/types';

export interface GeometryItem { id: string; geometry: Geometry }
export interface BuildingProperties extends Record<string, unknown> {
  id: string; height_m: number; height_source: VisibilityBuilding['height_source'];
  estimated: boolean; source: string; source_version: string; candidate: boolean;
}
export type BuildingCollection = FeatureCollection<MultiPolygon, BuildingProperties>;
export function geometryItems(scene: VisibilityScene): GeometryItem[] {
  return scene.buildings.map(building => ({ id: building.id, geometry: { type: 'MultiPolygon',
    coordinates: building.polygons.map(polygon => polygon.map(ring => ring.map(([x, y]) => [x, y]))) } }));
}
export function buildingCollection(scene: VisibilityScene, projected: GeometryItem[]): BuildingCollection {
  if (projected.length !== scene.buildings.length) throw new Error('변환된 건물 수가 채점 자료와 다릅니다.');
  return { type: 'FeatureCollection', features: scene.buildings.map((building, i) => {
    const item = projected[i];
    if (item.id !== building.id || item.geometry.type !== 'MultiPolygon') throw new Error('변환된 건물 식별자를 확인하지 못했습니다.');
    return { type: 'Feature', id: building.id, geometry: item.geometry,
      properties: { id: building.id, height_m: building.height_m, height_source: building.height_source,
        estimated: building.estimated, source: building.source, source_version: building.source_version,
        candidate: building.id === scene.candidate_building_id } };
  }) };
}
export function heightLabel(building: VisibilityBuilding) {
  if (building.height_source === 'unknown') return `높이 미상 · 표시/차폐 ${building.height_m}m 가정`;
  return `${building.height_source === 'floors_estimate' ? '추정 높이' : '원천 높이'} ${building.height_m}m${building.height_source === 'floors_estimate' ? ' (층수 기반)' : ''}`;
}
export function buildingCoverage(scene: VisibilityScene, inSeoul?: boolean) {
  const notes: string[] = [];
  if (inSeoul === false) notes.push('서울 밖 지역입니다. 적재된 건물 자료를 확인할 수 없습니다.');
  if (!scene.sources.building_shp?.available && !scene.sources.building_wfs?.available) notes.push('건물 원천 자료가 아직 적재되지 않았습니다.');
  if (!scene.coverage.query_within_loaded_region) notes.push('주변 반경 일부의 건물 자료가 없습니다.');
  if (scene.coverage.score_ring_within_loaded_region !== true) notes.push('건물 자료 범위 밖 — 노출 평가 불가');
  if (!scene.buildings.length) notes.push(scene.coverage.query_within_loaded_region && scene.sources.building_shp?.available
    ? '적재 범위 안에서 조회된 건물은 0개입니다.' : '표시할 건물 자료가 없습니다. 건물이 없다는 뜻은 아닙니다.');
  return notes;
}

/** Exact geometry/source identity, no score or personal data. At most two scenes and one RPC. */
export function createBuildingProjectionLoader(fetcher: (items: GeometryItem[], signal: AbortSignal) => Promise<GeometryItem[]>) {
  const cache = new Map<string, GeometryItem[]>();
  let queue: Promise<unknown> = Promise.resolve(), wanted = '', controller: AbortController | undefined;
  return {
    load(scene: VisibilityScene) {
      const items = geometryItems(scene), key = JSON.stringify([scene.candidate, scene.sources, items]);
      if (wanted !== key) controller?.abort();
      wanted = key;
      const job = queue.catch(() => undefined).then(async () => {
        if (wanted !== key) throw new DOMException('Selection changed', 'AbortError');
        let projected = cache.get(key);
        if (!projected) {
          controller = new AbortController();
          const signal = controller.signal, timer = setTimeout(() => controller?.abort(), 15000);
          try {
            projected = items.length ? await fetcher(items, signal) : [];
            signal.throwIfAborted();
            if (wanted !== key) throw new DOMException('Selection changed', 'AbortError');
            buildingCollection(scene, projected); // Never cache incomplete/misordered responses.
            cache.set(key, projected);
            if (cache.size > 2) cache.delete(cache.keys().next().value!);
          } finally { clearTimeout(timer); controller = undefined; }
        } else {
          cache.delete(key); cache.set(key, projected);
        }
        return buildingCollection(scene, projected);
      });
      queue = job;
      return job;
    },
    cancel() { wanted = ''; controller?.abort(); },
    dispose() { wanted = ''; controller?.abort(); cache.clear(); },
  };
}
