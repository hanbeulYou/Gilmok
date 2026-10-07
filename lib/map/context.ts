import type { MapContext } from './features';

/** One request at a time; share identical work and skip selections superseded in the queue. */
export function createMapContextLoader(fetcher: (lat: number, lng: number, signal: AbortSignal) => Promise<MapContext>) {
  const cache = new Map<string, MapContext>(), pending = new Map<string, Promise<MapContext>>();
  let wanted = '', queue: Promise<unknown> = Promise.resolve(), controller: AbortController | undefined;
  return {
    load(lat: number, lng: number, fingerprint: string): Promise<MapContext> {
      const key = JSON.stringify([lat, lng, fingerprint]); wanted = key;
      const cached = cache.get(key); if (cached) return Promise.resolve(cached);
      const running = pending.get(key); if (running) return running;
      const job = queue.catch(() => undefined).then(async () => {
        if (wanted !== key) throw new DOMException('Selection changed', 'AbortError');
        controller = new AbortController();
        const timer = setTimeout(() => controller?.abort(), 15000);
        try {
          const value = await fetcher(lat, lng, controller.signal);
          if (value.schema_version !== '1.0' || value.center[0] !== lng || value.center[1] !== lat)
            throw new Error('지도 중심 좌표를 확인하지 못했습니다.');
          cache.set(key, value);
          if (cache.size > 10) cache.delete(cache.keys().next().value!);
          return value;
        } finally { clearTimeout(timer); controller = undefined; }
      }).finally(() => { pending.delete(key); });
      pending.set(key, job); queue = job; return job;
    },
    dispose() { wanted = ''; controller?.abort(); cache.clear(); },
  };
}
