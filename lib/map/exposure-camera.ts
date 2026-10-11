import type {Map as LibreMap} from 'maplibre-gl';

type Render = (gl: WebGLRenderingContext | WebGL2RenderingContext, matrix: unknown,
  camera?: {nearZ: number; farZ: number}) => void;
const aligned = new WeakSet<object>();

/** MapLibre 4 sends camera planes as argument 3; deck 9.1 expects argument 2.
 * Forward the actual planes, without estimating or changing the map camera.
 * Scope this adapter to our interleaved custom layers, never the basemap.
 */
export function alignExposureCamera(map: Pick<LibreMap, 'getLayer'>, ids: readonly string[]) {
  for (const id of ids) {
    const layer = map.getLayer(id) as unknown as {implementation?: {render: Render}} | undefined;
    const implementation = layer?.implementation;
    if (!implementation || aligned.has(implementation)) continue;
    const render = implementation.render;
    implementation.render = function(gl, matrix, camera) {
      render.call(this, gl, camera ?? matrix);
    };
    aligned.add(implementation);
  }
}
