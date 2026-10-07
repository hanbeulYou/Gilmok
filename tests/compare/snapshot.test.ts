import { beforeEach, expect, it, vi } from 'vitest';
import type { SupabaseClient } from '@supabase/supabase-js';
import type { ComparisonCandidate } from '../../lib/compare/store';
import { academyV0 } from '../../lib/scoring/presets';

const mocks = vi.hoisted(() => ({ uid:'owner-a', load:vi.fn(), rpc:vi.fn() }));
vi.mock('../../lib/supabase/session', () => ({ ensureSession:async () => ({ user:{ id:mocks.uid } }) }));
vi.mock('../../lib/supabase/client', () => ({ getSupabaseClient:() => ({ rpc:mocks.rpc }) }));
vi.mock('../../lib/compare/load-candidate', () => ({ loadCandidate:mocks.load }));
import { useComparisonStore } from '../../lib/compare/store';
import { reopenComparison, saveComparison, serializeCandidate } from '../../lib/compare/persistence';

const rows = [1,2].map(floor => ({ id:`candidate-${floor}`,alias:`층${floor}`,
  candidate:{ lat:37.5,lng:127.05,floor,address:'공개 주소' }, selection:{ pnu:'1168010600109120013' },
  location:{ status:'ready' },resolved:{ status:'footprint_missing' },stage:'scored',generation:0,
  startedAt:0,result:{ preset:{ id:'academy_v0',version:academyV0.version },total:80+floor },
} as ComparisonCandidate));
beforeEach(() => {
  mocks.uid='owner-a'; mocks.load.mockReset(); mocks.rpc.mockReset(); useComparisonStore.getState().clear();
  const data = new Map<string,string>();
  vi.stubGlobal('localStorage',{ getItem:(key:string)=>data.get(key) ?? null, setItem:(key:string,value:string)=>data.set(key,value) });
  useComparisonStore.getState().restore(rows,{ ...academyV0.weights },rows.map(r=>r.id),true,'comparison');
  mocks.rpc.mockImplementation(async (name:string) => ({ error:null, data:name === 'save_comparison_v2' ? 'comparison' : {
    comparison:{ id:'comparison',candidate_ids:rows.map(r=>r.id),weights:academyV0.weights,preset_version:'0.3',manual_order:true },
    candidates:rows.map(serializeCandidate),
  } }));
});
it('uses one complete owner snapshot only when every live score failed', async () => {
  await saveComparison({ rpc:mocks.rpc } as unknown as SupabaseClient);
  mocks.load.mockRejectedValue(new Error('offline'));
  await reopenComparison();
  expect(useComparisonStore.getState().snapshotReadOnly).toBe(true);
  expect(useComparisonStore.getState().candidates.map(r=>r.result?.total)).toEqual([81,82]);
  useComparisonStore.getState().setWeight('demand',1);
  expect(useComparisonStore.getState().weights.demand).toBe(30);
});
it('never fills a partial live result with old data', async () => {
  await saveComparison();
  mocks.load.mockImplementation(async (_client,candidate,_resolved,_exposure,progress) => {
    if (candidate.floor === 1) progress({ stage:'scored',result:{ ...rows[0].result,total:50 } });
    else throw new Error('offline');
  });
  await reopenComparison();
  expect(useComparisonStore.getState().snapshotReadOnly).toBe(false);
  expect(useComparisonStore.getState().candidates.map(r=>r.result?.total)).toEqual([50,undefined]);
});
it('does not read another uid snapshot even for the same comparison ID', async () => {
  await saveComparison(); mocks.uid='owner-b'; mocks.load.mockRejectedValue(new Error('offline'));
  await reopenComparison();
  expect(useComparisonStore.getState().snapshotReadOnly).toBe(false);
  expect(useComparisonStore.getState().candidates.every(r=>!r.result)).toBe(true);
});

it('re-scores legacy 0.3 saved inputs with the current model', async () => {
  mocks.load.mockImplementation(async (_client, candidate, _resolved, _exposure, progress) => {
    progress({ stage:'scored', result:{ ...rows[0].result, total:70+candidate.floor } });
    return { result:{ ...rows[0].result, total:70+candidate.floor }, inputs:{} };
  });
  await reopenComparison();
  expect(mocks.load).toHaveBeenCalledTimes(2);
  expect(useComparisonStore.getState().candidates.every(r=>r.result?.preset.version==='0.4.0')).toBe(true);
});

it('does not restore v0.3 scores after failed v0.4.0 scoring', async () => {
  useComparisonStore.setState({ candidates:rows.map(r=>({ ...r, result:{ ...r.result!, preset:{ id:'academy_v0',version:'0.3' } } })) });
  await saveComparison();
  mocks.load.mockRejectedValue(new Error('offline'));
  await reopenComparison();
  expect(useComparisonStore.getState().snapshotReadOnly).toBe(false);
  expect(useComparisonStore.getState().candidates.every(r=>!r.result)).toBe(true);
});

it('writes actual model metadata only after a successful save', async () => {
  useComparisonStore.setState({ savedModelVersion:'0.3' });
  await saveComparison();
  expect(mocks.rpc).toHaveBeenCalledWith('save_comparison_v2', expect.objectContaining({ model_version:'0.4.0' }));
  expect(useComparisonStore.getState().savedModelVersion).toBe('0.4.0');
  mocks.rpc.mockResolvedValueOnce({ error:{ message:'failed' }, data:null });
  useComparisonStore.setState({ savedModelVersion:'0.3' });
  await expect(saveComparison()).rejects.toThrow();
  expect(useComparisonStore.getState().savedModelVersion).toBe('0.3');
});
it('saves incomplete results as unrecorded and preserves loaded metadata until saving', async () => {
  useComparisonStore.setState({ candidates:[{ ...rows[0], stage:'error' }], savedModelVersion:'0.3' });
  await saveComparison();
  expect(mocks.rpc).toHaveBeenCalledWith('save_comparison_v2', expect.objectContaining({ model_version:null }));
  expect(useComparisonStore.getState().savedModelVersion).toBeNull();
});
