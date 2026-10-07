'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import maplibregl, { type GeoJSONSource, type Map as LibreMap, type StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import './map.css';
import { useComparisonStore } from '../../lib/compare/store';
import { getSupabaseClient } from '../../lib/supabase/client';
import { ensureSession } from '../../lib/supabase/session';
import { createMapContextLoader } from '../../lib/map/context';
import { contextSummary, groupCandidates, mapSourceFingerprint, type MapContext } from '../../lib/map/features';

const styleUrl = process.env.NEXT_PUBLIC_MAP_STYLE_URL;
const credits = '<a href="https://openfreemap.org/" target="_blank" rel="noopener noreferrer">OpenFreeMap</a> · '
  + '<a href="https://openmaptiles.org/" target="_blank" rel="noopener noreferrer">© OpenMapTiles</a> · '
  + '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a>';
function openStyle(_previous: StyleSpecification | undefined, style: StyleSpecification): StyleSpecification {
  const sources = { ...style.sources };
  if (sources.openmaptiles?.type === 'vector') sources.openmaptiles = { ...sources.openmaptiles, attribution: credits };
  return { ...style, sources, layers: style.layers.filter(layer => layer.type !== 'fill-extrusion').map(layer => {
    if (layer.type === 'symbol' && /name/.test(JSON.stringify(layer.layout?.['text-field'])))
      return { ...layer, layout: { ...layer.layout, ...(/poi/i.test(layer.id) ? { visibility: 'none' as const } : {}),
        'text-field': ['coalesce', ['get', 'name:ko'], ['get', 'name'], ['get', 'name:latin']] } };
    if (layer.type === 'background') return { ...layer, paint: { ...layer.paint, 'background-color': '#f3f2ef' } };
    if (layer.type === 'fill' && layer.id === 'water') return { ...layer, paint: { ...layer.paint, 'fill-color': '#dce8ea' } };
    return layer;
  }) } as StyleSpecification;
}

export default function CompareMap({ retry }: { retry: () => void }) {
  const state = useComparisonStore(), host = useRef<HTMLDivElement>(null), map = useRef<LibreMap | null>(null);
  const [ready, setReady] = useState(false), [mapError, setMapError] = useState(''), [contextError, setContextError] = useState('');
  const [context, setContext] = useState<MapContext | null>(null), [loading, setLoading] = useState(false), [attempt, setAttempt] = useState(0);
  const [groupKey, setGroupKey] = useState<string | null>(null);
  const rows = useMemo(() => state.order.flatMap(id => state.candidates.filter(row => row.id === id)), [state.order, state.candidates]);
  const groups = useMemo(() => groupCandidates(rows), [rows]);
  const selected = rows.find(row => row.id === state.selectedId) ?? rows[0];
  const initial = useRef(selected?.candidate);
  const initialGroups = useRef(groups);
  const fittedCenter = useRef('');
  const lat = selected?.candidate.lat, lng = selected?.candidate.lng;
  const fingerprint = selected ? mapSourceFingerprint(selected) : '';
  const scoringFinished = selected && ['scored', 'scored_provisional', 'error'].includes(selected.stage) && !selected.refreshing;
  const loader = useMemo(() => createMapContextLoader(async (lat, lng, signal) => {
    await ensureSession();
    const { data, error } = await getSupabaseClient().rpc('compare_map_context', { lat, lng }).abortSignal(signal);
    if (error || !data) throw new Error('역·학교·반경 자료를 불러오지 못했습니다.');
    return data as MapContext;
  }), []);
  useEffect(() => () => loader.dispose(), [loader]);
  useEffect(() => {
    if (!styleUrl || lat === undefined || lng === undefined || !scoringFinished) { setContext(null); return; }
    let active = true; setContext(null); setLoading(true); setContextError('');
    void loader.load(lat, lng, fingerprint).then(value => { if (active) setContext(value); }, error => {
      if (active) setContextError(error instanceof Error && error.name !== 'AbortError' ? error.message : '지도 자료 조회를 다시 시도해 주세요.');
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [lat, lng, scoringFinished, fingerprint, attempt, loader]);

  useEffect(() => {
    if (!host.current || !initial.current || !styleUrl) return;
    let instance: LibreMap;
    try {
      instance = new maplibregl.Map({ container: host.current,
        center: [initial.current.lng, initial.current.lat], zoom: 14, pitch: 0, maxPitch: 0,
        dragRotate: false, touchPitch: false, attributionControl: false, cooperativeGestures: true });
    } catch { setMapError('이 브라우저에서 지도를 열 수 없습니다.'); return; }
    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    instance.addControl(new maplibregl.AttributionControl({ compact: false, customAttribution: credits }), 'bottom-right');
    const timeout = setTimeout(() => { if (!instance.loaded()) setMapError('지도 타일을 불러오지 못했습니다.'); }, 15000);
    instance.on('error', () => setMapError('일부 지도 타일을 불러오지 못했습니다.'));
    instance.on('idle', () => { clearTimeout(timeout); if (host.current) host.current.dataset.mapIdle = 'true'; });
    instance.on('load', () => {
      clearTimeout(timeout);
      instance.addSource('comparison-context', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      instance.addLayer({ id: 'primary-radius', type: 'fill', source: 'comparison-context', filter: ['==', ['get', 'radius_m'], 800], paint: { 'fill-color': '#0f766e', 'fill-opacity': 0.07 } });
      instance.addLayer({ id: 'radius-lines', type: 'line', source: 'comparison-context', filter: ['==', ['get', 'kind'], 'radius'], paint: { 'line-color': ['match', ['get', 'radius_m'], 800, '#0f766e', '#657b86'], 'line-width': 2, 'line-dasharray': [3, 2] } });
      instance.addLayer({ id: 'station-points', type: 'circle', source: 'comparison-context', filter: ['==', ['get', 'kind'], 'station'], paint: { 'circle-color': '#235897', 'circle-radius': 7, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 } });
      instance.addLayer({ id: 'school-points', type: 'circle', source: 'comparison-context', filter: ['==', ['get', 'kind'], 'school'], paint: { 'circle-color': ['match', ['get', 'level'], 'elem', '#87601b', 'mid', '#526735', '#775d91'], 'circle-radius': 8, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 } });
      for (const layer of ['station-points', 'school-points']) {
        instance.on('click', layer, event => {
          const feature = event.features?.[0]; if (!feature || feature.geometry.type !== 'Point') return;
          const label = document.createElement('span'); label.textContent = `${feature.properties.name}${feature.properties.line ? ` · ${feature.properties.line}` : ''}${feature.properties.estimated ? ' · 추정 위치' : ''}`;
          new maplibregl.Popup().setLngLat(feature.geometry.coordinates as [number, number]).setDOMContent(label).addTo(instance);
        });
      }
      const bounds = new maplibregl.LngLatBounds(); initialGroups.current.forEach(group => bounds.extend(group.coordinate));
      if (!bounds.isEmpty()) instance.fitBounds(bounds, { padding: 64, maxZoom: 15, duration: 0 });
      setReady(true);
    });
    instance.setStyle(styleUrl, { transformStyle: openStyle });
    const resize = new ResizeObserver(() => instance.resize()); resize.observe(host.current);
    return () => { clearTimeout(timeout); resize.disconnect(); instance.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const instance = map.current; if (!instance) return;
    const markers = groups.map(group => {
      const element = document.createElement('button'); element.type = 'button'; element.className = 'map-candidate';
      element.textContent = group.members.length > 1 ? `${group.members.length}곳` : String(group.members[0].rank);
      const label = group.members.length > 1 ? `같은 좌표 후보 ${group.members.length}곳` : `${group.members[0].rank}위 ${group.members[0].alias} ${group.members[0].floor}층`;
      element.setAttribute('aria-pressed', String(group.members.some(member => member.id === selected?.id)));
      element.dataset.coordinate = JSON.stringify(group.coordinate); element.dataset.candidateIds = JSON.stringify(group.members.map(member => member.id));
      element.onclick = () => { if (group.members.length > 1) setGroupKey(group.key); else state.selectCandidate(group.members[0].id); };
      const marker = new maplibregl.Marker({ element, anchor: 'center' }).setLngLat(group.coordinate).addTo(instance);
      element.setAttribute('aria-label', label); // MapLibre 4 replaces the label in addTo().
      return marker;
    });
    return () => { markers.forEach(marker => marker.remove()); };
  }, [groups, selected?.id, state.selectCandidate]);
  useEffect(() => {
    if (ready && lat !== undefined && lng !== undefined) map.current?.easeTo({ center: [lng, lat], zoom: 14,
      duration: matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 450 });
  }, [ready, lat, lng]);
  useEffect(() => {
    if (ready) (map.current?.getSource('comparison-context') as GeoJSONSource | undefined)?.setData(context?.collection ?? { type: 'FeatureCollection', features: [] });
    const ring = context?.collection.features.find(feature => feature.properties.radius_m === 1000);
    if (ready && context && ring?.geometry.type === 'Polygon' && fittedCenter.current !== JSON.stringify(context.center)) {
      const bounds = new maplibregl.LngLatBounds(); ring.geometry.coordinates[0].forEach(point => bounds.extend(point as [number, number]));
      map.current?.fitBounds(bounds, { padding: 24, maxZoom: 15, duration: 0 });
      fittedCenter.current = JSON.stringify(context.center);
    }
  }, [ready, context]);
  useEffect(() => {
    const instance = map.current; if (!instance || !context) return;
    const markers = context.collection.features.flatMap(feature => {
      if (feature.properties.kind !== 'school' || feature.geometry.type !== 'Point') return [];
      const element = document.createElement('span'); element.className = 'map-school-icon';
      element.textContent = { elem: '초', mid: '중', high: '고' }[feature.properties.level!];
      const marker = new maplibregl.Marker({ element, anchor: 'center' }).setLngLat(feature.geometry.coordinates as [number, number]).addTo(instance);
      element.setAttribute('aria-label', `${feature.properties.name} ${element.textContent}`);
      return [marker];
    });
    return () => { markers.forEach(marker => marker.remove()); };
  }, [context, ready]);

  if (!styleUrl) return <p role="status">지도 설정을 준비 중입니다. 후보 점수와 근거는 계속 확인할 수 있습니다.</p>;
  const group = groups.find(value => value.key === groupKey);
  return <>
    <div className="map-candidate-list" aria-label="지도 후보">{rows.map((row, index) => <button key={row.id} aria-pressed={row.id === selected?.id}
      onClick={() => state.selectCandidate(row.id)}>{index + 1}. {row.alias} · {row.candidate.floor}층</button>)}</div>
    {group && <div className="map-floor-list" role="group" aria-label="같은 좌표 후보 층 목록">{group.members.map(member => <button key={member.id}
      onClick={() => { state.selectCandidate(member.id); setGroupKey(null); }}>{member.rank}. {member.alias} · {member.floor}층</button>)}<button onClick={() => setGroupKey(null)}>목록 닫기</button></div>}
    <div ref={host} className="map-canvas" data-testid="compare-map" aria-label="후보와 주변 역·학교 지도"/>
    {mapError && <p role="alert">{mapError} <button onClick={retry}>지도 다시 시도</button></p>}
    <p className="map-legend">초록 영역 800m · 바깥 점선 1km · 파랑 역 · 초/중/고 학교</p>
    <p role="status" className="map-context-status">{context ? contextSummary(context) : contextError || (loading ? '반경·역·학교를 불러오는 중입니다.' : '채점 입력을 확인한 뒤 주변 자료를 표시합니다.')}
      {contextError && <button onClick={() => setAttempt(value => value + 1)}>주변 자료 다시 시도</button>}</p>
    {context && <small className="map-source-dates">역 기준 {context.meta.sources.transit_stops.source_versions.join(', ') || '미확인'} · 학교 기준 {context.meta.sources.schools.source_versions.join(', ') || '미확인'}</small>}
  </>;
}
