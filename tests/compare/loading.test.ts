import { describe, expect, it, vi } from 'vitest';
import type { SupabaseClient } from '@supabase/supabase-js';
import { loadCandidate, type LoadProgress } from '../../lib/compare/load-candidate';
import { candidate, context, inputs, reference } from '../scoring/fixtures';
import { scene } from '../visibility/fixtures';
import { percentile } from '../../lib/scoring/percentile';
import type { ExposureInput, PercentileReference } from '../../lib/scoring/types';
const resolved = { status: 'footprint_missing' as const, context, building: null };
const ready: ExposureInput = {status:'ready',model_version:'0.2.2',visible_ratio:.5};
function backend() {
  let primary=inputs(); let fail='';
  const rpc=vi.fn((name: string, args: Record<string, unknown>)=>({abortSignal: async()=>{
    if(name===fail) {fail='';return {data:null,error:{message:'fixture failure'}};}
    if(name==='score_inputs') return {data:args.radius_m===800?structuredClone(primary):inputs(1000),error:null};
    if(name==='exposure_inputs_v022') return {data:scene(),error:null};
    const {distributions,...metadata}=reference(primary);
    const raw=args.requested_raw as Record<string,number|null>;
    const data: PercentileReference={...metadata,kind:'percentiles',percentiles:distributions.filter(d=>d.key!=='cluster').map(d=>({
      key:d.key,radius_m:800,raw:raw[d.key],percentile:percentile(d.values,raw[d.key]),cell_count:d.cell_count,population_size:d.values.length,histogram:{min:1,max:3,bins:[]},
    }))};
    return {data,error:null};
  }}));
  return {client:{rpc} as unknown as SupabaseClient,rpc,primary:(value:typeof primary)=>{primary=value;},fail:(name:string)=>{fail=name;}};
}
describe('incremental comparison loading',()=>{
 it('publishes provisional score, then refreshes only 800m after a building event',async()=>{
  const b=backend(),worker=vi.fn(async()=>ready),progress:LoadProgress[]=[];
  const first=await loadCandidate(b.client,candidate,resolved,worker,p=>progress.push(p),new AbortController().signal);
  expect(progress.some(p=>p.result?.axes.find(a=>a.key==='exposure')?.status==='pending')).toBe(true);
  b.rpc.mockClear();const next=inputs();next.building!.floors_above=8;
  next.meta.sources={...next.meta.sources,building_address:{available:true,fetched_at:'2026-10-01T00:00:00Z'}};b.primary(next);
  const second=await loadCandidate(b.client,candidate,resolved,worker,()=>{},new AbortController().signal,first.inputs,true);
  expect(b.rpc.mock.calls.map(([name,args])=>[name,args.radius_m])).toEqual([['score_inputs',800]]);
  expect(worker).toHaveBeenCalledTimes(1);expect(second.inputs.primary?.building?.floors_above).toBe(8);
 });
 it('invalidates reference, school and scene on source snapshot change',async()=>{
  const b=backend(),worker=vi.fn(async()=>ready);
  const first=await loadCandidate(b.client,candidate,resolved,worker,()=>{},new AbortController().signal);
  const next=inputs();next.meta.sources={...next.meta.sources,fixture_change:{available:true}};b.primary(next);b.rpc.mockClear();
  await loadCandidate(b.client,candidate,resolved,worker,()=>{},new AbortController().signal,first.inputs,true);
  expect(b.rpc.mock.calls.map(([name])=>name)).toEqual(['score_inputs','score_inputs','exposure_inputs_v022','score_reference_percentiles']);expect(worker).toHaveBeenCalledTimes(2);
 });
 it('retains successful RPCs after a reference failure and retries only that RPC',async()=>{
  const b=backend();b.fail('score_reference_percentiles');let cache;
  await expect(loadCandidate(b.client,candidate,resolved,async()=>ready,p=>{if(p.inputs)cache=p.inputs;},new AbortController().signal)).rejects.toThrow();
  b.rpc.mockClear();await loadCandidate(b.client,candidate,resolved,async()=>ready,()=>{},new AbortController().signal,cache);
  expect(b.rpc.mock.calls.map(([name])=>name)).toEqual(['score_reference_percentiles']);
 });
 it('does not cache a failed Worker and retries it with no RPCs',async()=>{
  const b=backend(),worker=vi.fn(async():Promise<ExposureInput>=>({status:'missing',reason:'exposure_worker_unavailable'}));
  const first=await loadCandidate(b.client,candidate,resolved,worker,()=>{},new AbortController().signal);
  expect(first.stage).toBe('error');expect(first.inputs.exposure).toBeUndefined();expect(first.result.total).not.toBeNull();
  worker.mockResolvedValue(ready);b.rpc.mockClear();const second=await loadCandidate(b.client,candidate,resolved,worker,()=>{},new AbortController().signal,first.inputs);
  expect(second.stage).toBe('scored');expect(b.rpc).not.toHaveBeenCalled();expect(worker).toHaveBeenCalledTimes(2);
 });
 it('rejects late completion after abort without publishing it',async()=>{
  const b=backend(),controller=new AbortController();let finish!:(x:ExposureInput)=>void;
  const promise=loadCandidate(b.client,candidate,resolved,()=>new Promise(r=>{finish=r;}),()=>{},controller.signal);
  await vi.waitFor(()=>expect(finish).toBeTypeOf('function'));controller.abort();finish(ready);
  await expect(promise).rejects.toThrow();
 });
});
