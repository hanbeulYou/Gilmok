/** Manual browser validation entry, never imported by app/ or served by Next.js. */
import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { ComparisonMatrix } from '../../components/compare/ComparisonMatrix';
import { useComparisonStore, scoreCandidate, acceptLookup, type NewCandidate } from '../../lib/compare/store';
import { getSupabaseClient } from '../../lib/supabase/client';
import { ensureSession } from '../../lib/supabase/session';
import { subscribeLookups } from '../../lib/compare/subscriptions';
import type { LookupState } from '../../lib/compare/status';
const client = getSupabaseClient();
const proof = {
  ready: false, events: [] as LookupState[], states: [] as string[],
  async add(value: NewCandidate) {
    const {data,error} = await client.rpc('resolve_candidate_location', {lat:value.candidate.lat,lng:value.candidate.lng,pnu:value.selection.pnu || null});
    if(error) throw error;
    const id = useComparisonStore.getState().add({...value,resolved:data}); await scoreCandidate(id); return id;
  },
  state: () => useComparisonStore.getState(),
  remove: (id: string) => useComparisonStore.getState().remove(id),
  edit: (id: string, floor: number) => useComparisonStore.getState().edit(id, '층 변경', floor),
  deliver: acceptLookup,
  async watch(address: string) {
    const {data, error} = await client.rpc('watch_candidate_lookup', {address});
    if (error) throw error; return data;
  },
  async observe(ids: string[]) {
    const session = await ensureSession();
    return subscribeLookups(client, session.user.id, ids, row => proof.events.push(row), state => proof.states.push(state));
  },
  disconnect: () => client.realtime.disconnect(),
  reconnect: () => client.realtime.connect(),
  async visible() { const {data,error} = await client.from('candidate_lookup_state').select('*'); if(error) throw error; return data; },
  async start() { const session = await ensureSession(); createRoot(document.getElementById('root')!).render(createElement(ComparisonMatrix)); proof.ready=true; return session.user.id; },
};
Object.assign(window, { comparisonProof: proof });
