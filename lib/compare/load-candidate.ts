import type { SupabaseClient } from '@supabase/supabase-js';
import { extractReferenceRaw } from '../scoring/raw';
import { academyV0 } from '../scoring/presets';
import { score } from '../scoring/score';
import type { Candidate, ScoreContext, ScoreInputs, PercentileReference, ExposureInput, ScoreResult } from '../scoring/types';
import type { VisibilityScene } from '../visibility/types';

export interface ResolvedLocation {
  status: 'matched' | 'footprint_missing'; context: ScoreContext;
  building: { id: string; pnu: string; register_pk: string | null } | null;
}
export type RegistrationStage = 'fetching' | 'scoring' | 'scored' | 'scored_provisional' | 'error';
export interface CandidateInputs {
  key: string; primary?: ScoreInputs; school?: ScoreInputs; scene?: VisibilityScene;
  reference?: PercentileReference; exposure?: ExposureInput;
}
export interface LoadProgress {
  stage?: RegistrationStage; inputs?: CandidateInputs; result?: ScoreResult;
  lookupRequestId?: string | null; lookupStatus?: string; error?: string;
}
function canonical(value: unknown): string {
  return JSON.stringify(value, (_key, v) => v && typeof v === 'object' && !Array.isArray(v)
    ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => a.localeCompare(b))) : v);
}
// Address lookup freshness affects only the primary building input, not school,
// percentile distributions, or the footprint scene loaded by exposure_inputs.
function sharedSources(input: ScoreInputs) {
  return Object.fromEntries(Object.entries(input.meta.sources).filter(([key]) => key !== 'building_address'));
}
/** Partial successes survive retry; a ready event refreshes only primary when sources/raw are unchanged. */
export async function loadCandidate(client: SupabaseClient, candidate: Candidate, resolved: ResolvedLocation,
  exposure: (scene: VisibilityScene) => Promise<ExposureInput>, progress: (value: LoadProgress) => void,
  signal: AbortSignal, previous?: CandidateInputs, refresh = false) {
  const key = canonical(candidate), cache: CandidateInputs = previous?.key === key ? { ...previous } : { key };
  const priorPrimary = cache.primary;
  const publish = () => { signal.throwIfAborted(); progress({ inputs: { ...cache } }); };
  async function rpc<T>(name: string, args: Record<string, unknown>): Promise<T> {
    const { data, error } = await client.rpc(name, args).abortSignal(signal);
    signal.throwIfAborted();
    if (error || data === null) throw new Error('주변 데이터를 불러오지 못했습니다. 다시 시도해 주세요.');
    return data as T;
  }
  const input = { lat: candidate.lat, lng: candidate.lng, floor: candidate.floor, address: candidate.address };
  async function primary() {
    if (refresh || !cache.primary) {
      cache.primary = await rpc<ScoreInputs>('score_inputs', { ...input, radius_m: 800 });
      if (priorPrimary && canonical(sharedSources(priorPrimary)) !== canonical(sharedSources(cache.primary))) {
        cache.school = undefined; cache.scene = undefined; cache.reference = undefined; cache.exposure = undefined;
      }
      publish();
    }
    progress({ lookupRequestId: cache.primary.meta.building_lookup.request_id ?? null,
      lookupStatus: cache.primary.meta.building_lookup.status });
  }
  async function school() {
    if (!cache.school) { cache.school = await rpc<ScoreInputs>('score_inputs', { ...input, radius_m: 1000 }); publish(); }
  }
  async function scene() {
    if (!cache.scene) {
      cache.scene = { ...await rpc<Omit<VisibilityScene, 'floor'>>('exposure_inputs_v022',
        { lat: candidate.lat, lng: candidate.lng }), floor: candidate.floor };
      publish();
    }
  }
  // On refresh the new primary source snapshot decides whether secondary inputs may be reused.
  if (refresh || priorPrimary) { await primary(); await Promise.all([school(), scene()]); }
  else await Promise.all([primary(), school(), scene()]);
  signal.throwIfAborted();
  const raw = Object.fromEntries(Object.entries(extractReferenceRaw(cache.primary!, cache.school!, resolved.context, academyV0))
    .filter(([name]) => name !== 'cluster').map(([name, value]) => [name, value.value]));
  if (cache.reference && cache.reference.percentiles.some(p => p.raw !== raw[p.key])) cache.reference = undefined;
  const visibility = cache.exposure ? Promise.resolve({ value: cache.exposure, failed: false })
    : exposure(cache.scene!).then(value => ({ value, failed: value?.status === 'missing' && value.reason.startsWith('exposure_worker_') }), () => ({
      value: { status: 'missing', reason: 'exposure_worker_failed' } as ExposureInput, failed: true,
    }));
  if (!cache.reference) {
    cache.reference = await rpc<PercentileReference>('score_reference_percentiles', {
      requested_preset_id: academyV0.id, requested_radius_m: 800, requested_raw: raw,
    });
    publish();
  }
  const compute = (value: ExposureInput) => score(cache.primary!, cache.school!, cache.scene!.buildings,
    value, candidate, academyV0, cache.reference!, resolved.context);
  if (!cache.exposure) progress({ stage: 'scoring', result: compute({ status: 'pending', reason: 'exposure_worker_pending' }) });
  const completed = await visibility;
  signal.throwIfAborted();
  if (!completed.failed) cache.exposure = completed.value;
  const result = compute(completed.value);
  const pending = ['pending', 'processing'].includes(cache.primary!.meta.building_lookup.status);
  return { result, inputs: { ...cache }, lookupRequestId: cache.primary!.meta.building_lookup.request_id ?? null,
    lookupStatus: cache.primary!.meta.building_lookup.status,
    error: completed.failed ? '노출 계산에 실패했습니다. 다시 시도해 주세요.' : undefined,
    stage: completed.failed ? 'error' as const : pending ? 'scored_provisional' as const : 'scored' as const };
}
