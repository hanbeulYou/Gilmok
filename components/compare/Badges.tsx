import type { AxisResult, ScoreResult } from '../../lib/scoring/types';
import { number, reason } from './format';
export function AxisBadges({ axis, result }: { axis: AxisResult; result: ScoreResult }) {
  const v = axis.evidence.values;
  return <span className="axis-badges">
    {axis.status === 'pending' && <span className="badge pending">확인 중</span>}
    {axis.normalized === null && axis.status !== 'pending' && <span className="badge missing" title={reason(axis.missing_reason ?? '자료 없음')}>결측</span>}
    {axis.key === 'cluster' && typeof v.saturation_level === 'string' && <span
      className={`badge saturation-${v.saturation_level}`}
      title={`학생 1,000명당 학원 ${number(v.saturation as number)}곳 · 서울 상위 ${number(100 - (v.saturation_percentile as number))}%. 외부 통학 수요는 반영하지 않습니다.`}>
      포화 {({ high: '높음', mid: '보통', low: '낮음' } as Record<string, string>)[v.saturation_level] ?? v.saturation_level}</span>}
    {axis.key === 'building' && <><span className={`badge eligible-${result.derived.academy_eligible}`}>
      {result.derived.academy_eligible === true ? '등록 가능 용도' : result.derived.academy_eligible === false ? '등록 불가 위험' : '확인 필요'}</span>
      {axis.evidence.rules_applied.some(rule => rule.startsWith('R6:')) && <span className="badge warning">유해업소 동거 — 확인 필요</span>}</>}
  </span>;
}
export function Confidence({ value, onClick }: { value: number; onClick: () => void }) {
  return <button className="confidence" onClick={onClick} aria-label={`신뢰도 ${value}점 근거`}>
    <svg width="40" height="40" viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="16" fill="none" stroke="#dce6e3" strokeWidth="4"/>
      <circle cx="20" cy="20" r="16" fill="none" stroke="#0f766e" strokeWidth="4" pathLength="100"
        strokeDasharray={`${value} 100`} transform="rotate(-90 20 20)"/>
      <text x="20" y="24" textAnchor="middle" fontSize="11" fill="currentColor">{value}</text></svg><span>신뢰도</span>
  </button>;
}
