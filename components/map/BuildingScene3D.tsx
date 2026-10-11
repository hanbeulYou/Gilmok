'use client';
import { useEffect, useMemo, useState } from 'react';
import type { Map as LibreMap, MapLayerMouseEvent } from 'maplibre-gl';
import type { ComparisonCandidate } from '../../lib/compare/store';
import { getSupabaseClient } from '../../lib/supabase/client';
import { ensureSession } from '../../lib/supabase/session';
import { buildingCoverage, createBuildingProjectionLoader, heightLabel, type GeometryItem, type BuildingCollection } from '../../lib/map/buildings';
import { EXPOSURE_LIMITATION } from '../../lib/visibility/types';
import './building-3d.css';

const source = 'scored-buildings', layer = 'scored-buildings-3d';
const attribution = '<a href="https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?svcCde=NA&dsId=18" target="_blank" rel="noopener noreferrer">건물: 국토교통부 GIS건물통합정보(CC BY)</a> · Vworld WFS 보조';
export interface BuildingSceneProps {
  map: LibreMap; active: boolean; selected?: ComparisonCandidate; candidateIds: string;
  inSeoul?: boolean; exit: () => void;
}
export default function BuildingScene3D({ map, active, selected, candidateIds, inSeoul, exit }: BuildingSceneProps) {
  const scene = selected?.inputs?.scene;
  const [data, setData] = useState<BuildingCollection | null>(null), [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0), [clicked, setClicked] = useState<string | null>(null);
  const loader = useMemo(() => createBuildingProjectionLoader(async (items, signal) => {
    await ensureSession(); signal.throwIfAborted();
    const { data, error } = await getSupabaseClient().rpc('project_exposure_geometry', { items }).abortSignal(signal);
    if (error || !Array.isArray(data)) throw new Error('건물 좌표를 변환하지 못했습니다. 잠시 후 다시 시도해 주세요.');
    return data as GeometryItem[];
  }), []);
  useEffect(() => () => loader.dispose(), [loader]);
  useEffect(() => {
    let owner: string | null | undefined;
    const { data: auth } = getSupabaseClient().auth.onAuthStateChange((_event, session) => {
      const next = session?.user.id ?? null;
      if (owner !== undefined && owner !== next) { loader.dispose(); setData(null); setClicked(null); }
      owner = next;
    });
    return () => { auth.subscription.unsubscribe(); };
  }, [loader]);
  useEffect(() => { loader.dispose(); }, [candidateIds, loader]);
  useEffect(() => {
    setData(null); setClicked(null); setError('');
    if (!active || !scene) { loader.cancel(); return; }
    if (!map.getCanvas().getContext('webgl2')) { setError('3D를 지원하는 WebGL2를 사용할 수 없습니다. 2D 지도는 계속 사용할 수 있습니다.'); return; }
    let alive = true;
    void loader.load(scene).then(value => { if (alive) setData(value); }, cause => {
      if (alive && cause?.name !== 'AbortError') setError(cause instanceof Error ? cause.message : '건물 3D 자료를 표시하지 못했습니다.');
    });
    return () => { alive = false; };
  }, [scene, selected?.id, selected?.generation, active, attempt, map, loader, candidateIds]);
  useEffect(() => {
    if (!active || !data) return;
    map.addSource(source, { type: 'geojson', data, attribution, tolerance:0, promoteId:'id' });
    map.addLayer({ id: layer, type: 'fill-extrusion', source, paint: {
      'fill-extrusion-height': ['get', 'height_m'], 'fill-extrusion-base': 0,
      'fill-extrusion-color': ['case', ['get', 'candidate'], '#b57921', ['match', ['get', 'height_source'],
        'floors_estimate', '#b8946d', 'unknown', '#867b9c', '#829b9e']],
      'fill-extrusion-opacity': 0.9, 'fill-extrusion-vertical-gradient': true,
    } }, 'station-points');
    const click = (event: MapLayerMouseEvent) => { setClicked(String(event.features?.[0]?.id ?? '')); };
    map.on('click', layer, click);
    return () => {
      map.off('click', layer, click);
      if (map.getLayer(layer)) map.removeLayer(layer);
      if (map.getSource(source)) map.removeSource(source);
    };
  }, [map, active, data]);
  if (!active) return null;
  const building = scene?.buildings.find(value => value.id === (clicked ?? scene.candidate_building_id));
  return <section className="building-3d-status" data-testid="building-3d" data-state={error ? 'error' : data ? 'ready' : scene ? 'loading' : 'waiting'}
    data-building-count={data?.features.length ?? 0} aria-label="건물 3D 자료">
    <p>건물 3D 자료: 강남구 적재분</p>
    {scene && buildingCoverage(scene,inSeoul).map(note => <p key={note}>{note}</p>)}
    {!scene && <p role="status">채점의 건물 자료를 기다리는 중입니다.</p>}
    {scene && !data && !error && <p role="status">건물 3D를 준비하는 중입니다.</p>}
    {error && <p role="alert">{error} <button onClick={() => setAttempt(value => value + 1)}>3D 다시 시도</button> <button onClick={exit}>2D로 돌아가기</button></p>}
    {data && <><p className="building-3d-legend"><span>원천 높이</span><span>층수 기반 추정</span><span>미상 · 4m 가정</span><span>선택 후보</span></p>
      <p>채점 장면 건물 {data.features.length.toLocaleString()}개 · 원천 {scene!.buildings.filter(b => b.height_source === 'source').length}개 · 추정 {scene!.buildings.filter(b => b.height_source === 'floors_estimate').length}개 · 미상 {scene!.buildings.filter(b => b.height_source === 'unknown').length}개</p>
      <button onClick={() => setClicked(null)}>선택 후보 건물 정보</button>
      {building ? <p data-testid="building-height" data-estimated={String(building.estimated)}>{heightLabel(building)} · 추정값 {building.estimated ? '예' : '아니오'} · {building.source.includes('wfs') ? 'Vworld WFS' : 'GIS건물통합정보'} · 기준 {building.source_version}</p>
        : <p>후보 도형 없음 · 자기 건물 차폐 미반영</p>}</>}
    <p>{EXPOSURE_LIMITATION}</p>
  </section>;
}
