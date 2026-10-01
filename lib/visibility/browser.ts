import { createVisibilityClient } from './client';
import type { VisibilityScene } from './types';
import type { ExposureInput } from '../scoring/types';
let client: ReturnType<typeof createVisibilityClient> | undefined;
let worker: Worker | undefined;
export async function browserExposure(scene: VisibilityScene): Promise<ExposureInput> {
  try {
    if (!client) {
      worker = new Worker(new URL('../../workers/visibility.worker.ts', import.meta.url), { type: 'module' });
      client = createVisibilityClient(worker);
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const response = await Promise.race([client.request(scene).response,
        new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('exposure_timeout')), 15000); })]);
      if ('error' in response) throw new Error(response.error);
      return response.result;
    } finally { clearTimeout(timer); }
  } catch {
    client?.dispose(); worker?.terminate(); client = undefined; worker = undefined;
    return { status: 'missing', reason: 'exposure_worker_unavailable' };
  }
}
