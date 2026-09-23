import { describe, expect, it } from 'vitest';
import { createVisibilityClient } from '../../lib/visibility/client.ts';
import type { VisibilityWorkerPort } from '../../lib/visibility/client.ts';
import type { VisibilityRequest, VisibilityResponse } from '../../lib/visibility/types.ts';
import { computeVisibility } from '../../lib/visibility/compute.ts';
import { scene } from './fixtures.ts';
class Port implements VisibilityWorkerPort {
  sent: VisibilityRequest[] = [];
  message: ((event: { data: VisibilityResponse }) => void) | undefined;
  error: (() => void) | undefined;
  postMessage(request: VisibilityRequest) { this.sent.push(request); }
  addEventListener(type: 'message', listener: (event: { data: VisibilityResponse }) => void): void;
  addEventListener(type: 'error', listener: () => void): void;
  addEventListener(type: string, listener: ((event: { data: VisibilityResponse }) => void) | (() => void)) {
    if (type === 'message') this.message = listener as (event: { data: VisibilityResponse }) => void;
    else this.error = listener as () => void;
  }
  removeEventListener(type: 'message', listener: (event: { data: VisibilityResponse }) => void): void;
  removeEventListener(type: 'error', listener: () => void): void;
  removeEventListener(type: string) { if (type === 'message') this.message = undefined; else this.error = undefined; }
}
describe('Worker caller request identity and failures', () => {
  it('matches replies to the originating request, including out of order replies', async () => {
    const port = new Port(), client = createVisibilityClient(port);
    const a = client.request(scene()), b = client.request({ ...scene(), floor: 4 });
    const result = computeVisibility(scene());
    port.message!({ data: { requestId: b.requestId, result, computeMs: 1 } });
    port.message!({ data: { requestId: a.requestId, result, computeMs: 2 } });
    expect((await a.response).requestId).toBe(a.requestId);
    expect((await b.response).requestId).toBe(b.requestId);
    expect(port.sent.map(r => r.scene.floor)).toEqual([3, 4]);
    client.dispose(); expect(port.message).toBeUndefined(); expect(port.error).toBeUndefined();
  });
  it('rejects a failed request and recovers, but closes on a fatal Worker error', async () => {
    const port = new Port(), client = createVisibilityClient(port);
    const a = client.request(scene()), failed = expect(a.response).rejects.toThrow('bad scene');
    port.message!({ data: { requestId: a.requestId, error: 'bad scene' } }); await failed;
    const b = client.request(scene()), crashed = expect(b.response).rejects.toThrow('worker_failed');
    port.error!(); await crashed;
    await expect(client.request(scene()).response).rejects.toThrow('client_closed');
    client.dispose();
  });
});
