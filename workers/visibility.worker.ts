import { computeVisibility } from '../lib/visibility/compute.ts';
import type { VisibilityRequest, VisibilityResponse } from '../lib/visibility/types.ts';
const worker = self as DedicatedWorkerGlobalScope;
worker.onmessage = (event: MessageEvent<VisibilityRequest>) => {
  const { requestId, scene } = event.data;
  let response: VisibilityResponse;
  try {
    const start = performance.now();
    const result = computeVisibility(scene);
    response = { requestId, result, computeMs: performance.now() - start };
  } catch (error) {
    response = { requestId, error: error instanceof Error ? error.message : 'visibility_worker_error' };
  }
  worker.postMessage(response);
};
