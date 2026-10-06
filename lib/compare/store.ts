import { create } from 'zustand';
import type { AddressSelection, RegisteredLocation } from '../geo/address-provider';
import type { AxisKey, Candidate, ScoreResult, Weights } from '../scoring/types';
import { academyV0 } from '../scoring/presets';
import { reweight } from '../scoring/score';
import { getSupabaseClient } from '../supabase/client';
import { ensureSession } from '../supabase/session';
import { browserExposure } from '../visibility/browser';
import { loadCandidate, type CandidateInputs, type LoadProgress, type ResolvedLocation, type RegistrationStage } from './load-candidate';
import { isTerminal, isWaiting, newer, type LookupState } from './status';
export interface ComparisonCandidate {
  id: string; alias: string; candidate: Candidate; selection: AddressSelection;
  location: RegisteredLocation; resolved: ResolvedLocation; stage: RegistrationStage;
  generation: number; startedAt: number; pendingSince?: number; refreshing?: boolean;
  inputs?: CandidateInputs; result?: ScoreResult; error?: string; lookupRequestId?: string | null;
  lookupStatus?: string; lookupState?: LookupState;
}
export type NewCandidate = Pick<ComparisonCandidate, 'alias' | 'candidate' | 'selection' | 'location' | 'resolved'>;
interface ComparisonState {
  candidates: ComparisonCandidate[]; weights: Weights; order: string[]; manualOrder: boolean; adjusting: boolean;
  selectedId: string | null; selectedAxis: AxisKey | null; evidenceOpen: boolean;
  comparisonId: string | null; snapshotReadOnly: boolean;
  clear: () => void;
  restore: (candidates: ComparisonCandidate[], weights: Weights, order: string[], manualOrder: boolean,
    comparisonId: string, snapshotReadOnly?: boolean) => void;
  add: (value: NewCandidate) => string;
  update: (id: string, value: Partial<ComparisonCandidate>, generation?: number) => void;
  remove: (id: string) => void;
  edit: (id: string, alias: string, floor: number) => void;
  setWeight: (key: AxisKey, value: number) => void;
  beginAdjustment: () => void; endAdjustment: () => void; resetWeights: () => void;
  move: (id: string, before: string) => void; sortByScore: () => void;
  select: (id: string, axis?: AxisKey) => void; closeEvidence: () => void;
}
export function scoreOrder(rows: readonly ComparisonCandidate[], weights: Weights, order: readonly string[]) {
  const totals = new Map(rows.map(row => [row.id, row.result ? reweight(row.result, weights).total : null]));
  return [...order.filter(id => totals.has(id)), ...rows.map(r => r.id).filter(id => !order.includes(id))]
    .sort((a, b) => (totals.get(b) ?? -Infinity) - (totals.get(a) ?? -Infinity));
}
export const useComparisonStore = create<ComparisonState>((set, get) => ({
  candidates: [], weights: { ...academyV0.weights }, order: [], manualOrder: false, adjusting: false,
  selectedId: null, selectedAxis: null, evidenceOpen: false,
  comparisonId: null, snapshotReadOnly: false,
  clear() {
    for (const job of jobs.values()) job.controller.abort();
    jobs.clear(); refreshes.clear();
    set({ candidates: [], order: [], weights: { ...academyV0.weights }, comparisonId: null, snapshotReadOnly: false,
      adjusting: false, manualOrder: false, selectedId: null, selectedAxis: null, evidenceOpen: false });
  },
  restore(candidates, weights, order, manualOrder, comparisonId, snapshotReadOnly = false) {
    for (const job of jobs.values()) job.controller.abort();
    jobs.clear(); refreshes.clear();
    set({ candidates, weights, order, manualOrder, comparisonId, snapshotReadOnly,
      adjusting: false, selectedId: order[0] ?? null, selectedAxis: null, evidenceOpen: false });
  },
  add(value) {
    if (get().snapshotReadOnly) throw new Error('마지막 저장 결과는 읽기 전용입니다. 다시 불러온 뒤 등록해 주세요.');
    if (get().candidates.length >= 5) throw new Error('후보는 최대 5곳까지 비교할 수 있습니다.');
    const id = crypto.randomUUID();
    set(state => ({ candidates: [...state.candidates, { ...value, id, generation: 0, startedAt: Date.now(), stage: 'fetching' }],
      order: [...state.order, id], selectedId: state.selectedId ?? id }));
    return id;
  },
  update(id, value, generation) {
    set(state => {
      const existing = state.candidates.find(c => c.id === id);
      if (!existing || (generation !== undefined && existing.generation !== generation)) return state;
      const candidates = state.candidates.map(c => c.id === id ? { ...c, ...value,
        pendingSince: isWaiting('lookupStatus' in value ? value.lookupStatus : c.lookupStatus) ? c.pendingSince ?? Date.now() : undefined } : c);
      return { candidates, order: state.adjusting || state.manualOrder ? state.order : scoreOrder(candidates, state.weights, state.order) };
    });
  },
  remove(id) {
    if (get().snapshotReadOnly) return;
    jobs.get(id)?.controller.abort(); jobs.delete(id); refreshes.delete(id);
    set(state => { const candidates = state.candidates.filter(c => c.id !== id);
      return { candidates, order: state.order.filter(v => v !== id),
        selectedId: state.selectedId === id ? candidates[0]?.id ?? null : state.selectedId,
        evidenceOpen: candidates.length > 0 && state.evidenceOpen }; });
  },
  edit(id, alias, floor) {
    if (get().snapshotReadOnly) return;
    if (!alias.trim() || alias.trim().length > 20 || !Number.isInteger(floor) || floor === 0 || floor < -5 || floor > 30)
      throw new Error('별칭은 1~20자, 층은 −5~−1 또는 1~30으로 입력해 주세요.');
    const row = get().candidates.find(c => c.id === id); if (!row) return;
    if (floor === row.candidate.floor) { get().update(id, { alias: alias.trim() }); return; }
    jobs.get(id)?.controller.abort(); jobs.delete(id); refreshes.delete(id);
    get().update(id, { alias: alias.trim(), candidate: { ...row.candidate, floor }, generation: row.generation + 1,
      result: undefined, inputs: undefined, lookupRequestId: null, lookupState: undefined, lookupStatus: undefined,
      pendingSince: undefined, refreshing: false, stage: 'fetching', startedAt: Date.now(), error: undefined });
    void scoreCandidate(id);
  },
  setWeight(key, value) {
    if (get().snapshotReadOnly) return;
    if (!Number.isFinite(value) || value < 0 || value > 40) return;
    set(state => { const weights = { ...state.weights, [key]: value };
      return { weights, order: state.adjusting || state.manualOrder ? state.order : scoreOrder(state.candidates, weights, state.order) }; });
  },
  beginAdjustment() { set({ adjusting: true }); },
  endAdjustment() { set(state => ({ adjusting: false,
    order: state.manualOrder ? state.order : scoreOrder(state.candidates, state.weights, state.order) })); },
  resetWeights() { if (get().snapshotReadOnly) return; set(state => ({ weights: { ...academyV0.weights }, adjusting: false,
    order: state.manualOrder ? state.order : scoreOrder(state.candidates, academyV0.weights, state.order) })); },
  move(id, before) { if (get().snapshotReadOnly) return; set(state => { if (id === before || !state.order.includes(id) || !state.order.includes(before)) return state;
    const order = state.order.filter(v => v !== id); order.splice(order.indexOf(before), 0, id); return { order, manualOrder: true }; }); },
  sortByScore() { set(state => ({ manualOrder: false, order: scoreOrder(state.candidates, state.weights, state.order) })); },
  select(id, axis) { set({ selectedId: id, selectedAxis: axis ?? null, evidenceOpen: true }); },
  closeEvidence() { set({ evidenceOpen: false }); },
}));
const jobs = new Map<string, { controller: AbortController; generation: number }>();
const refreshes = new Map<string, number>();
const queue: (() => void)[] = []; let active = 0;
async function acquire() { if (active < 2) { active++; return; } await new Promise<void>(resolve => queue.push(resolve)); }
function release() { const next = queue.shift(); if (next) next(); else active--; }
export function acceptLookup(id: string, generation: number, lookup: LookupState) {
  const row = useComparisonStore.getState().candidates.find(c => c.id === id);
  if (!row || row.generation !== generation || row.lookupRequestId !== lookup.request_id || !newer(lookup, row.lookupState)) return;
  useComparisonStore.getState().update(id, { lookupState: lookup, lookupStatus: lookup.status }, generation);
  // Failed score_inputs calls re-observe the request and advance projection time.
  // A timestamp-only failed event must not create a self-sustaining RPC loop.
  if (isTerminal(lookup.status) && !(lookup.status === 'failed' && row.lookupStatus === 'failed')) void scoreCandidate(id, true);
}
/** Generations reject late RPC/Worker replies after removal/floor edits; at most two jobs load. */
export async function scoreCandidate(id: string, refresh = false): Promise<void> {
  const row = useComparisonStore.getState().candidates.find(c => c.id === id); if (!row) return;
  if (jobs.has(id)) { if (refresh) refreshes.set(id, row.generation); return; }
  const controller = new AbortController(), job = { controller, generation: row.generation }; jobs.set(id, job);
  await acquire();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const patch = (value: LoadProgress & Partial<ComparisonCandidate>) => {
    if (!controller.signal.aborted) useComparisonStore.getState().update(id, value, row.generation);
  };
  try {
    if (controller.signal.aborted) return;
    timer = setTimeout(() => controller.abort(), 55000);
    patch({ error: undefined, refreshing: refresh, ...(refresh && row.result ? {} : { stage: 'fetching', startedAt: Date.now() }) });
    await ensureSession(); controller.signal.throwIfAborted();
    const loaded = await loadCandidate(getSupabaseClient(), row.candidate, row.resolved, browserExposure,
      patch, controller.signal, row.inputs, refresh, row.selection.pnu);
    patch({ ...loaded, refreshing: false });
  } catch (error) {
    useComparisonStore.getState().update(id, { stage: 'error', refreshing: false,
      error: controller.signal.aborted ? '조회 시간이 길어지고 있습니다. 다시 시도해 주세요.'
        : error instanceof Error ? error.message : '채점에 실패했습니다. 다시 시도해 주세요.' }, row.generation);
  } finally {
    clearTimeout(timer); controller.abort();
    if (jobs.get(id) === job) jobs.delete(id);
    release();
    if (refreshes.get(id) === row.generation) { refreshes.delete(id); void scoreCandidate(id, true); }
  }
}
