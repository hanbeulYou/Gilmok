import { create } from 'zustand';
import type { AddressSelection, RegisteredLocation } from '../geo/address-provider';
import type { Candidate, ScoreResult } from '../scoring/types';
import { getSupabaseClient } from '../supabase/client';
import { ensureSession } from '../supabase/session';
import { browserExposure } from '../visibility/browser';
import { loadCandidate, type ResolvedLocation, type RegistrationStage } from './load-candidate';
export interface ComparisonCandidate {
  id: string; alias: string; candidate: Candidate; selection: AddressSelection;
  location: RegisteredLocation; resolved: ResolvedLocation; stage: RegistrationStage;
  result?: ScoreResult; error?: string; lookupRequestId?: string | null;
}
interface ComparisonState {
  candidates: ComparisonCandidate[];
  add: (value: Omit<ComparisonCandidate, 'id' | 'stage'>) => string;
  update: (id: string, value: Partial<ComparisonCandidate>) => void;
  remove: (id: string) => void;
}
export const useComparisonStore = create<ComparisonState>((set, get) => ({
  candidates: [],
  add(value) {
    if (get().candidates.length >= 5) throw new Error('후보는 최대 5곳까지 비교할 수 있습니다.');
    const id = crypto.randomUUID();
    set(state => ({ candidates: [...state.candidates, { ...value, id, stage: 'fetching' }] }));
    return id;
  },
  update(id, value) { set(state => ({ candidates: state.candidates.map(c => c.id === id ? { ...c, ...value } : c) })); },
  remove(id) { jobs.get(id)?.abort(); set(state => ({ candidates: state.candidates.filter(c => c.id !== id) })); },
}));
const jobs = new Map<string, AbortController>();
const queue: (() => void)[] = [];
let active = 0;
async function acquire() {
  if (active < 2) { active++; return; }
  await new Promise<void>(resolve => queue.push(resolve));
}
function release() { const next = queue.shift(); if (next) next(); else active--; }
/** Shared jobs prevent duplicate RPCs; two candidates at most load concurrently. */
export async function scoreCandidate(id: string): Promise<void> {
  if (jobs.has(id)) return;
  const controller = new AbortController(); jobs.set(id, controller);
  await acquire();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const store = useComparisonStore.getState();
  try {
    const row = store.candidates.find(c => c.id === id);
    if (!row || controller.signal.aborted) return;
    timer = setTimeout(() => controller.abort(), 55000);
    store.update(id, { error: undefined, stage: 'fetching' });
    await ensureSession();
    const loaded = await loadCandidate(getSupabaseClient(), row.candidate, row.resolved,
      browserExposure, stage => store.update(id, { stage }), controller.signal);
    store.update(id, loaded);
  } catch (error) {
    store.update(id, { stage: 'error', error: controller.signal.aborted
      ? '조회 시간이 길어지고 있습니다. 다시 시도해 주세요.'
      : error instanceof Error ? error.message : '채점에 실패했습니다. 다시 시도해 주세요.' });
  } finally { clearTimeout(timer); controller.abort(); jobs.delete(id); release(); }
}
