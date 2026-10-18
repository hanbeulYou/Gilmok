import type { ComparisonCandidate } from '../compare/store';
import type { AcademyLayerRequest, AcademyLayer } from './academies';

export function academyRequest(row?: ComparisonCandidate): AcademyLayerRequest | null {
  const primary = row?.inputs?.primary;
  const values = row?.result?.axes.find(axis => axis.key === 'cluster')?.evidence.values;
  const radius = primary?.meta.radius_m, n = values?.n_field, field = values?.field;
  const source = primary?.meta.sources.academies;
  if (!row || row.refreshing || !['scored','scored_provisional'].includes(row.stage) || !source ||
      (radius !== 800 && radius !== 1000) || typeof n !== 'number' || !Number.isInteger(n) || n < 0 || typeof field !== 'string') return null;
  return { lat: row.candidate.lat, lng: row.candidate.lng, radius_m: radius, field,
    expected_source: source, expected_same_field_count: n };
}
export const academyUnavailable: Record<Exclude<AcademyLayer['status'], 'ready'>, string> = {
  too_dense: '학원이 밀집해 응답 용량 한도를 넘었습니다. 일부만 표시하지 않습니다. 반경 학원 수는 채점 근거에서 확인하세요.',
  coordinate_replacement_pending: '학원 좌표 교체·검증이 진행 중입니다. 게시가 완료되면 점을 표시합니다.',
  source_mismatch: '채점과 학원 지도의 데이터 기준이 다릅니다. 후보를 다시 채점해 주세요.',
  outside_coverage: '이 후보는 학원 지도 제공 범위(서울) 밖에 있습니다.',
};
