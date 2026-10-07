import type { SupabaseClient } from '@supabase/supabase-js';
import { academyV0 } from '../scoring/presets';
import type { Weights } from '../scoring/types';
import { getSupabaseClient } from '../supabase/client';
import { ensureSession } from '../supabase/session';
import { scoreCandidate, useComparisonStore, type ComparisonCandidate } from './store';

const keys = Object.keys(academyV0.weights) as (keyof Weights)[];
export function validWeights(value: unknown): value is Weights {
  if (!value || typeof value !== 'object' || Object.keys(value).length !== keys.length) return false;
  return keys.every(key => typeof (value as Weights)[key] === 'number' && Number.isFinite((value as Weights)[key])
    && (value as Weights)[key] >= 0 && (value as Weights)[key] <= 40);
}
export function normalizedWeights(weights: Weights): Weights {
  const total = keys.reduce((sum, key) => sum + weights[key], 0);
  return Object.fromEntries(keys.map(key => [key, total ? weights[key] / total : 0])) as Weights;
}
export function serializeCandidate(row: ComparisonCandidate) {
  return { id: row.id, alias: row.alias, lat: row.candidate.lat, lng: row.candidate.lng, floor: row.candidate.floor,
    address: row.candidate.address ?? null, pnu: row.selection.pnu || null,
    deposit: row.candidate.deposit_krw ?? null, user_rent: row.candidate.monthly_rent_krw ?? null,
    management_fee: row.candidate.maintenance_krw ?? null, area_m2: row.candidate.exclusive_area_m2 ?? null,
    address_provenance: { selection: row.selection, location: row.location },
    registration_context: row.resolved, lookup_request_id: row.lookupRequestId ?? null, lookup_status: row.lookupStatus ?? null };
}
type SavedCandidate = ReturnType<typeof serializeCandidate>;
interface SavedComparison { comparison: { id: string; candidate_ids: string[]; weights: Weights; preset_version: string;
  reference_snapshot: string | null; manual_order: boolean; updated_at: string }; candidates: SavedCandidate[] }
interface Snapshot { id: string; signature: string; rows: ComparisonCandidate[]; savedAt: string }
// The unchanged DB stores candidate inputs and eight weights, never ScoreResult.
// Its fixed 0.3 metadata is accepted for fresh scoring with the current model.
const storedInputVersion = '0.3';
const cacheKey = (uid: string, id: string) => `gilmok:comparison:${uid}:${id}`;
function signature(rows: ComparisonCandidate[], weights: Weights, order: string[]) {
  // JSONB object key order differs from browser insertion order.
  return JSON.stringify({ rows: rows.map(serializeCandidate).sort((a,b) => a.id.localeCompare(b.id)), weights, order },
    (_key, value) => value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).sort(([a],[b]) => a.localeCompare(b))) : value);
}
export async function saveComparison(client: SupabaseClient = getSupabaseClient()): Promise<string> {
  const session = await ensureSession(), state = useComparisonStore.getState();
  if (state.snapshotReadOnly || !state.candidates.length || state.candidates.length > 5 || !validWeights(state.weights))
    throw new Error('저장할 비교를 확인해 주세요.');
  const id = state.comparisonId ?? crypto.randomUUID();
  useComparisonStore.setState({ comparisonId: id }); // Retry after a lost HTTP reply keeps the same ID.
  const { data, error } = await client.rpc('save_comparison', { comparison_id: id,
    candidate_rows: state.candidates.map(serializeCandidate), raw_weights: state.weights, ordered_ids: state.order,
    fixed_order: state.manualOrder, source_snapshot: academyV0.cluster_scale.snapshot });
  if (error || data !== id) throw new Error('비교를 저장하지 못했습니다. 다시 시도해 주세요.');
  if (state.candidates.every(row => row.result)) {
    const snapshot: Snapshot = { id, rows: state.candidates, savedAt: new Date().toISOString(),
      signature: signature(state.candidates, state.weights, state.order) };
    try { localStorage.setItem(cacheKey(session.user.id, id), JSON.stringify(snapshot)); } catch { /* DB save is authoritative. */ }
  }
  return id;
}
export function deserializeCandidate(row: SavedCandidate): ComparisonCandidate {
  return { id: row.id, alias: row.alias, candidate: { lat: row.lat, lng: row.lng, floor: row.floor, address: row.address,
    deposit_krw: row.deposit, monthly_rent_krw: row.user_rent, maintenance_krw: row.management_fee, exclusive_area_m2: row.area_m2 },
    selection: row.address_provenance.selection, location: row.address_provenance.location,
    resolved: row.registration_context, lookupRequestId: row.lookup_request_id, lookupStatus: row.lookup_status ?? undefined,
    generation: Date.now(), startedAt: Date.now(), stage: 'fetching' };
}
export async function reopenComparison(id: string | null = null, client: SupabaseClient = getSupabaseClient()): Promise<boolean> {
  const session = await ensureSession();
  const { data, error } = await client.rpc('load_comparison', { comparison_id: id });
  if (error) throw new Error('저장한 비교를 불러오지 못했습니다. 다시 시도해 주세요.');
  if (!data) return false;
  const saved = data as SavedComparison, c = saved.comparison;
  if (c.preset_version !== storedInputVersion || !validWeights(c.weights) || !saved.candidates?.length
    || saved.candidates.some(r => !r.address_provenance?.selection || !r.registration_context))
    throw new Error('저장 형식을 확인할 수 없습니다. 후보를 다시 등록해 주세요.');
  const rows = saved.candidates.map(deserializeCandidate);
  useComparisonStore.getState().restore(rows, c.weights, c.candidate_ids, c.manual_order, c.id);
  await Promise.all(rows.map(row => scoreCandidate(row.id)));
  const current = useComparisonStore.getState();
  if (current.comparisonId === c.id && current.candidates.every(row => row.stage === 'error' && !row.result)) {
    try {
      const cached = JSON.parse(localStorage.getItem(cacheKey(session.user.id, c.id)) ?? 'null') as Snapshot | null;
      if (cached?.id === c.id && cached.signature === signature(rows, c.weights, c.candidate_ids)
        && cached.rows.every(row => row.result?.preset.version === academyV0.version))
        current.restore(cached.rows, c.weights, c.candidate_ids, c.manual_order, c.id, true);
    } catch { /* Never mix a missing/invalid owner snapshot with fresh inputs. */ }
  }
  return true;
}

export interface WeightPreset { id: string; name: string; weights: Weights; normalized_weights: Weights }
export async function deleteCandidate(id: string, client: SupabaseClient = getSupabaseClient()) {
  const state = useComparisonStore.getState();
  if (state.snapshotReadOnly) return;
  if (state.comparisonId) {
    await ensureSession();
    // Owner RLS + DB AFTER DELETE repairs all affected comparisons atomically.
    const { error } = await client.from('candidates').delete().eq('id', id);
    if (error) throw new Error('후보를 삭제하지 못했습니다. 다시 시도해 주세요.');
  }
  state.remove(id);
  if (!useComparisonStore.getState().candidates.length) useComparisonStore.setState({ comparisonId:null });
}
export async function listWeightPresets(client: SupabaseClient = getSupabaseClient()): Promise<WeightPreset[]> {
  await ensureSession();
  const { data, error } = await client.from('user_weight_presets').select('id,name,weights,normalized_weights').order('name');
  if (error) throw new Error('가중치 프리셋을 불러오지 못했습니다.');
  return (data as WeightPreset[]).filter(p => validWeights(p.weights) && keys.every(key =>
    Math.abs(normalizedWeights(p.weights)[key] - p.normalized_weights[key]) < 1e-12));
}
export async function saveWeightPreset(name: string, weights: Weights, client: SupabaseClient = getSupabaseClient()) {
  const session = await ensureSession();
  if (!name.trim() || name.trim().length > 30 || !validWeights(weights) || !Object.values(weights).some(v => v > 0))
    throw new Error('이름은 1~30자, 가중치는 하나 이상 0보다 커야 합니다.');
  const { error } = await client.from('user_weight_presets').upsert({ user_id: session.user.id, name: name.trim(), weights }, { onConflict: 'user_id,name' });
  if (error) throw new Error('가중치 프리셋을 저장하지 못했습니다. 다시 시도해 주세요.');
}
