import type { Map } from 'maplibre-gl';

// The visible deck.gl sample wins over an academy circle at the same pixel.
// A synchronous pick avoids listener registration order and DOM event races.
const exposurePickers = new WeakMap<Map, (x: number, y: number) => boolean>();
export function registerExposurePicker(map: Map, pick: (x: number, y: number) => boolean) {
  exposurePickers.set(map, pick);
  return () => { if (exposurePickers.get(map) === pick) exposurePickers.delete(map); };
}
export function exposureHitAt(map: Map, x: number, y: number) {
  return exposurePickers.get(map)?.(x, y) ?? false;
}
