import type { VisibilityRequest, VisibilityResponse, VisibilityScene } from './types.ts';
/** Structural port keeps browser globals out of the pure/Node graph. Caller owns the Worker. */
export interface VisibilityWorkerPort {
  postMessage(message: VisibilityRequest): void;
  addEventListener(type: 'message', listener: (event: { data: VisibilityResponse }) => void): void;
  addEventListener(type: 'error', listener: () => void): void;
  removeEventListener(type: 'message', listener: (event: { data: VisibilityResponse }) => void): void;
  removeEventListener(type: 'error', listener: () => void): void;
}
export function createVisibilityClient(worker: VisibilityWorkerPort) {
  let sequence = 0, closed = false;
  const pending = new Map<string, { resolve: (r: VisibilityResponse) => void; reject: (error: Error) => void }>();
  const message = (event: { data: VisibilityResponse }) => {
    const request = pending.get(event.data.requestId);
    if (!request) return;
    pending.delete(event.data.requestId);
    if ('error' in event.data) request.reject(new Error(event.data.error));
    else request.resolve(event.data);
  };
  const fail = () => { closed = true; for (const request of pending.values()) request.reject(new Error('visibility_worker_failed')); pending.clear(); };
  worker.addEventListener('message', message); worker.addEventListener('error', fail);
  return {
    request(scene: VisibilityScene) {
      const requestId = String(++sequence);
      const response = new Promise<VisibilityResponse>((resolve, reject) => {
        if (closed) { reject(new Error('visibility_client_closed')); return; }
        pending.set(requestId, { resolve, reject });
        try { worker.postMessage({ requestId, scene }); }
        catch (error) { pending.delete(requestId); reject(error); }
      });
      return { requestId, response };
    },
    dispose() { closed = true; fail(); worker.removeEventListener('message', message); worker.removeEventListener('error', fail); },
  };
}
