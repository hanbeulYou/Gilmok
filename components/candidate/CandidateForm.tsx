'use client';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { ensureSession } from '../../lib/supabase/session';
import { getSupabaseClient } from '../../lib/supabase/client';
import type { AddressSelection, RegisteredLocation } from '../../lib/geo/address-provider';
import { addressRequest } from '../../lib/geo/address-client';
import { scoreCandidate, useComparisonStore } from '../../lib/compare/store';
import type { ResolvedLocation } from '../../lib/compare/load-candidate';
import { AddressSearch } from './AddressSearch';
export function CandidateForm() {
  const router = useRouter(), candidates = useComparisonStore(state => state.candidates);
  const [selection, setSelection] = useState<AddressSelection | null>(null);
  const [auth, setAuth] = useState<'loading' | 'ready' | 'error'>('loading');
  const [message, setMessage] = useState(''), [busy, setBusy] = useState(false);
  const [floor, setFloor] = useState('3'), [area, setArea] = useState('');
  const submitting = useRef(false);
  const located = useRef<{ pnu: string; location: RegisteredLocation; resolved: ResolvedLocation } | null>(null);
  async function authenticate() {
    setAuth('loading');
    try { await ensureSession(); setAuth('ready'); await getSupabaseClient().rpc('touch_user_activity'); }
    catch { setAuth('error'); }
  }
  useEffect(() => { void authenticate(); }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || !selection) return;
    const fields = new FormData(event.currentTarget);
    const number = (key: string) => String(fields.get(key) ?? '').trim() === '' ? null : Number(fields.get(key));
    const floorValue = Number(floor), areaValue = number('area');
    if (!Number.isInteger(floorValue) || floorValue === 0 || floorValue < -5 || floorValue > 30) {
      setMessage('층은 지하 5층(−5)부터 30층까지 입력해 주세요. 0층은 없습니다.'); return;
    }
    if (candidates.length >= 5) { setMessage('후보는 최대 5곳까지 비교할 수 있습니다.'); return; }
    const amounts = [number('deposit'), number('rent'), number('maintenance')];
    if (amounts.some(n => n !== null && (!Number.isFinite(n) || n < 0)) ||
      (areaValue !== null && (!Number.isFinite(areaValue) || areaValue <= 0))) {
      setMessage('면적은 양수, 금액은 0 이상으로 입력해 주세요.'); return;
    }
    submitting.current = true; setBusy(true); setMessage('건물 위치를 확인하고 있습니다.');
    try {
      if (!located.current || located.current.pnu !== selection.pnu) {
        const value = await addressRequest<{ location: RegisteredLocation; resolved: ResolvedLocation }>({ action: 'locate', selection });
        located.current = { pnu: selection.pnu, ...value };
      }
      const { location, resolved } = located.current;
      const id = useComparisonStore.getState().add({
        alias: String(fields.get('alias') ?? '').trim() || `${selection.rn} ${Number(selection.buldMnnm)}${Number(selection.buldSlno) ? `-${Number(selection.buldSlno)}` : ''}`,
        candidate: { lat: location.lat, lng: location.lng, floor: floorValue, address: selection.roadAddrPart1,
          exclusive_area_m2: areaValue, deposit_krw: amounts[0], monthly_rent_krw: amounts[1], maintenance_krw: amounts[2] },
        selection, location, resolved,
      });
      void scoreCandidate(id); router.push('/compare');
    } catch (error) { setMessage(error instanceof Error ? error.message : '등록에 실패했습니다. 다시 시도해 주세요.'); }
    finally { submitting.current = false; setBusy(false); }
  }
  const duplicate = selection && candidates.some(c => c.selection.pnu === selection.pnu && c.candidate.floor === Number(floor));
  return <>
    {auth !== 'ready' && <div role="status">{auth === 'loading' ? '익명 로그인을 준비하고 있습니다.' :
      <><p>익명 로그인이 필요합니다. 인증 후 주소를 검색할 수 있습니다.</p><button onClick={() => void authenticate()}>인증 다시 시도</button></>}</div>}
    <AddressSearch disabled={auth !== 'ready' || busy || candidates.length >= 5} selected={selection}
      onSelect={value => { setSelection(value); located.current = null; }} />
    <form onSubmit={event => void submit(event)} aria-busy={busy}>
      <fieldset disabled={auth !== 'ready' || busy || candidates.length >= 5}>
        <legend>후보 정보</legend>
        <label htmlFor="floor">층 *</label><input id="floor" name="floor" type="number" required min={-5} max={30} step={1}
          value={floor} onChange={event => setFloor(event.target.value)} /><p>지하층은 음수로 입력합니다. (예: 지하 1층 −1)</p>
        {duplicate && <p role="status">같은 주소·층의 후보가 있습니다. 다른 조건으로 추가할 수 있습니다.</p>}
        <label htmlFor="area">전용면적 (㎡, 선택)</label><input id="area" name="area" type="number" min="0.01" step="any"
          value={area} onChange={event => setArea(event.target.value)} />
        {Number(area) >= 500 && <p>500㎡ 이상은 교육연구시설 용도 확인이 필요합니다.</p>}
        <label htmlFor="deposit">보증금 (원, 선택)</label><input id="deposit" name="deposit" type="number" min="0" step="1" />
        <label htmlFor="rent">월 임대료 (원, 선택)</label><input id="rent" name="rent" type="number" min="0" step="1" />
        <label htmlFor="maintenance">월 관리비 (원, 선택)</label><input id="maintenance" name="maintenance" type="number" min="0" step="1" />
        <p>미입력 값은 결측으로 표시합니다. 현재 임대 효율은 기준 범위 미확정으로 근거에만 표시합니다.</p>
        <label htmlFor="alias">별칭 (선택, 20자)</label><input id="alias" name="alias" maxLength={20} />
        <button className="primary" type="submit" disabled={!selection}>{busy ? '위치 확인 중…' : '후보 추가하고 채점'}</button>
      </fieldset><p role="status">{candidates.length >= 5 ? '후보는 최대 5곳까지 비교할 수 있습니다.' : message}</p>
    </form>
  </>;
}
