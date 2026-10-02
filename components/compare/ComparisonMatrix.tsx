'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { axisKeys, labels } from '../../lib/scoring/axes';
import { academyV0 } from '../../lib/scoring/presets';
import { reweight } from '../../lib/scoring/score';
import type { AxisKey, ScoreResult } from '../../lib/scoring/types';
import { acceptLookup, scoreCandidate, useComparisonStore, type ComparisonCandidate } from '../../lib/compare/store';
import { subscribeLookups, type ConnectionState } from '../../lib/compare/subscriptions';
import { delayed, isWaiting } from '../../lib/compare/status';
import { ensureSession } from '../../lib/supabase/session';
import { getSupabaseClient } from '../../lib/supabase/client';
import { EXPOSURE_LIMITATION } from '../../lib/visibility/types';
import { AxisBadges, Confidence } from './Badges';
import { EvidencePanel } from './EvidencePanel';
import { number, rawSummary, reason } from './format';
import { WeightSlider } from './WeightSlider';
function useLookupUpdates(rows: readonly ComparisonCandidate[]) {
  const [uid, setUid] = useState<string | null>(null), [connection, setConnection] = useState<ConnectionState>('connecting');
  const subscription = useRef<ReturnType<typeof subscribeLookups> | null>(null), previousUid = useRef<string | null>(null);
  const ids = [...new Set(rows.flatMap(r => r.lookupRequestId ? [r.lookupRequestId] : []))].sort().join(',');
  useEffect(() => {
    let alive = true;
    void ensureSession().then(session => { if (alive) setUid(session.user.id); }, () => { if (alive) setConnection('reconnecting'); });
    const { data } = getSupabaseClient().auth.onAuthStateChange((_event, session) => { if (alive) setUid(session?.user.id ?? null); });
    return () => { alive = false; data.subscription.unsubscribe(); };
  }, []);
  useEffect(() => {
    if (previousUid.current && previousUid.current !== uid) {
      const store = useComparisonStore.getState(); for (const row of store.candidates) store.remove(row.id);
    }
    previousUid.current = uid;
    if (!uid || !ids) return;
    const targets = useComparisonStore.getState().candidates.filter(r => r.lookupRequestId);
    const controller = subscribeLookups(getSupabaseClient(), uid, ids.split(','), lookup => {
      for (const row of targets) if (row.lookupRequestId === lookup.request_id) acceptLookup(row.id, row.generation, lookup);
    }, setConnection);
    subscription.current = controller;
    const online = () => void controller.reconcile();
    window.addEventListener('online', online);
    return () => { controller.close(); subscription.current = null; window.removeEventListener('online', online); };
  }, [uid, ids]);
  return { connection, waiting: Boolean(ids), reconcile: () => void subscription.current?.reconcile() };
}
function CandidateMenu({ row, order }: { row: ComparisonCandidate; order: readonly string[] }) {
  const [error, setError] = useState('');
  const index = order.indexOf(row.id);
  return <details className="candidate-menu"><summary aria-label={`${row.alias} 후보 설정`}>···</summary>
    <form onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget);
      try { useComparisonStore.getState().edit(row.id, String(data.get('alias')), Number(data.get('floor'))); setError(''); event.currentTarget.closest('details')?.removeAttribute('open'); }
      catch (e) { setError(e instanceof Error ? e.message : '입력을 확인해 주세요.'); } }}>
      <label>별칭<input name="alias" defaultValue={row.alias} required maxLength={20}/></label>
      <label>층<input name="floor" type="number" min={-5} max={30} step={1} defaultValue={row.candidate.floor} required/></label>
      {error && <p role="alert">{error}</p>}<button type="submit">변경 적용</button>
    </form>
    <button onClick={() => useComparisonStore.getState().remove(row.id)}>후보 삭제</button>
    {index > 0 && <button onClick={() => useComparisonStore.getState().move(row.id, order[index - 1])}>앞으로 이동</button>}
    {index < order.length - 1 && <button onClick={() => useComparisonStore.getState().move(order[index + 1], row.id)}>뒤로 이동</button>}
  </details>;
}
function Notice({ row }: { row: ComparisonCandidate }) {
  return <div className="candidate-notice" role="status">
    {!row.result && row.stage !== 'error' && <div className="skeleton"><span>{row.stage === 'scoring' ? '노출 계산 중' : '주변 데이터를 불러오는 중'}</span>
      {Date.now() - row.startedAt >= 2000 && <p>첫 조회는 조금 더 걸릴 수 있습니다.</p>}</div>}
    {row.result && (row.stage === 'scored_provisional' || row.result.axes.some(a => a.status === 'pending') || row.refreshing) && <span className="badge pending">잠정{row.refreshing ? ' · 갱신 중' : ''}</span>}
    {isWaiting(row.lookupStatus) && delayed(row.pendingSince, Date.now()) && <p className="delay-notice">건물 정보 확인 지연 — 나중에 다시 열면 반영됩니다</p>}
    {row.lookupStatus === 'failed' && <p>건물 정보 조회 실패 — 확인 필요</p>}
    {row.stage === 'error' && <div role="alert"><p>{row.error}</p><button onClick={() => void scoreCandidate(row.id, Boolean(row.inputs?.primary && row.lookupState))}>채점 다시 시도</button></div>}
  </div>;
}
function Total({ row, result, select }: { row: ComparisonCandidate; result?: ScoreResult; select: () => void }) {
  const missing = result?.axes.filter(a => a.normalized === null && a.weight > 0).length ?? 0;
  return <><Notice row={row}/>{result && <>
    <div className="total-line"><span className="total score-change" key={result.total} data-total={result.total ?? 'null'}>{result.total === null ? '평가 불가' : `${result.total.toFixed(2)}점`}</span>
      <Confidence key={result.confidence.value} value={result.confidence.value} onClick={select}/></div>
    {missing > 0 && <span className="badge missing">{missing}축 재배분</span>}
    {result.total === null && <small>{result.axes.filter(a => ['demand','flow','transit','cluster','environment'].includes(a.key) && a.normalized === null).length >= 2
      ? '수요·유동·교통·집적·환경 중 2축 이상 결측' : '점수가 있는 축의 가중치 합이 0입니다'}</small>}
  </>}</>;
}
export function ComparisonMatrix() {
  const state = useComparisonStore(), [tab, setTab] = useState<'compare' | 'evidence'>('compare'), [sheet, setSheet] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null), [clockTick, tick] = useState(0), swipe = useRef<{x: number; y: number} | null>(null);
  const realtime = useLookupUpdates(state.candidates);
  const rows = state.order.map(id => state.candidates.find(row => row.id === id)).filter((r): r is ComparisonCandidate => Boolean(r));
  const results = useMemo(() => new Map(state.candidates.map(row => [row.id, row.result ? reweight(row.result, state.weights) : undefined])), [state.candidates, state.weights]);
  const selected = state.candidates.find(r => r.id === state.selectedId);
  const modified = axisKeys.some(key => state.weights[key] !== academyV0.weights[key]);
  const select = (id: string, axis?: AxisKey) => { state.select(id, axis); setTab('evidence'); };
  useEffect(() => { if (sheet) dialog.current?.showModal(); else dialog.current?.close(); }, [sheet]);
  useEffect(() => {
    const now = Date.now(), deadlines = state.candidates.flatMap(row => [
      ...(!row.result && row.stage !== 'error' && row.startedAt + 2000 > now ? [row.startedAt + 2000] : []),
      ...(isWaiting(row.lookupStatus) && row.pendingSince && row.pendingSince + 180000 > now ? [row.pendingSince + 180000] : []),
    ]);
    if (!deadlines.length) return;
    const timer = setTimeout(() => tick(n => n + 1), Math.min(...deadlines) - now + 1);
    return () => clearTimeout(timer);
  }, [state.candidates, clockTick]);
  return <main className={`page comparison ${state.evidenceOpen ? 'has-evidence' : ''}`}>
    <header className="comparison-header"><div><Link href="/">길목</Link><h1>후보 비교</h1><p>서울 · 학원업 · 반경 800m</p></div>
      <div><span className="preset">학원 v0.3{modified ? ' · 수정됨' : ' (기본)'}</span><nav>{rows.length < 5 && <Link href="/new" className="primary">후보 추가</Link>}</nav></div></header>
    <p className="memory-notice">현재 비교는 이 화면에서 유지됩니다. 새로고침하면 초기화됩니다.</p>
    {state.candidates.length > 0 && state.candidates.every(r => r.stage === 'error' && !r.result) && <p role="alert">데이터 서버에 연결할 수 없습니다. 후보별로 다시 시도해 주세요.</p>}
    {realtime.waiting && realtime.connection !== 'connected' && <p role="status">건물 확인 상태 {realtime.connection === 'connecting' ? '연결 중' : '재연결 중'} <button onClick={realtime.reconcile}>상태 다시 확인</button></p>}
    {!rows.length ? <section className="empty-state"><h2>주소를 입력해 첫 후보를 등록하세요</h2><Link className="primary" href="/new">후보 추가</Link></section> : <>
      <div className="comparison-toolbar"><button onClick={state.resetWeights}>가중치 초기화</button><button onClick={state.sortByScore}>{state.manualOrder ? '총점순 자동 정렬로 복귀' : '총점순 정렬'}</button>
        <span>{state.manualOrder ? '열 순서 고정' : '총점 내림차순'} · {rows.length}/5곳</span><button className="mobile-only" onClick={() => setSheet(true)}>가중치</button></div>
      {rows.length === 1 && <p>비교하려면 후보를 더 추가하세요.</p>}
      <div className="mobile-tabs" role="tablist" aria-label="비교 화면"><button role="tab" aria-selected={tab === 'compare'} onClick={() => setTab('compare')}>비교</button>
        <button role="tab" aria-selected={tab === 'evidence'} onClick={() => { setTab('evidence'); if (selected) state.select(selected.id); }}>근거</button></div>
      <div className="desktop-matrix matrix-scroll"><table className="comparison-matrix" aria-label="후보별 8축 비교"><thead><tr><th scope="col">평가 항목</th>
        {rows.map(row => <th scope="col" key={row.id} draggable onDragStart={e => e.dataTransfer.setData('text/plain', row.id)} onDragOver={e => e.preventDefault()}
          onDrop={e => { e.preventDefault(); state.move(e.dataTransfer.getData('text/plain'), row.id); }} data-candidate-id={row.id}>
          <button className="candidate-name" onClick={() => select(row.id)}>{row.alias} · {row.candidate.floor}층</button><small>{row.candidate.address}</small><CandidateMenu row={row} order={state.order}/></th>)}</tr>
        <tr className="total-row"><th scope="row">총점</th>{rows.map(row => <td key={row.id} aria-busy={row.refreshing || !row.result && row.stage !== 'error'}><Total row={row} result={results.get(row.id)} select={() => select(row.id)}/></td>)}</tr></thead>
        <tbody>{axisKeys.map((key, index) => {
          const distinct = [...new Set(rows.flatMap(row => { const value = results.get(row.id)?.axes[index].normalized; return value == null ? [] : [value]; }))].sort((a,b) => b-a);
          return <tr key={key}><th scope="row"><WeightSlider axis={key} value={state.weights[key]} prefix="desktop"/></th>{rows.map(row => {
            const result = results.get(row.id), axis = result?.axes[index];
            return <td key={row.id} data-axis={key} data-candidate-id={row.id} className={axis?.normalized == null ? 'missing-cell' : `tone-${Math.min(2, distinct.indexOf(axis.normalized))}`}>
              {axis && result ? <button className="score-cell" onClick={() => select(row.id, key)} aria-label={`${row.alias} ${labels[key]} 근거`} title={axis.missing_reason ? reason(axis.missing_reason) : undefined}>
                <span key={`${axis.normalized}:${axis.status}`} className="axis-score score-change" data-score={axis.normalized ?? 'null'}>{number(axis.normalized)}</span><small>{rawSummary(axis)}</small><AxisBadges axis={axis} result={result}/></button> : row.stage === 'error' ? <span>조회 실패</span> : <span className="cell-skeleton" aria-label="점수 불러오는 중"/>}
            </td>;
          })}</tr>;
        })}</tbody></table></div>
      <div className={`mobile-cards ${tab !== 'compare' ? 'mobile-hidden' : ''}`}>{rows.map((row, index) => {
        const result = results.get(row.id);
        return <article key={row.id} className={row.id === state.selectedId ? 'selected-card' : ''} aria-label={row.alias} data-candidate-id={row.id}>
          <header onTouchStart={e => { swipe.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }; }} onTouchEnd={e => {
            const from = swipe.current; swipe.current = null; if (!from) return; const to = e.changedTouches[0];
            if (Math.abs(to.clientY - from.y) > 40 || Math.abs(to.clientX - from.x) < 60) return;
            const next = rows[index + (to.clientX < from.x ? 1 : -1)]; if (next) { state.select(next.id); document.querySelector(`.mobile-cards [data-candidate-id="${next.id}"]`)?.scrollIntoView({block:'nearest'}); }
          }}><h2><button className="candidate-name" onClick={() => select(row.id)}>{row.alias} · {row.candidate.floor}층</button></h2><CandidateMenu row={row} order={state.order}/></header>
          <p>{row.candidate.address}</p><Total row={row} result={result} select={() => select(row.id)}/>
          <div className="mobile-axes">{result?.axes.map(axis => <button key={axis.key} className="mobile-axis" onClick={() => select(row.id, axis.key)} aria-label={`${row.alias} ${axis.label} 근거`}>
            <span>{axis.label}</span><strong key={`${axis.normalized}:${axis.status}`} className="score-change" data-score={axis.normalized ?? 'null'}>{number(axis.normalized)}</strong><span className="bar-track"><span style={{width:`${axis.normalized ?? 0}%`}}/></span><small>{rawSummary(axis)}</small><AxisBadges axis={axis} result={result}/></button>)}</div>
        </article>;
      })}</div>
      <p className="exposure-limit">{EXPOSURE_LIMITATION}</p>
      {selected && state.evidenceOpen && <div className={tab !== 'evidence' ? 'mobile-hidden' : ''}><EvidencePanel row={{...selected, result: results.get(selected.id)}} axisKey={state.selectedAxis} close={() => { state.closeEvidence(); setTab('compare'); }}/></div>}
      {tab === 'evidence' && !state.evidenceOpen && <p className="mobile-only">후보를 선택해 근거를 확인하세요.</p>}
      <dialog className="weight-sheet" ref={dialog} onClose={() => setSheet(false)}><header><h2>축별 가중치</h2><button onClick={() => setSheet(false)}>닫기</button></header>
        {axisKeys.map(key => <WeightSlider key={key} axis={key} value={state.weights[key]} prefix="mobile"/>)}<button onClick={state.resetWeights}>가중치 초기화</button></dialog>
    </>}
  </main>;
}
