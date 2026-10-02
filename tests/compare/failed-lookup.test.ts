import { expect, it, vi } from 'vitest';
import { acceptLookup, useComparisonStore, type NewCandidate } from '../../lib/compare/store';
import { loadCandidate } from '../../lib/compare/load-candidate';
import { candidate, context } from '../scoring/fixtures';
vi.mock('../../lib/supabase/client', () => ({ getSupabaseClient:() => ({}) }));
vi.mock('../../lib/supabase/session', () => ({ ensureSession:async () => ({}) }));
vi.mock('../../lib/compare/load-candidate', () => ({ loadCandidate:vi.fn() }));
it('refreshes the first failed transition once, ignoring its timestamp-only re-observations', async () => {
  const store = useComparisonStore.getState();
  const id = store.add({ alias:'실패 검증',candidate,selection:{},location:{},
    resolved:{ status:'footprint_missing',context,building:null } } as NewCandidate);
  store.update(id,{ lookupRequestId:'request',lookupStatus:'pending' });
  vi.mocked(loadCandidate).mockResolvedValue({ stage:'scored',inputs:{ key:'failed' },
    lookupRequestId:'request',lookupStatus:'failed' } as Awaited<ReturnType<typeof loadCandidate>>);
  try {
    acceptLookup(id,0,{ request_id:'request',status:'failed',updated_at:'2026-10-02T00:00:00Z' });
    await vi.waitFor(() => expect(useComparisonStore.getState().candidates.find(r=>r.id===id)?.stage).toBe('scored'));
    for (let second=1;second<5;second++) acceptLookup(id,0,{ request_id:'request',status:'failed',updated_at:`2026-10-02T00:00:0${second}Z` });
    await Promise.resolve(); expect(loadCandidate).toHaveBeenCalledTimes(1);
    acceptLookup(id,0,{ request_id:'request',status:'processing',updated_at:'2026-10-02T00:00:05Z' });
    acceptLookup(id,0,{ request_id:'request',status:'failed',updated_at:'2026-10-02T00:00:06Z' });
    await vi.waitFor(() => expect(loadCandidate).toHaveBeenCalledTimes(2));
  } finally { store.remove(id); }
});
