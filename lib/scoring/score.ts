import { axis, axisKeys, clamp, evidence, percentileAxes, rentAxis, exposureAxis } from './axes.ts';
import { buildingAxis } from './building.ts';
import { FOOTPRINT_MISSING, EXPOSURE_LIMITATION } from '../visibility/types.ts';
import { extractReferenceRaw, parseReferenceInputs } from './raw.ts';
import type { AxisResult, Candidate, ScoreContext, ScoreInputs, ScoreReference, ScoreResult,
  ScoringPreset, ExposureInput, Weights } from './types.ts';

function validateWeights(weights: Weights): void {
  if (axisKeys.some(key => !Number.isFinite(weights[key]) || weights[key] < 0))
    throw new Error('Weights must be finite and nonnegative for all axes');
}
function validateCandidate(candidate: Candidate): void {
  if (!Number.isFinite(candidate.lat) || !Number.isFinite(candidate.lng) ||
    candidate.lat < 33 || candidate.lat > 39 || candidate.lng < 124 || candidate.lng > 132 ||
    !Number.isInteger(candidate.floor) || candidate.floor === 0 || candidate.floor < -100 || candidate.floor > 200)
    throw new Error('Invalid candidate coordinate/floor');
  for (const key of ['exclusive_area_m2', 'deposit_krw', 'monthly_rent_krw', 'maintenance_krw'] as const) {
    const value = candidate[key];
    if (value != null && (!Number.isFinite(value) || value < 0 || (key === 'exclusive_area_m2' && value === 0)))
      throw new Error('Invalid candidate ' + key);
  }
}
/** Reuses already-normalized axes. Confidence is intentionally independent of sliders. */
export function reweight(result: ScoreResult, weights: Weights): ScoreResult {
  validateWeights(weights);
  if (result.axes.length !== axisKeys.length || axisKeys.some(k => result.axes.filter(a => a.key === k).length !== 1))
    throw new Error('ScoreResult axis contract mismatch: recompute with exposure v0.2.1');
  if (result.preset.version !== '0.2.1') throw new Error('ScoreResult model version mismatch: recompute with exposure v0.2.1');
  const copy = structuredClone(result);
  const percentileKeys = ['demand', 'flow', 'transit', 'cluster', 'environment'];
  const missing = copy.axes.filter(a => a.normalized === null && percentileKeys.includes(a.key)).length;
  const w = copy.axes.reduce((sum, a) => sum + (a.normalized === null ? 0 : weights[a.key]), 0);
  if (!Number.isFinite(w)) throw new Error('Weight sum overflow');
  for (const a of copy.axes) {
    if (a.normalized === null) {
      const note = '종합점수 계산 시 결측 축의 가중치는 점수가 있는 축에 비례 재배분한다.';
      if (!a.evidence.notes.includes(note)) a.evidence.notes.push(note);
    }
    a.weight = weights[a.key];
    a.effective_weight = a.normalized === null || w === 0 ? 0 : weights[a.key] / w * 100;
    a.contribution = a.normalized === null ? null : a.normalized * a.effective_weight / 100;
  }
  copy.total = missing >= 2 || w === 0 ? null : clamp(copy.axes.reduce((sum, a) => sum + (a.contribution ?? 0), 0));
  return copy;
}
function confidence(primary: ScoreInputs, axes: readonly AxisResult[], preset: ScoringPreset, context: ScoreContext) {
  let value = 100;
  const reasons: string[] = [];
  const deduct = (amount: number, reason: string) => { value -= amount; reasons.push(`${reason} (-${amount})`); };
  if (axes.find(a => a.key === 'exposure')?.evidence.notes.includes(FOOTPRINT_MISSING))
    deduct(5, FOOTPRINT_MISSING);
  for (const a of axes) if (a.normalized === null) deduct(preset.weights[a.key], `${a.label} 축 평가 불가: ${a.missing_reason}`);
  if (primary.flow.low_coverage) {
    const coverage = [...primary.meta.flow_coverage.weekday.coverage_ratio,
      ...primary.meta.flow_coverage.weekend.coverage_ratio].filter((v): v is number => v !== null);
    const min = coverage.length ? Math.min(...coverage) : null;
    deduct(10, `생활인구 격자 일부 비공개(최소 커버리지 ${min === null ? '미확인' : (min * 100).toFixed(1) + '%'})`);
  }
  if (primary.demand.estimated || primary.flow.estimated) deduct(5, '인구는 행정동·격자 면적 비례 추정');
  const unknown = primary.meta.height_quality.unknown_ratio;
  if (unknown !== null && unknown > .3) deduct(10, `주변 건물 ${(unknown * 100).toFixed(1)}%가 높이 미상, 노출 조건 신뢰 낮음`);
  const pending = ['pending', 'processing'].includes(primary.meta.building_lookup.status);
  if (pending) deduct(15, '건축물대장 조회 대기 중');
  else if (primary.building?.location_basis === 'footprint' && primary.building.register_pk === null)
    deduct(10, '건물 대장 미연결, 용도·승강기 미확인');
  if ((primary.transit.subway_units_missing_golden ?? 0) > 0) deduct(5, '지하철 일부 시간대 데이터 없음');
  if (context.seoul_boundary_distance_m != null && context.seoul_boundary_distance_m <= 1000)
    deduct(5, '경기 정류장 데이터 없음');
  return { value: clamp(value), reasons };
}
/** Pure ScoreResult v0.2.1. The caller owns DB, context queries, and visibility work. */
export function score(primary: ScoreInputs, school: ScoreInputs, buildings: readonly unknown[],
  visibility: ExposureInput, candidate: Candidate, preset: ScoringPreset,
  reference: ScoreReference | null, context: ScoreContext): ScoreResult {
  // Building geometries are an explicit input for the separate S2-3 worker, not a height guess.
  void buildings;
  validateCandidate(candidate); validateWeights(preset.weights);
  if (axisKeys.some(k => preset.signs[k] !== 1 && preset.signs[k] !== -1)) throw new Error('Invalid axis sign');
  if (context.seoul_boundary_distance_m != null &&
    (!Number.isFinite(context.seoul_boundary_distance_m) || context.seoul_boundary_distance_m < 0))
    throw new Error('Invalid boundary distance');
  const computed_at = context.computed_at ?? primary.meta.computed_at;
  if (typeof computed_at !== 'string' || !computed_at) throw new Error('computed_at must be injected');
  let axes: AxisResult[];
  let derived: ScoreResult['derived'] = { academy_eligible: null, academy_eligible_reasons: [] };
  const mismatch = primary.meta.schema_version !== preset.schema_version ? 'input_schema_version_mismatch' :
    primary.meta.radius_m !== preset.radius_primary_m || !preset.radii.includes(primary.meta.radius_m) ? 'input_radius_mismatch' :
    primary.meta.floor !== candidate.floor ? 'candidate_floor_mismatch' : null;
  if (mismatch) axes = axisKeys.map(k => axis(k, null, null, evidence(), mismatch));
  else {
    parseReferenceInputs(primary);
    const schoolValid = school.meta.schema_version === preset.schema_version && school.meta.radius_m === preset.school_radius_m &&
      school.meta.floor === candidate.floor;
    const missingSchool: ScoreInputs = { ...primary,
      demand: { ...primary.demand, schools: { elem: null, mid: null, high: null } },
      meta: { ...primary.meta, radius_m: preset.school_radius_m } };
    const raw = extractReferenceRaw(primary, schoolValid ? school : missingSchool, context, preset);
    if (!schoolValid) { raw.demand.value = null; raw.demand.notes = ['school_input_contract_mismatch']; }
    axes = percentileAxes(primary, schoolValid ? school : missingSchool, raw, preset, reference, context);
    if (!schoolValid) axes.find(a => a.key === 'demand')!.missing_reason = 'school_input_contract_mismatch';
    const building = buildingAxis(primary, candidate);
    derived = { academy_eligible: building.eligible, academy_eligible_reasons: building.reasons };
    axes.push(exposureAxis(visibility), building.axis);
    const orient = (a: AxisResult) => {
      if (a.normalized !== null && preset.signs[a.key] === -1) {
        a.normalized = 100 - a.normalized; a.evidence.rules_applied.push('preset_sign_negative');
      }
    };
    axes.forEach(orient);
    const rent = rentAxis(primary, candidate, preset, context, axes.find(a => a.key === 'demand')!, axes.find(a => a.key === 'flow')!);
    orient(rent); axes.push(rent);
    axes.sort((a, b) => axisKeys.indexOf(a.key) - axisKeys.indexOf(b.key));
  }
  const exposure = axes.find(a => a.key === 'exposure')!;
  if (!exposure.evidence.notes.includes(EXPOSURE_LIMITATION)) exposure.evidence.notes.push(EXPOSURE_LIMITATION);
  return reweight({ preset: { id: preset.id, version: preset.version }, inputs_schema_version: primary.meta.schema_version,
    total: null, confidence: confidence(primary, axes, preset, context), axes, derived, computed_at }, preset.weights);
}
