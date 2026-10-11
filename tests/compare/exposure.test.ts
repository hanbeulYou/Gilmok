import {describe,it,expect} from 'vitest';
import {exposureGeometryItems,exposureGeometry} from '../../lib/map/exposure';
import {computeVisibility} from '../../lib/visibility/compute';
import {scene as makeScene,building,rectangle} from '../visibility/fixtures';
import type {GeometryItem} from '../../lib/map/buildings';
const scene=makeScene();
describe('exposure display contract',()=>{
 it('preserves all 108 statuses, recorded blockers, moved positions, bearing and original weights',()=>{
  const input={...scene,buildings:[building('wall',rectangle(-8,10,8,35),9)]};const r=computeVisibility(input);const before=JSON.stringify(r);const items=exposureGeometryItems(r.samples);const data=exposureGeometry(input,r.samples,items);
  expect(data.samples).toHaveLength(108);expect(data.rings.map(r=>r.radius)).toEqual([20,40,60]);expect(data.rings.every(r=>r.path.length===37)).toBe(true);
  const north=data.samples.find(p=>p.sample.id==='ring:0:20')!;expect(north.sample.moved_m).toBeGreaterThan(0);expect(north.sample.weight).toBe(5);expect(north.point).toEqual([...north.sample.point,1.5]);expect(north.original).toEqual([0,20,1.5]);
  expect(data.samples.map(s=>s.sample)).toEqual(r.samples.filter(s=>s.group==='ring'));expect(JSON.stringify(r)).toBe(before);
 });
 it('uses each recorded target and basement entrance 2m; excluded points have no target',()=>{
  const input={...scene,floor:-1,buildings:[building('wall',rectangle(-100,-100,100,100))]};const r=computeVisibility(input);const data=exposureGeometry(input,r.samples,exposureGeometryItems(r.samples));expect(data.samples.every(s=>s.target===null)).toBe(true);
  const clear=computeVisibility({...scene,floor:-1});const basement=exposureGeometry({...scene,floor:-1},clear.samples,exposureGeometryItems(clear.samples));expect(basement.samples.every(s=>s.target?.[2]===2)).toBe(true);
  const third=exposureGeometry(scene,clear.samples,exposureGeometryItems(clear.samples));expect(third.samples.every(s=>s.target?.[2]===8.6)).toBe(true);
 });
 it('never fabricates points from a score and rejects mismatched projection IDs',()=>{
  expect(exposureGeometryItems([])).toEqual([]);const r=computeVisibility(scene),items=exposureGeometryItems(r.samples);
  expect(()=>exposureGeometry(scene,r.samples,items.slice(1))).toThrow();
  const wrong=structuredClone(items);wrong[0].id='wrong';expect(()=>exposureGeometry(scene,r.samples,wrong)).toThrow();
  const bad:GeometryItem[]=[{id:items[0].id,geometry:{type:'LineString',coordinates:[[1,2],[3,4]]}},...items.slice(1)];expect(()=>exposureGeometry(scene,r.samples,bad)).toThrow();
 });
});
