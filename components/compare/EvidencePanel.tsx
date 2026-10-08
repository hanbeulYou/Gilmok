import { memo } from 'react';
import type { AxisKey, AxisResult } from '../../lib/scoring/types';
import type { ComparisonCandidate } from '../../lib/compare/store';
import { EXPOSURE_LIMITATION } from '../../lib/visibility/types';
import { number, reason } from './format';
const names: Record<string, string> = {
  population: '학령인구', pop_5_9: '5~9세', pop_10_14: '10~14세', pop_15_18: '15~18세',
  schools_1km: '학교 1km', elem: '초등학교', mid: '중학교', high: '고등학교',
  weekday: '평일', weekend: '주말', n_field: '학원 수', students: '학령인구', saturation: '학생 1,000명당 학원',
  saturation_percentile: '포화도 서울 백분위', saturation_level: '포화 수준', components: '교통 구성요소',
  nearest_subway_m: '최근접 역 거리(m)', subway_boardings_golden: '학원 시간대 승하차', bus_stops: '버스 정류장 수',
  stores_total: '상가 수', estimated: '추정 여부', unknown_ratio: '높이 미상 비율', low_coverage: '낮은 커버리지',
  field: '학원 분야', fixed_scale: '집적 고정 선형 스케일', visible_ratio: '가시 비율',
  effective_monthly_rent: '월 환산 임대료', rent_per_m2: '㎡당 임대료', trade_median_per_m2: '매매 ㎡당 중앙값',
  floor_no: '층', floor_kind: '층 구분', use_name: '용도', other_use: '기타 용도', area_m2: '면적(㎡)',
  model_version: '모델 버전', snapshot: '기준 스냅샷', source: '출처', fetched_at: '조회일', period: '기준 기간',
};
const ValueTree = memo(function ValueTree({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>미확인</span>;
  if (typeof value === 'number') return <span>{number(value, 8)}</span>;
  if (typeof value === 'boolean') return <span>{value ? '예' : '아니오'}</span>;
  if (typeof value !== 'object') return <span>{String(value)}</span>;
  if (Array.isArray(value)) return value.length ? <ol className="evidence-list">{value.map((v, i) => <li key={i}><ValueTree value={v}/></li>)}</ol> : <span>없음</span>;
  return <dl className="evidence-values">{Object.entries(value).map(([key, v]) => <div key={key}><dt>{names[key] ?? key}</dt><dd>
    {v && typeof v === 'object' ? <details><summary>상세 값 보기</summary><ValueTree value={v}/></details> : <ValueTree value={v}/>}</dd></div>)}</dl>;
});
const histogramKeys: Partial<Record<AxisKey, readonly string[]>> = {
  demand: ['demand'], flow: ['flow'], transit: ['transit.nearest_subway_m', 'transit.subway_boardings_golden', 'transit.bus_stops'],
  cluster: ['cluster.saturation'], environment: ['environment.stores_total'],
};
function Histograms({ row, axis }: { row: ComparisonCandidate; axis: AxisResult }) {
  const metrics = row.inputs?.reference?.percentiles.filter(p => histogramKeys[axis.key]?.includes(p.key)) ?? [];
  return <div className="histograms">{metrics.map(metric => {
    const h = metric.histogram, max = Math.max(1, ...h.bins);
    if (h.min === null || h.max === null || !h.bins.length) return <p key={metric.key}>기준 분포 없음</p>;
    const x = metric.raw === null ? null : h.max === h.min ? 5 : Math.max(0, Math.min(200, (metric.raw - h.min) / (h.max - h.min) * 200));
    return <figure key={metric.key}><figcaption>{axis.key === 'cluster' ? '포화도 근거용 분포 (집적 점수와 별개)' : names[metric.key.split('.').at(-1)!] ?? axis.label}
      {' · 서울 백분위 '}{number(metric.percentile)} · 모집단 {number(metric.population_size, 0)}</figcaption>
      <svg role="img" aria-label={`${metric.key} 서울 분포, 백분위 ${number(metric.percentile)}, 모집단 ${metric.population_size}`} viewBox="0 0 200 46">
        {h.bins.map((n, i) => <rect key={i} x={i * 10} y={42 - n / max * 36} width="9" height={n / max * 36} fill="#bacfca"/>)}
        {x !== null && <line x1={x} x2={x} y1="1" y2="45" stroke="#b45309" strokeWidth="2"/>}</svg>
      <div className="range-labels"><span>{number(h.min)}</span><span>{number(h.max)}</span></div></figure>;
  })}</div>;
}
function AxisEvidence({ row, axis }: { row: ComparisonCandidate; axis: AxisResult }) {
  const floors = row.inputs?.primary?.building?.all_floors ?? [];
  const numeric = (key: string) => typeof axis.evidence.values[key] === 'number' ? axis.evidence.values[key] as number : null;
  return <div data-evidence-axis={axis.key}>
    <p>설정 가중치 {number(axis.weight)} · 결측 재배분 후 유효 가중치 {number(axis.effective_weight)}</p>
    <p>정규화 {number(axis.normalized)}점 · 원시값 {number(axis.raw, 8)} · 서울 백분위 {number(axis.evidence.percentile)}
      {axis.evidence.reference && <> · 모집단 {number(axis.evidence.reference.population_size, 0)} · 커버리지 {number(axis.evidence.reference.coverage * 100)}%</>}</p>
    {axis.missing_reason && <p className="missing-explanation">{reason(axis.missing_reason)}</p>}
    {axis.key === 'exposure' && <p className="limitation">{EXPOSURE_LIMITATION}</p>}
    {axis.key === 'building' && typeof axis.evidence.values.floor_elevator_row === 'string' &&
      <p data-testid="floor-elevator-rule">적용 행: {axis.evidence.values.floor_elevator_row} · 보정 {number(numeric('floor_adjustment'))}점</p>}
    {axis.key === 'exposure' && typeof axis.evidence.values.floor_attention_coefficient === 'number' &&
      <p data-testid="floor-attention-rule">{number(numeric('requested_floor'), 0)}층 · 주목도 Y 계수 {number(numeric('floor_attention_coefficient'), 2)} (모델 가정)
        {' · 원래 가시 비율 '}{number(numeric('visible_ratio'), 8)}</p>}
    {axis.key === 'rent_efficiency' && <><p>임대료 점수 범위는 미확정입니다. 아래 값은 사용자 입력·환산·매매 참고 자료입니다.</p>
      <ValueTree value={{ '전용면적㎡': row.candidate.exclusive_area_m2, 보증금원: row.candidate.deposit_krw,
        월세원: row.candidate.monthly_rent_krw, 관리비원: row.candidate.maintenance_krw }}/></>}
    <Histograms row={row} axis={axis}/>
    <h4>원시값과 추정 근거</h4><ValueTree value={axis.evidence.values}/>
    <h4>적용 규칙</h4><ul>{axis.evidence.rules_applied.map((r, i) => <li key={i}>{r}</li>)}</ul>
    <h4>결측·한계·재배분 근거</h4><ul>{axis.evidence.notes.map((r, i) => <li key={i}>{reason(r)}</li>)}</ul>
    {axis.key === 'building' && <><h4>전 층 용도·면적</h4>{floors.length ? <table className="floor-table"><thead><tr><th>층</th><th>용도</th><th>기타 용도</th><th>면적(㎡)</th></tr></thead>
      <tbody>{floors.map((f, i) => <tr key={i}><td>{f.floor_kind === '10' ? '지하 ' : ''}{number(f.floor_no, 0)}</td><td>{f.use_name ?? '미확인'}</td><td>{f.other_use ?? '—'}</td><td>{number(f.area_m2)}</td></tr>)}</tbody></table> : <p>층별 자료가 없습니다.</p>}
      <ul>{row.result?.derived.academy_eligible_reasons.map(r => <li key={r}>{reason(r)}</li>)}</ul></>}
  </div>;
}
export function EvidencePanel({ row, axisKey, close }: { row: ComparisonCandidate; axisKey: AxisKey | null; close: () => void }) {
  const axes = row.result?.axes.filter(axis => !axisKey || axis.key === axisKey) ?? [];
  return <section className="evidence-panel" aria-label="근거 패널"><header><h2 id="evidence-heading" tabIndex={-1}>{row.alias} · {axisKey ? axes[0]?.label : '후보 전체'} 근거</h2><button onClick={close}>근거 닫기</button></header>
    {!row.result ? <p>점수가 준비되면 근거를 볼 수 있습니다.</p> : <>
      {!axisKey && <><h3>신뢰도 {row.result.confidence.value}점 · 감점 사유</h3><ul>{row.result.confidence.reasons.map((r, i) => <li key={i}>{reason(r)}</li>)}</ul></>}
      {axes.map(axis => axisKey ? <AxisEvidence key={axis.key} row={row} axis={axis}/> : <details className="axis-accordion" key={axis.key}><summary>{axis.label} · {number(axis.normalized)}점</summary><AxisEvidence row={row} axis={axis}/></details>)}
      <details><summary>데이터 출처·기준일</summary><p>채점 시각 {row.result.computed_at} · 기준분포 {row.inputs?.reference?.snapshot ?? '미확인'}</p><ValueTree value={row.inputs?.primary?.meta.sources}/></details>
    </>}
  </section>;
}
