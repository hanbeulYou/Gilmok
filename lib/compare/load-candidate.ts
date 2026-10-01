import type { SupabaseClient } from '@supabase/supabase-js';
import { extractReferenceRaw } from '../scoring/raw';
import { academyV0 } from '../scoring/presets';
import { score } from '../scoring/score';
import type { Candidate, ScoreContext, ScoreInputs, PercentileReference, ExposureInput } from '../scoring/types';
import type { VisibilityScene } from '../visibility/types';

export interface ResolvedLocation {
  status: 'matched' | 'footprint_missing';
  context: ScoreContext;
  building: { id: string; pnu: string; register_pk: string | null } | null;
}
export type RegistrationStage = 'fetching' | 'scoring' | 'scored' | 'scored_provisional' | 'error';
export async function loadCandidate(client: SupabaseClient, candidate: Candidate, resolved: ResolvedLocation,
  exposure: (scene: VisibilityScene) => Promise<ExposureInput>,
  stage: (value: RegistrationStage) => void, signal: AbortSignal) {
  async function rpc<T>(name: string, args: Record<string, unknown>): Promise<T> {
    const { data, error } = await client.rpc(name, args).abortSignal(signal);
    if (error || data === null) throw new Error('주변 데이터를 불러오지 못했습니다. 다시 시도해 주세요.');
    return data as T;
  }
  stage('fetching');
  const input = { lat: candidate.lat, lng: candidate.lng, floor: candidate.floor, address: candidate.address };
  const [primary, school, scene] = await Promise.all([
    rpc<ScoreInputs>('score_inputs', { ...input, radius_m: 800 }),
    rpc<ScoreInputs>('score_inputs', { ...input, radius_m: 1000 }),
    rpc<Omit<VisibilityScene, 'floor'>>('exposure_inputs_v022', { lat: candidate.lat, lng: candidate.lng }),
  ]);
  signal.throwIfAborted();
  stage('scoring');
  const raw = extractReferenceRaw(primary, school, resolved.context, academyV0);
  const [reference, visibility] = await Promise.all([
    rpc<PercentileReference>('score_reference_percentiles', { requested_preset_id: academyV0.id,
      requested_radius_m: 800, requested_raw: Object.fromEntries(Object.entries(raw)
        .filter(([key]) => key !== 'cluster').map(([key, value]) => [key, value.value])) }),
    exposure({ ...scene, floor: candidate.floor }),
  ]);
  signal.throwIfAborted();
  const result = score(primary, school, scene.buildings, visibility, candidate, academyV0, reference, resolved.context);
  const pending = ['pending', 'processing'].includes(primary.meta.building_lookup.status);
  return { result, lookupRequestId: primary.meta.building_lookup.request_id ?? null,
    stage: pending ? 'scored_provisional' as const : 'scored' as const };
}
