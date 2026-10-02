import type { SupabaseClient } from '@supabase/supabase-js';
import { lookupState, newer, type LookupState } from './status';
export type ConnectionState = 'connecting' | 'connected' | 'reconnecting';
/** One owner-scoped channel. Only projection rows, never private address/cache payloads. */
export function subscribeLookups(client: SupabaseClient, uid: string, requestIds: readonly string[],
  receive: (state: LookupState) => void, connection: (state: ConnectionState) => void) {
  const allowed = new Set(requestIds), latest = new Map<string, LookupState>();
  let closed = false, reconcileAgain = false, reconciling = false;
  function accept(value: unknown) {
    if (closed) return;
    const state = lookupState(value);
    if (!state || !allowed.has(state.request_id) || !newer(state, latest.get(state.request_id))) return;
    latest.set(state.request_id, state);
    receive(state);
  }
  async function reconcile() {
    if (closed) return;
    if (reconciling) { reconcileAgain = true; return; }
    reconciling = true;
    try {
      const { data, error } = await client.from('candidate_lookup_state')
        .select('request_id,status,updated_at').in('request_id', [...allowed]);
      if (closed) return;
      if (error) connection('reconnecting');
      else for (const row of data ?? []) accept(row);
    } finally {
      reconciling = false;
      if (reconcileAgain && !closed) { reconcileAgain = false; void reconcile(); }
    }
  }
  connection('connecting');
  const channel = client.channel(`candidate-lookup:${uid}:${crypto.randomUUID()}`, {
    config: { postgres_changes_options: { wait: true } },
  })
    .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'candidate_lookup_status' }, payload => accept(payload.new))
    .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'candidate_lookup_status' }, payload => accept(payload.new))
    .subscribe(status => {
      if (closed) return;
      if (status === 'SUBSCRIBED') { connection('connected'); void reconcile(); }
      else if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT' || status === 'CLOSED') connection('reconnecting');
    });
  return {
    reconcile,
    close() { closed = true; void client.removeChannel(channel); },
  };
}
