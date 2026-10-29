'use client';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Popup, type GeoJSONSource, type Map as LibreMap, type MapMouseEvent } from 'maplibre-gl';
import type { ComparisonCandidate } from '../../lib/compare/store';
import { academyViewportCounts, createAcademyLayerLoader, type AcademyLayer as Reply, type ReadyAcademyLayer } from '../../lib/map/academies';
import { academyRequest, academyUnavailable } from '../../lib/map/academy-view';
import { exposureHitAt } from '../../lib/map/picking';
import { ensureSession } from '../../lib/supabase/session';
import { getSupabaseClient } from '../../lib/supabase/client';
import './academy-layer.css';

const source = 'academy-institutions', circles = ['academy-other', 'academy-same'], layers = ['academy-review', ...circles];
const empty = { type: 'FeatureCollection' as const, features: [] };
type Institution = ReadyAcademyLayer['collection']['features'][number];
export default function AcademyLayer({ map, row, active }: { map: LibreMap; row?: ComparisonCandidate; active: boolean }) {
  const request = academyRequest(row), key = JSON.stringify([row?.id, row?.generation, request]);
  const [reply, setReply] = useState<{ key: string; value: Reply } | null>(null);
  const [zoomed, setZoomed] = useState(map.getZoom() >= 15), [error, setError] = useState(''), [attempt, retry] = useState(0);
  const [counts, setCounts] = useState<ReturnType<typeof academyViewportCounts> | null>(null);
  const [popup, setPopup] = useState<{ host: HTMLElement; features: Institution[] } | null>(null), [chosen, choose] = useState(0);
  const popupRef = useRef<Popup | null>(null), attempted = useRef(''), wanted = useRef(key);
  wanted.current = key;
  useLayoutEffect(() => {
    // MapLibre first anchors the empty host; remeasure after portal/selection rendering.
    const current = popupRef.current;
    if (popup && current) current.setLngLat(current.getLngLat());
  }, [popup, chosen]);
  const value = reply?.key === key ? reply.value : null;
  const loader = useMemo(() => createAcademyLayerLoader(async (args, signal) => {
    await ensureSession(); signal.throwIfAborted();
    const { data, error } = await getSupabaseClient().rpc('academy_layer', args).abortSignal(signal);
    if (error || !data) throw new Error('학원 자료를 불러오지 못했습니다. 다시 시도해 주세요.');
    return data;
  }), []);
  useEffect(() => {
    let owner: string | null | undefined;
    const { data } = getSupabaseClient().auth.onAuthStateChange((_event, session) => {
      const next = session?.user.id ?? null;
      if (owner !== undefined && owner !== next) { loader.dispose(); attempted.current = ''; setReply(null); setCounts(null); popupRef.current?.remove(); }
      owner = next;
    });
    return () => { data.subscription.unsubscribe(); loader.dispose(); };
  }, [loader]);
  useEffect(() => {
    attempted.current = ''; setError(''); setCounts(null); popupRef.current?.remove();
    return () => { loader.cancel(); popupRef.current?.remove(); };
  }, [key, loader]);
  useEffect(() => {
    const update = () => setZoomed(map.getZoom() >= 15);
    map.on('zoom', update); return () => { map.off('zoom', update); };
  }, [map]);
  // Zoom hiding never clears loaded data or cancels a completed/in-flight request.
  // A selection change cancels immediately, before the next selection's debounce.
  useEffect(() => {
    if (!active || !zoomed || !request || attempted.current === key) return;
    const timer = setTimeout(() => {
      attempted.current = key; setError('');
      void loader.load(request).then(result => {
        if (wanted.current === key) setReply({ key, value: result });
      }).catch(cause => {
        if (wanted.current === key) setError(cause instanceof Error ? cause.message : '학원 조회 실패');
      });
    }, 250);
    return () => clearTimeout(timer);
    // The serialized key includes all request fields.
  }, [key, active, zoomed, attempt, loader]);
  // Dispose layers before the parent's passive effect removes the MapLibre map.
  useLayoutEffect(() => {
    map.addSource(source, { type: 'geojson', data: empty, promoteId: 'academy_id' });
    map.addLayer({ id: layers[0], type: 'circle', source, minzoom: 15,
      filter: ['==', ['get', 'coordinate_verification_pending'], true],
      paint: { 'circle-radius': 7, 'circle-color': '#fff', 'circle-stroke-color': '#a45200', 'circle-stroke-width': 2 } }, 'station-points');
    map.addLayer({ id: circles[0], type: 'circle', source, minzoom: 15,
      paint: { 'circle-radius': 4, 'circle-color': '#b5a2c6', 'circle-opacity': 0.65 } }, 'station-points');
    map.addLayer({ id: circles[1], type: 'circle', source, minzoom: 15,
      paint: { 'circle-radius': 5, 'circle-color': '#522779', 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 } }, 'station-points');
    return () => { popupRef.current?.remove(); for (const layer of [...layers].reverse()) if (map.getLayer(layer)) map.removeLayer(layer); if (map.getSource(source)) map.removeSource(source); };
  }, [map]);
  useEffect(() => {
    // geojson-vt drops nonnumeric top-level IDs; promote the unchanged institution ID.
    const data = value?.status === 'ready' ? { ...value.collection, features: value.collection.features.map(f => ({ ...f, properties: { ...f.properties, academy_id: String(f.id) } })) } : empty;
    (map.getSource(source) as GeoJSONSource)?.setData(data);
    const field = value?.field ?? '';
    map.setFilter(circles[0], ['!=', ['get', 'field'], field]);
    map.setFilter(circles[1], ['==', ['get', 'field'], field]);
  }, [map, value]);
  useEffect(() => {
    for (const layer of layers) map.setLayoutProperty(layer, 'visibility', active && zoomed ? 'visible' : 'none');
    if (!active || !zoomed) popupRef.current?.remove();
  }, [map, active, zoomed]);
  useEffect(() => {
    if (value?.status !== 'ready') return;
    const update = () => {
      const next = academyViewportCounts(value, map.queryRenderedFeatures({ layers: circles }).map(f => String(f.id)));
      setCounts(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next);
    };
    update(); map.on('idle', update); map.on('moveend', update);
    return () => { map.off('idle', update); map.off('moveend', update); };
  }, [map, value, active, zoomed]);
  useEffect(() => {
    if (!active || !zoomed || value?.status !== 'ready') return;
    const click = (event: MapMouseEvent) => {
      if (exposureHitAt(map, event.point.x, event.point.y)) { popupRef.current?.remove(); return; }
      const hits = new Set(map.queryRenderedFeatures(event.point, { layers: circles }).map(f => String(f.id)));
      const features = value.collection.features.filter(f => hits.has(String(f.id)));
      if (!features.length) return;
      popupRef.current?.remove(); const host = document.createElement('div');
      const next = new Popup({ className: 'academy-map-popup', maxWidth: '280px', closeOnClick: true }).setLngLat(features[0].geometry.coordinates as [number, number]).setDOMContent(host).addTo(map);
      popupRef.current = next; choose(0); setPopup({ host, features });
      next.on('close', () => { if (popupRef.current === next) { popupRef.current = null; setPopup(null); } });
    };
    map.on('click', click); return () => { map.off('click', click); };
  }, [map, value, active, zoomed]);
  const institution = popup?.features[chosen]?.properties;
  return <>
    <aside className="academy-counts" data-testid="academy-layer" data-state={!zoomed ? 'hidden' : error ? 'error' : value?.status ?? (request ? 'loading' : 'waiting')} aria-label="학원 지도">
      {!zoomed ? <p>학원 점은 줌 15 이상에서 표시합니다.</p> : !request ? <p>채점이 완료되면 반경 학원 수를 표시합니다.</p> : error ? <p role="alert">{error} <button onClick={() => { attempted.current = ''; retry(v => v + 1); }}>학원 다시 시도</button></p> : !value ? <p role="status">학원 점을 불러오는 중입니다.</p> : value.status !== 'ready' ? <p role="status">{academyUnavailable[value.status]}</p> : <>
        <p data-testid="academy-counts">반경 <strong data-testid="academy-n">{value.counts.radius_same_field}</strong>곳 · 화면 <strong data-testid="academy-m">{counts?.viewportSameFieldM ?? '…'}</strong>곳</p>
        <p>{value.radius_m}m · {value.field} · 화면은 보이는 고유 기관 ID 기준</p>
        <p>진한 점 같은 분야 · 옅은 점 다른 분야 · 주황 외곽선 좌표 검증 보류 {value.counts.radius_pending}곳(전 분야)</p>
        <details><summary>출처·좌표 한계</summary><small>
          학원·교습소: 서울특별시교육청 / <a href="https://data.seoul.go.kr/dataList/OA-20528/S/1/datasetView.do" target="_blank" rel="noopener noreferrer">서울 열린데이터광장 OA-20528</a> (원천 NEIS), 공공누리 제1유형.
          분야·개원 상태는 제공 자료 기준, 층은 주소의 명시 표기만 표시합니다. 조회일 {typeof value.meta.source.fetched_at === 'string' ? value.meta.source.fetched_at.slice(0,10) : '미확인'}.
          좌표: 행정안전부 주소정보누리집, 출입구 위치(층 위치 아님). 좌표 조회일 미확인. 좌표 미확보 서울 전체 {value.meta.unlocated_count_seoul}곳 제외.
        </small></details>
      </>}
    </aside>
    {popup && institution && createPortal(<div className="academy-popup" data-testid="academy-popup" onKeyDown={event => { if (event.key === 'Escape') { popupRef.current?.remove(); map.getCanvas().focus(); } }}>
      {popup.features.length > 1 && <label>겹친 학원 {popup.features.length}곳<select aria-label="겹친 학원 선택" value={chosen} onChange={event => choose(Number(event.target.value))}>{popup.features.map((f, i) => <option value={i} key={f.id}>{f.properties.name}</option>)}</select></label>}
      <strong>{institution.name}</strong><p>{institution.field}</p><p>{institution.floor_status === 'explicit' ? institution.floor_label : '층 미표기'}</p>
      {institution.coordinate_verification_pending && <p className="academy-review-badge">좌표 검증 보류 · 점수에서 자동 제외하지 않습니다.</p>}
    </div>, popup.host)}
  </>;
}
