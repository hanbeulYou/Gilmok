import {getSupabaseClient} from '../supabase/client';
import {ensureSession} from '../supabase/session';
import type {GeometryItem} from './buildings';
let queue:Promise<unknown>=Promise.resolve();
/** One display RPC in flight across building and sample adapters. Aborted queued work never starts. */
export function projectGeometry(items:GeometryItem[],signal:AbortSignal):Promise<GeometryItem[]> {
 const job=queue.catch(()=>undefined).then(async()=>{
  signal.throwIfAborted();await ensureSession();signal.throwIfAborted();
  const {data,error}=await getSupabaseClient().rpc('project_exposure_geometry',{items}).abortSignal(signal);
  signal.throwIfAborted();if(error||!Array.isArray(data))throw new Error('표시 좌표를 변환하지 못했습니다. 잠시 후 다시 시도해 주세요.');return data as GeometryItem[];
 });
 // The serialization tail must not retain projected geometry after UI caches clear.
 queue=job.then(()=>undefined,()=>undefined);return job;
}
