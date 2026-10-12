import type { GeometryItem } from './buildings';
import type { SampleResult, VisibilityScene } from '../visibility/types';
export type Position = [number, number, number];
export interface DisplaySample { sample: SampleResult; point: Position; original: Position; target: Position | null }
export interface ExposureGeometry { samples: DisplaySample[]; rings: {radius: number; path: Position[]}[] }
/** Project recorded worker coordinates only; no resampling or second raycast. */
export function exposureGeometryItems(samples: readonly SampleResult[]): GeometryItem[] {
  const rings = samples.filter(s => s.group === 'ring');
  const items: GeometryItem[] = [];
  for (const s of rings) for (const [suffix, point] of [['point',s.point],['original',s.original_point],['target',s.target]] as const) {
    if (point) items.push({id:`${s.id}:${suffix}`,geometry:{type:'Point',coordinates:[...point]}});
  }
  for (const radius of [20,40,60]) {
    const points = rings.filter(s=>s.radius_m===radius).sort((a,b)=>a.bearing_deg!-b.bearing_deg!).map(s=>[...s.original_point]);
    if (points.length) items.push({id:`ring:${radius}`,geometry:{type:'LineString',coordinates:[...points,points[0]]}});
  }
  return items;
}
export function exposureGeometry(scene: VisibilityScene, samples: readonly SampleResult[], projected: GeometryItem[]): ExposureGeometry {
  const expected = exposureGeometryItems(samples);
  if (projected.length !== expected.length || projected.some((p,i)=>p.id!==expected[i].id || p.geometry.type!==expected[i].geometry.type)) throw new Error('노출 좌표 변환 결과가 채점 자료와 다릅니다.');
  const byId = new Map(projected.map(p=>[p.id,p.geometry]));
  const point = (id:string,z:number):Position => { const g=byId.get(id); if (g?.type!=='Point') throw new Error('샘플 좌표가 없습니다.'); return [g.coordinates[0],g.coordinates[1],z]; };
  const z = scene.floor < 0 ? 2 : (scene.floor-1)*3.3+2;
  return {samples:samples.filter(s=>s.group==='ring').map(sample=>({sample,point:point(`${sample.id}:point`,1.5),original:point(`${sample.id}:original`,1.5),target:sample.target ? point(`${sample.id}:target`,z) : null})),
    rings:[20,40,60].flatMap(radius=>{const g=byId.get(`ring:${radius}`);return g?.type==='LineString' ? [{radius,path:g.coordinates.map(p=>[p[0],p[1],1.5] as Position)}] : [];})};
}
export const sampleStatus = {visible:'가시',blocked:'차폐',excluded:'제외'};
export function sampleLabel(s:SampleResult) { return `${s.radius_m}m · ${s.bearing_deg}° · ${sampleStatus[s.status]}`; }
