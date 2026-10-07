'use client';
import { Component, lazy, memo, Suspense, useEffect, useMemo, useState, type ReactNode } from 'react';

class MapBoundary extends Component<{ children: ReactNode; retry: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <p role="alert">지도를 불러오지 못했습니다. <button onClick={this.props.retry}>지도 다시 시도</button></p> : this.props.children; }
}

/** No MapLibre or map CSS import until after desktop shell paint / an explicit mobile action. */
export const MapGate = memo(function MapGate() {
  const [opened, setOpened] = useState(false), [desktop, setDesktop] = useState(false), [attempt, setAttempt] = useState(0);
  const MapView = useMemo(() => lazy(() => import('./CompareMap')), [attempt]);
  useEffect(() => {
    const media = matchMedia('(min-width: 1024px)');
    let first = 0, second = 0;
    const update = () => {
      setDesktop(media.matches);
      cancelAnimationFrame(first); cancelAnimationFrame(second);
      if (media.matches) first = requestAnimationFrame(() => { second = requestAnimationFrame(() => setOpened(true)); });
    };
    performance.mark('gilmok:matrix-shell'); update(); media.addEventListener('change', update);
    return () => { media.removeEventListener('change', update); cancelAnimationFrame(first); cancelAnimationFrame(second); };
  }, []);
  const retry = () => setAttempt(value => value + 1);
  return <section className={`map-panel ${opened ? 'map-activated' : ''}`} aria-label="후보 지도">
    <header className="map-heading"><h2>주변 지도</h2><span>2D</span>
      {!desktop && <button aria-expanded={opened} aria-controls="compare-map-content" onClick={() => setOpened(true)}>지도 보기</button>}</header>
    <div id="compare-map-content">{opened ? <MapBoundary key={attempt} retry={retry}><Suspense fallback={<div className="map-placeholder" role="status">지도를 불러오는 중입니다.</div>}>
      <MapView retry={retry}/></Suspense></MapBoundary> : <div className="map-placeholder" aria-hidden="true">선택 후보의 반경·역·학교</div>}</div>
  </section>;
});
