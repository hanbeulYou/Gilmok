import {it,expect,vi} from 'vitest';
const rpc=vi.hoisted(()=>vi.fn());
vi.mock('../../lib/supabase/client',()=>({getSupabaseClient:()=>({rpc})}));
vi.mock('../../lib/supabase/session',()=>({ensureSession:()=>Promise.resolve()}));
import {projectGeometry} from '../../lib/map/project';
it('serializes building/sample display calls and drops aborted queued work',async()=>{
 const releases:((x:unknown)=>void)[]=[];
 rpc.mockImplementation(()=>({abortSignal:()=>new Promise(resolve=>releases.push(resolve))}));
 const signal=new AbortController().signal,queued=new AbortController();
 const a=projectGeometry([],signal),b=projectGeometry([],signal),c=projectGeometry([],queued.signal).catch(e=>e.name);
 await vi.waitFor(()=>expect(rpc).toHaveBeenCalledTimes(1));queued.abort();releases[0]({data:[],error:null});await a;
 await vi.waitFor(()=>expect(rpc).toHaveBeenCalledTimes(2));releases[1]({data:[],error:null});await b;
 expect(await c).toBe('AbortError');expect(rpc).toHaveBeenCalledTimes(2);
});
