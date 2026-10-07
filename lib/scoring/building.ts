import { axis, clamp, evidence } from './axes.ts';
import type { Candidate, ScoreInputs } from './types.ts';

const compact = (v: string | null | undefined) => (v ?? '').replace(/\s/g, '');
export const ELEVATOR_UNKNOWN = '승강기 미확인(대장 값 없음)';
export function buildingAxis(inputs: ScoreInputs, candidate: Candidate) {
  const b = inputs.building, status = inputs.meta.building_lookup.status;
  const e = evidence({ building: b === null ? null : structuredClone(b),
    requested_floor: candidate.floor, exclusive_area_m2: candidate.exclusive_area_m2 ?? null,
    building_lookup_status: status });
  let eligible: boolean | null = null;
  const reasons: string[] = [];
  const finish = (raw: number | null, reason: string | null = null, pending = false) => ({
    axis: axis('building', raw, raw === null ? null : clamp(raw), e, reason,
      pending ? 'pending' : raw === null ? 'missing' : 'scored'),
    eligible, reasons,
  });
  if (status === 'pending' || status === 'processing') {
    e.notes.push('대장 조회 대기 중'); reasons.push('register_lookup_pending');
    e.rules_applied.push('building_pending_hold60');
    return finish(60, null, true);
  }
  if (b === null || (b.location_basis === null && b.id === null && b.register_pk === null)) { reasons.push('candidate_building_missing'); return finish(null, 'candidate_building_missing'); }
  const f = candidate.floor, passenger = b.elevators.passenger;
  if (passenger === null) {
    e.notes.push(ELEVATOR_UNKNOWN);
    if (f >= 3) e.values.elevator_unknown_confidence_penalty = 5;
  }
  let raw = 60, r1 = 0;
  const apply = (rule: string, delta: number) => { raw += delta; e.rules_applied.push(`${rule}:${delta >= 0 ? '+' : ''}${delta}`); };
  const applyHarmful = () => {
    const harmful = b.all_floors.filter(row => /(유흥주점|단란주점|숙박|노래연습장|무도)/.test(compact(row.use_name)));
    e.values.harmful_floor_uses = structuredClone(harmful);
    if (harmful.length) {
      apply('R6', -40);
      if (b.gross_area !== null && b.gross_area < 1650) {
        eligible = false; reasons.push('harmful_use_gross_area_below_1650');
      } else {
        if (eligible !== false) eligible = null;
        reasons.push(b.gross_area === null ? 'harmful_use_gross_area_unknown' : 'harmful_use_room_distances_unverified');
      }
      e.notes.push('R6: 실간 수평·상하 거리는 v0에서 계산하지 않음');
    }
  };
  if (b.floor_use === null || b.floor_use.length === 0) {
    e.notes.push('요청 층 용도 미확인: 60점 보류, 관측된 R6 유해업소만 반영');
    reasons.push('requested_floor_use_unknown');
    e.rules_applied.push('floor_use_missing_hold60');
    applyHarmful();
    return finish(raw, null, true);
  }
  const uses = b.floor_use?.map(f => compact(f.use_name) + ' ' + compact(f.other_use)).join(' ') ?? '';
  const educationCode = b.floor_use?.some(f => f.use_code === '10003') ?? false;
  const education = uses.includes('교육연구시설') || educationCode;
  if (educationCode) e.notes.push('R1: 요청 층 용도 코드 10003(교육연구시설군 학원) 확인');
  if (uses.includes('제2종근린생활시설') || education) {
    r1 = 25; apply('R1', r1); eligible = true; reasons.push('requested_floor_use_allowed');
  } else if (/(제1종근린생활시설|주거|주택|아파트|공업|공장|창고)/.test(uses)) {
    r1 = -40; apply('R1', r1); eligible = false; reasons.push('requested_floor_use_disallowed');
  } else { e.notes.push('R1: 요청 층의 등록 가능 용도 미확인'); reasons.push('requested_floor_use_unknown'); }
  if (candidate.exclusive_area_m2 == null) {
    if (!education) { reasons.push('exclusive_area_unknown'); if (eligible === true) eligible = null; }
  } else if (candidate.exclusive_area_m2 >= 500 && !education) {
    apply('R2', -30); eligible = false; reasons.push('exclusive_area_requires_education_use');
  }
  const floorBand = f === 1 ? '1층' : f === 2 ? '2층' : f === 3 ? '3층' : f <= 5 ? '4~5층' : '6층 이상';
  const adjustment = f === 1 ? 10 : f === 2 ? 5 : passenger === null ? 0 :
    passenger === 0 ? (f === 3 ? -5 : f <= 5 ? -15 : -30) : (f === 3 ? 5 : f <= 5 ? 0 : -5);
  e.values.passenger_elevators = passenger;
  e.values.floor_elevator_row = f < 0 ? '지하층 · R7만 적용' : passenger === null ?
    `${floorBand} · 승용승강기 미확인 (${f <= 2 ? '승강기와 무관' : '보정 보류'})` : `${floorBand} · 승용승강기 ${passenger === 0 ? '없음' : '있음'}`;
  e.values.floor_adjustment = f < 0 ? -25 : adjustment;
  if (f > 0) {
    apply('R3_R4', adjustment);
    if (passenger === null && f >= 3) e.notes.push('통합표 보정 0점 보류(승강기 0대로 대체하지 않음)');
  }
  const academyFloors = new Set(b.all_floors.filter(row =>
    (row.floor_kind === '10' || row.floor_kind === '20') && row.floor_no !== null &&
    row.floor_no !== 0 && row.floor_no !== f && compact(row.use_name).includes('학원'))
    .map(row => `${row.floor_kind}:${row.floor_no}`));
  e.values.other_academy_floor_count = academyFloors.size;
  const r5 = 5 * Math.min(academyFloors.size, 3);
  apply('R5', r5);
  const combinedBonus = r1 + r5;
  e.values.r1_r5_before_cap = combinedBonus;
  e.values.r1_r5_after_cap = Math.min(30, combinedBonus);
  e.values.r1_r5_cap = 30;
  if (combinedBonus > 30) apply('R1_R5_CAP', 30 - combinedBonus);
  applyHarmful();
  if (f < 0) apply('R7', -25);
  return finish(raw);
}
