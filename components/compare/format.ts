import type { AxisResult } from '../../lib/scoring/types';
export const number = (value: number | null | undefined, digits = 2) => value == null ? '—'
  : value.toLocaleString('ko-KR', { maximumFractionDigits: digits });
const reasons: Record<string, string> = {
  raw_missing: '원천 데이터가 없습니다', percentile_data_unavailable: '기준 분포를 확인할 수 없습니다',
  outside_seoul: '서울 밖 지역입니다', inside_seoul_unknown: '서울 경계를 확인할 수 없습니다',
  rent_input_missing: '임대료가 입력되지 않았습니다', rent_range_unconfigured: '임대료 채점 범위는 v0.3에서 미확정입니다',
  exposure_worker_failed: '노출 계산에 실패했습니다', exposure_worker_pending: '노출 계산 중입니다',
  visibility_worker_not_provided: '노출 계산 입력이 없습니다', buildings_not_loaded: '이 지역은 건물 데이터가 아직 없습니다',
  building_data_unavailable: '건물 데이터가 없습니다', building_lookup_pending: '건축물대장을 확인 중입니다',
  candidate_footprint_missing_self_occlusion_unaccounted: '후보 도형이 없어 자기 건물 차폐를 반영하지 못했습니다',
  requested_floor_use_unknown: '요청 층의 용도가 확인되지 않았습니다', exclusive_area_unknown: '전용면적이 입력되지 않았습니다',
  requested_floor_use_allowed: '요청 층에서 등록 가능 용도가 관측됐습니다', requested_floor_use_disallowed: '등록 불가 위험 용도가 관측됐습니다',
  harmful_use_room_distances_unverified: '유해 용도와의 실간 거리는 미확인입니다',
  harmful_use_gross_area_below_1650: '유해 용도가 있고 건물 연면적이 1,650㎡ 미만입니다',
  harmful_use_gross_area_unknown: '유해 용도가 있으나 건물 연면적이 미확인입니다',
};
export function reason(value: string): string {
  const code = value.replace(/ \(-\d+\)$/, ''), suffix = value.slice(code.length);
  return reasons[code] ? `${reasons[code]}${suffix} (${code})` : value;
}
export function rawSummary(axis: AxisResult): string {
  const v = axis.evidence.values;
  if (axis.key === 'transit' && axis.normalized !== null && Array.isArray(v.components)) {
    const station = v.components.find(c => c.key === 'transit.nearest_subway_m');
    const bus = v.components.find(c => c.key === 'transit.bus_stops');
    return `최근접 역 ${number(station?.raw, 0)}m · 버스 ${number(bus?.raw, 0)}곳`;
  }
  if (axis.raw === null) return reason(axis.missing_reason ?? '원시값 없음');
  if (axis.key === 'cluster') return `학원 ${number(v.n_field as number, 0)}곳`;
  if (axis.key === 'exposure') return `가시 비율 ${number(axis.raw * 100, 1)}%`;
  if (axis.key === 'building') return `규칙 합 ${number(axis.raw)}점`;
  return `원시값 ${number(axis.raw)}`;
}
