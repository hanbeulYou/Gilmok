'use client';
import Link from 'next/link';
import { scoreCandidate, useComparisonStore } from '../../lib/compare/store';
export default function ComparePage() {
  const candidates = useComparisonStore(state => state.candidates);
  return <main className="page wide"><Link href="/">길목</Link><h1>후보 비교</h1>
    <p>서울 · 학원업 · 반경 800m · 채점 기준 v0.3</p>
    <p>현재 비교는 이 화면에서 유지됩니다. 새로고침하면 초기화됩니다.</p>
    {candidates.length < 5 && <Link className="primary" href="/new">후보 추가</Link>}
    {candidates.length === 0 && <p>주소와 층을 등록하면 같은 기준으로 점수를 확인할 수 있습니다.</p>}
    <div className="candidate-list">{candidates.map(row => <article key={row.id} aria-label={row.alias}
      aria-busy={['fetching', 'scoring'].includes(row.stage)}>
      <h2>{row.alias} · {row.candidate.floor}층</h2><p>{row.candidate.address}</p>
      {['fetching', 'scoring'].includes(row.stage) ? <div className="skeleton" role="status">
        <p>{row.stage === 'fetching' ? '주변 데이터를 불러오는 중' : '건물 노출 조건과 점수를 계산하는 중'}</p>
        <p>첫 조회는 2~4초 이상 걸릴 수 있습니다.</p></div> : row.stage === 'error' ?
        <div role="alert"><p>{row.error}</p><button onClick={() => void scoreCandidate(row.id)}>채점 다시 시도</button></div> : row.result && <>
          {row.stage === 'scored_provisional' && <p className="badge">잠정 · 건물 정보를 조회 중입니다 (pending)</p>}
          <p className="total">{row.result.total === null ? '평가 불가' : `${row.result.total.toFixed(2)}점`}</p>
          <p>신뢰도 {row.result.confidence.value}</p>
          <dl>{row.result.axes.map(axis => <div className="axis" key={axis.key}><dt>{axis.label}</dt>
            <dd>{axis.normalized === null ? <span className="badge">{axis.status === 'pending' ? '조회 중' : '결측'}</span> : axis.normalized.toFixed(2)}</dd></div>)}</dl>
          {row.result.total !== null && row.result.axes.some(axis => axis.normalized === null) && <p>결측 축의 가중치는 계산 가능한 축으로 재배분됩니다.</p>}
          <p>가로수·가로시설물·간판 크기 미반영, 현장 확인 필요</p>
        </>}
      <button onClick={() => useComparisonStore.getState().remove(row.id)}>후보 삭제</button>
    </article>)}</div>
  </main>;
}
