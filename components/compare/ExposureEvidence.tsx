'use client';
import type {ComparisonCandidate} from '../../lib/compare/store';
import {sampleLabel} from '../../lib/map/exposure';
import {EXPOSURE_LIMITATION} from '../../lib/visibility/types';
import {useExposureLink} from './ExposureLink';
import {number,reason} from './format';
export function ExposureEvidence({row,interactive=true}:{row:ComparisonCandidate;interactive?:boolean}) {
 const link=useExposureLink(), result=row.inputs?.exposure, samples=result?.samples?.filter(s=>s.group==='ring')??[], summary=result?.summary?.ring;
 const axis=row.result?.axes.find(a=>a.key==='exposure'), building=row.result?.axes.find(a=>a.key==='building');
 const value=(key:string)=>typeof axis?.evidence.values[key]==='number'?axis.evidence.values[key] as number:null;
 const selected=samples.find(s=>s.id===link.sampleId), blocker=row.inputs?.scene?.buildings.find(b=>b.id===selected?.building_id);
 return <div className="exposure-explanation" data-testid="exposure-explanation">
  <p><strong>비가중 가시점 {summary&&summary.generated>0?`${summary.visible}/${summary.generated}`:'미확인'}</strong> · 가중 가시율 {value('visible_ratio')===null?'미확인':`${number(value('visible_ratio')!*100,6)}%`} · 주목도 Y 적용 {number(axis?.normalized,6)}점</p>
  <p>{row.candidate.floor}층 · 주목도 계수 {number(value('floor_attention_coefficient'),2)} (모델 가정) · 목표 높이 {number(row.inputs?.exposure?.evidence?.values.target_height_m as number|undefined,1)}m</p>
  {row.candidate.floor<0&&<p>지하: 입구 간판 기준 노출 · 목표 2.0m·주목도 0.8 가정 · {building?.evidence.rules_applied.includes('R7:-25')?'건물 R7 −25 적용':'건물 보정은 대장 상태 근거 참조'}</p>}
  {typeof building?.evidence.values.floor_elevator_row==='string'&&<p>건물 적용 행: {String(building.evidence.values.floor_elevator_row)}</p>}
  {row.result?.confidence.reasons.filter(r=>r.includes('승강기')||r.includes('후보 도형')||r.includes('candidate_footprint')).map(r=><p key={r}>{reason(r)}</p>)}
  {building?.status==='pending'&&<p>건축물대장 조회 대기 중 · 건물 60점 유지·신뢰도 −15</p>}
  {building?.evidence.values.elevator_unknown_confidence_penalty===5&&<p>승강기 미확인: 층×승강기 보정 0 · 신뢰도 −5 (0대로 간주하지 않음)</p>}
  {row.inputs?.scene?.candidate_building_id===null&&<p>후보 도형 없음 · 자기 건물 차폐 미반영{row.result?.confidence.reasons.includes('candidate_footprint_missing_self_occlusion_unaccounted')?' · 신뢰도 −5':''}</p>}
  {summary&&summary.generated>0&&<p>이동 {summary.moved}점 · 제외 {summary.excluded}점/{summary.generated}점 ({number(summary.excluded_ratio*100,2)}%) · 제외는 차폐 수에 넣지 않음. 이동 후에도 원래 링 가중치 100/d 유지.</p>}
  <p>{EXPOSURE_LIMITATION}</p>
  {!samples.length&&<p>시각화 자료 없음/계산 중 · 저장 점수만으로 샘플점을 만들지 않습니다.</p>}
  {!link.desktop&&<p>샘플점 지도는 데스크톱에서 확인</p>}
  {selected&&<div data-testid="exposure-selected-sample" data-sample-id={selected.id} tabIndex={-1}>
   <strong>{sampleLabel(selected)}</strong><p>이동 {number(selected.moved_m,3)}m · 가중치 {number(selected.weight,6)}</p>
   {selected.status==='excluded'?<p>건물 밖으로 30m 이내 이동 불가 또는 이동 방향을 정할 수 없어 제외 · 광선 없음</p>:<p>관측 1.5m → 샘플별 후보 외벽 목표점. {selected.status==='blocked'?`Worker가 기록한 차폐 건물: ${selected.building_id} (가장 가까운 건물이라는 뜻은 아님)`:'차폐 건물 없음'}</p>}
   {blocker&&<p>{blocker.height_m}m · {blocker.height_source==='unknown'?'높이 미상 4m 가정':blocker.estimated?'추정 높이':'원천 높이'} · {blocker.source}</p>}
  </div>}
  {interactive&&link.desktop&&samples.length>0&&<details className="sample-evidence-list"><summary>링·방향별 108점 근거</summary><p>EPSG:5186 격자 북0°·동90°·시계방향. 실제 보행 동선은 아닙니다.</p>{[20,40,60].map(radius=><details key={radius}><summary>{radius}m 링 · 가시 {samples.filter(s=>s.radius_m===radius&&s.status==='visible').length}/36</summary><ul>{samples.filter(s=>s.radius_m===radius).sort((a,b)=>a.bearing_deg!-b.bearing_deg!).map(s=><li key={s.id}>{link.desktop?<button data-sample-evidence={s.id} aria-pressed={s.id===link.sampleId} onClick={()=>link.pick(s.id,'evidence')}>{sampleLabel(s)}{s.moved_m>0?' · 이동':''}</button>:<span>{sampleLabel(s)} · 이동 {number(s.moved_m,2)}m</span>}</li>)}</ul></details>)}</details>}
 </div>;
}
