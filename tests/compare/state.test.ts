import { beforeEach, describe, expect, it, vi } from 'vitest';
import { delayed, lookupState, newer, timestamp } from '../../lib/compare/status';
import { useComparisonStore, acceptLookup, type NewCandidate } from '../../lib/compare/store';
import { score, reweight } from '../../lib/scoring/score';
import { academyV0 } from '../../lib/scoring/presets';
import { candidate, context, inputs, reference } from '../scoring/fixtures';
vi.mock('../../lib/supabase/session',()=>({ensureSession:vi.fn(()=>new Promise(()=>{}))}));
const value={alias:'후보',candidate,selection:{},location:{},resolved:{context}} as NewCandidate;
const result=()=>score(inputs(),inputs(1000),[],null,candidate,academyV0,reference(),context);
beforeEach(()=>{const s=useComparisonStore.getState();for(const r of s.candidates)s.remove(r.id);s.resetWeights();s.sortByScore();});
describe('comparison state',()=>{
 it('keeps order during adjustment, applies reweight on release and preserves normalized/confidence',()=>{
  const s=useComparisonStore.getState(),a=s.add(value),b=s.add(value),first=result(),second=result();
  first.axes.find(a=>a.key==='demand')!.normalized=0;second.axes.find(a=>a.key==='demand')!.normalized=100;
  s.update(a,{result:first});s.update(b,{result:second});const before=useComparisonStore.getState().order;
  s.beginAdjustment();s.setWeight('demand',0);expect(useComparisonStore.getState().order).toEqual(before);s.endAdjustment();
  const changed=reweight(second,useComparisonStore.getState().weights);expect(changed.confidence).toEqual(second.confidence);expect(changed.axes.map(a=>a.normalized)).toEqual(second.axes.map(a=>a.normalized));
 });
 it('retains manual order on adjustment and resets, and nulls all-zero totals',()=>{
  const s=useComparisonStore.getState(),a=s.add(value),b=s.add(value);s.update(a,{result:result()});s.update(b,{result:result()});s.move(b,a);
  for(const key of Object.keys(academyV0.weights) as (keyof typeof academyV0.weights)[])s.setWeight(key,0);
  expect(reweight(result(),useComparisonStore.getState().weights).total).toBeNull();s.resetWeights();expect(useComparisonStore.getState().order).toEqual([b,a]);
 });
 it('ignores wrong request ids, duplicate/out-of-order events and removed/floor-edited generations',()=>{
  const s=useComparisonStore.getState(),id=s.add(value);s.update(id,{lookupRequestId:'own'});
  const event={request_id:'own',status:'processing' as const,updated_at:'2026-10-01T00:00:00.123456Z'};
  acceptLookup(id,0,{...event,request_id:'foreign'});expect(useComparisonStore.getState().candidates[0].lookupState).toBeUndefined();
  acceptLookup(id,0,event);acceptLookup(id,0,{...event,status:'pending',updated_at:'2026-10-01T00:00:00.123455Z'});expect(useComparisonStore.getState().candidates[0].lookupState).toEqual(event);
  s.update(id,{generation:1,lookupState:undefined});acceptLookup(id,0,event);expect(useComparisonStore.getState().candidates[0].lookupState).toBeUndefined();s.remove(id);acceptLookup(id,0,event);expect(useComparisonStore.getState().candidates).toEqual([]);
 });
 it('preserves microseconds and rejects malformed payloads; delay is exactly 180s',()=>{
  expect(timestamp('2026-10-01T00:00:00.123456Z')!-timestamp('2026-10-01T09:00:00.123455+09:00')!).toBe(1n);
  const e={request_id:'x',status:'ready' as const,updated_at:'2026-10-01T00:00:00Z'};expect(newer(e,e)).toBe(false);expect(lookupState({...e,updated_at:'bad'})).toBeNull();expect(lookupState({...e,status:'invalid'})).toBeNull();expect(delayed(0,179999)).toBe(false);expect(delayed(0,180000)).toBe(true);
 });
});
