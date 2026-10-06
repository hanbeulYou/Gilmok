'use client';
import { useEffect, useRef, useState } from 'react';
import { academyV0 } from '../../lib/scoring/presets';
import { useComparisonStore } from '../../lib/compare/store';
import { listWeightPresets, reopenComparison, saveComparison, saveWeightPreset, type WeightPreset } from '../../lib/compare/persistence';
import { ensureSession } from '../../lib/supabase/session';
import { getSupabaseClient } from '../../lib/supabase/client';

export function SaveControls() {
  const state = useComparisonStore(), started = useRef(false);
  const previousUid = useRef<string | null>(null);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState('');
  const [presets, setPresets] = useState<WeightPreset[]>([]), [naming, setNaming] = useState(false), [name, setName] = useState('');
  const [notice, setNotice] = useState(false), [uid, setUid] = useState('');
  const modified = Object.keys(academyV0.weights).some(k => state.weights[k as keyof typeof state.weights] !== academyV0.weights[k as keyof typeof state.weights]);
  const selected = presets.find(p => Object.keys(p.weights).every(k => p.weights[k as keyof typeof p.weights] === state.weights[k as keyof typeof state.weights]));
  useEffect(() => {
    const { data } = getSupabaseClient().auth.onAuthStateChange((_event, session) => {
      const next = session?.user.id ?? null;
      if (previousUid.current && next !== previousUid.current) {
        useComparisonStore.getState().clear(); setPresets([]); setMessage(''); setError(''); setNotice(false); setNaming(false);
        // Supabase auth callbacks must not await another Supabase request.
        if (next) setTimeout(() => { void listWeightPresets().then(setPresets).catch(() => setPresets([])); }, 0);
      }
      previousUid.current = next; setUid(next ?? '');
    });
    return () => data.subscription.unsubscribe();
  }, []);
  useEffect(() => {
    if (started.current) return; started.current = true;
    void (async () => {
      setBusy(true);
      try {
        const session = await ensureSession(); setUid(session.user.id);
        if (!useComparisonStore.getState().candidates.length)
          await reopenComparison(new URLSearchParams(window.location.search).get('comparison'));
        setPresets(await listWeightPresets());
      } catch (e) { setError(e instanceof Error ? e.message : '저장 정보를 확인하지 못했습니다.'); }
      finally { setBusy(false); }
    })();
  }, []);
  async function save() {
    setNotice(false); setBusy(true); setError('');
    try {
      const id = await saveComparison();
      try { localStorage.setItem(`gilmok:save-notice:${uid}`, 'acknowledged'); } catch { /* Notice repeats if storage is unavailable. */ }
      window.history.replaceState(null, '', `/compare?comparison=${id}`);
      setMessage('비교를 저장했습니다. 같은 브라우저에서 다시 열 수 있습니다.');
    } catch (e) { setError(e instanceof Error ? e.message : '저장에 실패했습니다.'); }
    finally { setBusy(false); }
  }
  function requestSave() {
    let seen = false;
    try { seen = localStorage.getItem(`gilmok:save-notice:${uid}`) === 'acknowledged'; } catch { /* Notice remains required. */ }
    if (seen) void save(); else setNotice(true);
  }
  async function reopen() {
    setBusy(true); setError(''); setMessage('');
    try { if (!await reopenComparison()) setMessage('저장한 비교가 없습니다.'); }
    catch (e) { setError(e instanceof Error ? e.message : '다시 열지 못했습니다.'); }
    finally { setBusy(false); }
  }
  return <section className="save-controls" aria-label="비교 저장과 프리셋" aria-busy={busy}>
    <div className="comparison-toolbar">
      <label>가중치 프리셋<select aria-label="가중치 프리셋" value={selected?.id ?? (modified ? 'modified' : 'default')}
        disabled={busy || state.snapshotReadOnly} onChange={e => {
          const weights = e.target.value === 'default' ? academyV0.weights : presets.find(p => p.id === e.target.value)?.weights;
          if (weights) { state.beginAdjustment(); for (const [key, value] of Object.entries(weights)) state.setWeight(key as keyof typeof weights, value); state.endAdjustment(); }
        }}>
        <option value="default">학원 v0.3(기본)</option><option value="modified" disabled>학원 v0.3 · 수정됨</option>
        {presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select></label>
      <button disabled={!modified || busy || state.snapshotReadOnly} onClick={() => setNaming(true)}>프리셋으로 저장</button>
      <button disabled={!state.candidates.length || busy || state.snapshotReadOnly} onClick={requestSave}>비교 저장</button>
      <button disabled={busy} onClick={() => void reopen()}>저장한 비교 다시 열기</button>
    </div>
    {naming && <form onSubmit={async e => {
      e.preventDefault(); setBusy(true); setError('');
      try { await saveWeightPreset(name, state.weights); setPresets(await listWeightPresets()); setNaming(false); setName(''); setMessage('가중치 프리셋을 저장했습니다.'); }
      catch (e) { setError(e instanceof Error ? e.message : '프리셋 저장에 실패했습니다.'); }
      finally { setBusy(false); }
    }}><label>프리셋 이름<input value={name} onChange={e => setName(e.target.value)} required maxLength={30}/></label>
      <button disabled={busy} type="submit">가중치 이름 저장</button><button type="button" onClick={() => setNaming(false)}>취소</button>
      <small>같은 이름으로 저장하면 기존 가중치를 바꿉니다.</small></form>}
    {notice && <div className="save-notice" role="dialog" aria-label="익명 저장 안내">
      <p>이 브라우저에 익명으로 저장합니다. 다른 브라우저를 쓰거나 브라우저 저장소를 지우면 복구할 수 없습니다.</p>
      <p>미활동 보존기간은 미저장 30일, 저장 후보가 있으면 90일입니다. 정리 배치는 현재 비활성입니다.</p>
      <button onClick={() => void save()}>안내 확인하고 저장</button><button onClick={() => setNotice(false)}>취소</button>
    </div>}
    {state.snapshotReadOnly && <p role="status">마지막 저장 결과 · 읽기 전용 · 채점 시각 {state.candidates[0]?.result?.computed_at}. 새 데이터와 섞지 않은 이전 결과입니다.</p>}
    {busy && <p role="status">저장 정보를 확인하고 있습니다.</p>}
    {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
