import { referencePercentile } from './percentile.ts';
import { EXPOSURE_LIMITATION } from '../visibility/types.ts';
import type { ReferenceKey, ReferenceRaw } from './raw.ts';
import type { AxisKey, AxisResult, Candidate, Evidence, ScoreContext, ScoreInputs,
  ScoreReference, ScoringPreset, ExposureInput } from './types.ts';

export const labels: Readonly<Record<AxisKey, string>> = Object.freeze({
  demand: '수요', flow: '유동', transit: '교통', cluster: '학원 집적',
  exposure: '건물 앞 도로·맞은편에서의 간판 노출', building: '건물 적합성', environment: '환경', rent_efficiency: '임대료 효율',
});
export const axisKeys = Object.freeze(Object.keys(labels) as AxisKey[]);
export const clamp = (v: number) => Math.max(0, Math.min(100, v));
export function evidence(values: Record<string, unknown> = {}): Evidence {
  return { values, percentile: null, rules_applied: [], reference: null, notes: [] };
}
export function axis(key: AxisKey, raw: number | null, normalized: number | null,
  e: Evidence, reason: string | null = null, status: AxisResult['status'] = normalized === null ? 'missing' : 'scored'): AxisResult {
  return { key, label: labels[key], weight: 0, effective_weight: 0, status,
    raw, normalized, contribution: null, evidence: e, missing_reason: reason };
}
export function percentileAxes(primary: ScoreInputs, school: ScoreInputs, raw: ReferenceRaw,
  preset: ScoringPreset, reference: ScoreReference | null, context: ScoreContext): AxisResult[] {
  const p = (key: ReferenceKey, direction: 1 | -1 = 1) =>
    referencePercentile(key, raw[key].value, primary, school, preset, reference, direction);
  const single = (key: 'demand' | 'flow', values: Record<string, unknown>) => {
    const found = p(key), e = evidence(values);
    e.percentile = found.value; e.reference = found.reference; e.notes.push(...raw[key].notes);
    return axis(key, raw[key].value, found.value, e, found.reason);
  };
  const demand = single('demand', { population: {
    pop_5_9: primary.demand.pop_5_9, pop_10_14: primary.demand.pop_10_14,
    pop_15_18: primary.demand.pop_15_18 }, schools_1km: { ...school.demand.schools },
    coefficients: { ...preset.demand_coef }, estimated: primary.demand.estimated });
  demand.evidence.rules_applied.push('weighted_population_plus_1km_schools');
  const flow = single('flow', { weekday: primary.flow.weekday.golden_avg_pop,
    weekend: primary.flow.weekend.golden_avg_pop, low_coverage: primary.flow.low_coverage,
    coverage: structuredClone(primary.meta.flow_coverage), estimated: primary.flow.estimated });
  flow.evidence.rules_applied.push('weekday_0.7_weekend_0.3_renormalize_available');
  if (primary.flow.low_coverage) flow.evidence.notes.push('coverage_below_80_percent_no_imputation');
  const map = primary.compete.academies_by_field;
  const pops = [primary.demand.pop_5_9, primary.demand.pop_10_14, primary.demand.pop_15_18];
  const saturation = raw['cluster.saturation'].value, satPct = p('cluster.saturation');
  const ce = evidence({ field: preset.cluster_field,
    n_field: map === null ? null : map[preset.cluster_field] ?? 0,
    students: pops.some(v => v === null) ? null : pops.reduce<number>((a, b) => a + b!, 0),
    saturation, saturation_level: saturation === null ? null : saturation >= preset.saturation.high ? 'high' :
      saturation >= preset.saturation.mid ? 'mid' : 'low',
    saturation_percentile: satPct.value, saturation_reference: satPct.reference,
    saturation_thresholds: { ...preset.saturation } });
  const scale = preset.cluster_scale;
  if (!Number.isFinite(scale.p50) || !Number.isFinite(scale.upper) || scale.upper <= scale.p50)
    throw new Error('Invalid cluster fixed scale');
  const clusterRaw = raw.cluster.value;
  const linear = clusterRaw === null ? null : (clusterRaw - scale.p50) / (scale.upper - scale.p50) * 100;
  ce.values.fixed_scale = { ...scale, method: 'percentile_cont', reference_version: preset.reference_version };
  ce.values.unclamped_score = linear;
  ce.notes.push(...raw.cluster.notes);
  const cluster = axis('cluster', clusterRaw, linear === null ? null : clamp(linear), ce,
    clusterRaw === null ? 'raw_missing' : null);
  cluster.evidence.rules_applied.push('fixed_linear_p50_zero_upper_100');
  cluster.evidence.rules_applied.push('log1p_academy_count', 'saturation_evidence_only');
  cluster.evidence.notes.push('이 지표는 반경 내 거주 학령인구 대비이며, 대치동처럼 외부 통학 수요가 큰 곳은 실제 공급 과잉과 다를 수 있다');
  if (saturation !== null && saturation >= preset.saturation.high)
    cluster.evidence.notes.push('경쟁 포화 구간: 이 자리는 검증된 목이지만 신규 진입 시 차별화가 필요');
  if (satPct.reason) cluster.evidence.notes.push('saturation:' + satPct.reason);

  const components = ([['transit.nearest_subway_m', .5, -1],
    ['transit.subway_boardings_golden', .3, 1], ['transit.bus_stops', .2, 1]] as const)
    .map(([key, weight, direction]) => ({ key, weight, raw: raw[key].value, ...p(key, direction) }));
  const available = components.filter(c => c.value !== null), w = available.reduce((a, c) => a + c.weight, 0);
  const transitScore = w ? available.reduce((a, c) => a + c.value! * c.weight / w, 0) : null;
  const te = evidence({ components, subway_units_missing_golden: primary.transit.subway_units_missing_golden,
    seoul_boundary_distance_m: context.seoul_boundary_distance_m ?? null });
  te.rules_applied.push('subway_distance_down_0.5_boardings_0.3_bus_0.2_renormalize');
  te.notes.push(...raw['transit.nearest_subway_m'].notes, '교통은 요일 구분 없는 일평균; 생활인구와 시간 기준이 다름');
  for (const c of components) if (c.reason) te.notes.push(c.key + ':' + c.reason);
  if (context.seoul_boundary_distance_m == null) te.notes.push('서울 경계 거리 미확인');
  else if (context.seoul_boundary_distance_m <= 1000) te.notes.push('경기 정류장 데이터 없음');
  const transit = axis('transit', null, transitScore, te, transitScore === null ? 'all_transit_components_missing' : null);

  const vitality = p('environment.stores_total'), stores = primary.market.stores_total;
  const categories = primary.market.stores_by_lcls;
  const i1 = categories === null ? null : categories.I1 ?? 0;
  const share = stores === null || categories === null ? null : stores === 0 ? 0 : i1! / stores;
  const penalty = share === null ? null : Math.min(25, 500 * share);
  const ee = evidence({ stores_total: stores, stores_by_lcls: categories && { ...categories },
    share_I1: share, penalty, vitality: vitality.value });
  ee.percentile = vitality.value; ee.reference = vitality.reference;
  ee.rules_applied.push('clamp_0.8_vitality_minus_min25_500_lodging_share_plus20');
  const env = vitality.value === null || penalty === null ? null : clamp(.8 * vitality.value - penalty + 20);
  const environment = axis('environment', stores, env, ee, vitality.reason ?? (categories === null ? 'store_categories_missing' : null));
  return [demand, flow, transit, cluster, environment];
}
export function exposureAxis(visibility: ExposureInput): AxisResult {
  const e = evidence(visibility?.evidence ? structuredClone(visibility.evidence.values) : {});
  e.notes.push(...(visibility?.evidence?.notes ?? []));
  if (!e.notes.includes(EXPOSURE_LIMITATION)) e.notes.push(EXPOSURE_LIMITATION);
  if (visibility?.status === 'ready') {
    if (visibility.model_version !== '0.2.2') return axis('exposure', null, null, e, 'exposure_model_version_mismatch');
    if (!Number.isFinite(visibility.visible_ratio) || visibility.visible_ratio < 0 || visibility.visible_ratio > 1)
      throw new Error('Invalid visible_ratio');
    e.values.visible_ratio = visibility.visible_ratio;
    e.rules_applied.push('ring_visible_ratio_times100');
    return axis('exposure', visibility.visible_ratio, visibility.visible_ratio * 100, e);
  }
  const reason = visibility?.reason ?? 'exposure_worker_pending';
  return axis('exposure', null, null, e, reason, visibility?.status ?? 'pending');
}
export function rentAxis(primary: ScoreInputs, candidate: Candidate, preset: ScoringPreset,
  context: ScoreContext, demand: AxisResult, flow: AxisResult): AxisResult {
  const r = primary.rent, code = primary.meta.legal_dong_code;
  const name = code === null ? null : context.legal_dong_names?.[code] ?? code;
  const e = evidence({ legal_dong: name, legal_dong_code: code, floor: candidate.floor,
    trade_building_type: r.trade_building_type, trade_sample_count: r.trade_sample_count,
    trade_median_per_m2_krw: r.trade_median_per_m2,
    trade_median_per_m2_manwon: r.trade_median_per_m2 === null ? null : r.trade_median_per_m2 / 10000,
    survey_rent_per_m2: r.survey_rent_per_m2, survey_vacancy: r.survey_vacancy,
    survey_building_class: r.survey_building_class, rent_level: r.rent_level,
    survey_by_building_class: structuredClone(r.survey_by_building_class),
    exclusive_area_m2: candidate.exclusive_area_m2 ?? null, deposit_krw: candidate.deposit_krw ?? null,
    monthly_rent_krw: candidate.monthly_rent_krw ?? null, maintenance_krw: candidate.maintenance_krw ?? null });
  e.notes.push('매매 실거래와 임대동향은 근거 전용; 매매→임대 환산 없음');
  const costs = [candidate.monthly_rent_krw, candidate.maintenance_krw, candidate.deposit_krw];
  if (costs.some(v => v == null) || candidate.exclusive_area_m2 == null)
    return axis('rent_efficiency', null, null, e, 'user_rent_inputs_missing');
  const monthly = costs[0]! + costs[1]! + costs[2]! * .05 / 12;
  const perM2 = monthly / candidate.exclusive_area_m2;
  if (!Number.isFinite(monthly) || !Number.isFinite(perM2)) throw new Error('Rent arithmetic overflow');
  e.values.monthly_total = monthly; e.values.rent_per_m2 = perM2;
  if (perM2 === 0) return axis('rent_efficiency', null, null, e, 'zero_rent_denominator');
  if (demand.normalized === null || flow.normalized === null)
    return axis('rent_efficiency', null, null, e, 'demand_or_flow_missing');
  const value = (demand.normalized + flow.normalized) / 2 / perM2;
  e.values.value = value;
  if (preset.rent_range === null) return axis('rent_efficiency', value, null, e, 'rent_range_uncalibrated');
  const { lo, hi } = preset.rent_range;
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) throw new Error('Invalid rent range');
  e.rules_applied.push('deposit_annual_0.05_monthly_then_linear_range');
  return axis('rent_efficiency', value, clamp(100 * (value - lo) / (hi - lo)), e);
}
