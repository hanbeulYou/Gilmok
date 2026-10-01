'use client';
import { useEffect, useRef, useState } from 'react';
import type { AddressSelection } from '../../lib/geo/address-provider';
import { addressRequest } from '../../lib/geo/address-client';
export function AddressSearch({ disabled, selected, onSelect }: {
  disabled: boolean; selected: AddressSelection | null; onSelect: (value: AddressSelection | null) => void;
}) {
  const [query, setQuery] = useState(''), [choices, setChoices] = useState<AddressSelection[]>([]);
  const [message, setMessage] = useState(''), [busy, setBusy] = useState(false), [retry, setRetry] = useState(0);
  const serial = useRef(0);
  useEffect(() => {
    const sequence = ++serial.current;
    if (disabled || selected || query.trim().length < 2) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setBusy(true); setMessage('주소를 찾고 있습니다.');
      void addressRequest<{ total: number; choices: AddressSelection[] }>({ action: 'search', query },
        AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]))
        .then(result => {
          if (sequence !== serial.current) return;
          setChoices(result.choices);
          setMessage(result.total === 0 ? '검색 결과가 없습니다. 도로명과 건물번호 또는 지번으로 검색해 주세요.' :
            result.total > 100 ? '결과가 많습니다. 도로명과 건물번호를 더 입력해 주세요.' : `${result.total}개 주소 · 출처: 행정안전부 도로명주소`);
        }).catch(error => {
          if (!controller.signal.aborted && sequence === serial.current)
            setMessage(error instanceof Error ? error.message : '주소 검색에 실패했습니다.');
        }).finally(() => { if (sequence === serial.current) setBusy(false); });
    }, 500);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, disabled, selected, retry]);
  return <section aria-busy={busy}>
    <label htmlFor="address-query">주소 *</label>
    <input id="address-query" autoComplete="off" disabled={disabled} maxLength={100}
      placeholder="도로명·지번·건물명" value={query}
      onChange={event => { setQuery(event.target.value); onSelect(null); setChoices([]); setMessage(''); setBusy(false); }} />
    <p role="status">{selected ? `${selected.roadAddrPart1} 선택됨 · 행정안전부 도로명주소` : message}</p>
    {!selected && choices.length > 0 && <ul className="address-options" aria-label="주소 검색 결과">
      {choices.map(choice => <li key={choice.bdMgtSn}><button type="button" onClick={() => {
        onSelect(choice); setChoices([]); setBusy(false);
      }}><strong>{choice.roadAddrPart1}</strong><br />{choice.jibunAddr}{choice.bdNm ? ` · ${choice.bdNm}` : ''}</button></li>)}
    </ul>}
    {!selected && !busy && message && choices.length === 0 && <button type="button" disabled={disabled}
      onClick={() => setRetry(value => value + 1)}>주소 검색 다시 시도</button>}
  </section>;
}
