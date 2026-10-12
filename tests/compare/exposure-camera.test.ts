import {expect,it,vi} from 'vitest';
import type {Map as LibreMap} from 'maplibre-gl';
import {alignExposureCamera} from '../../lib/map/exposure-camera';
it('forwards MapLibre 4 camera planes once, preserving the custom-layer receiver',()=>{
 const draw=vi.fn(),implementation={render:draw},other={render:vi.fn()};
 const map={getLayer:(id:string)=>id==='sample'?{implementation}:id==='other'?{implementation:other}:undefined} as unknown as Pick<LibreMap,'getLayer'>;
 alignExposureCamera(map,['sample','missing']);const wrapped=implementation.render;
 alignExposureCamera(map,['sample']);expect(implementation.render).toBe(wrapped);
 const gl={} as WebGL2RenderingContext,matrix=[1,2,3],camera={nearZ:11,farZ:900};
 implementation.render(gl,matrix,camera);
 expect(draw).toHaveBeenCalledExactlyOnceWith(gl,camera);expect(draw.mock.contexts[0]).toBe(implementation);
 expect(other.render).not.toHaveBeenCalled();
 implementation.render(gl,camera);expect(draw).toHaveBeenLastCalledWith(gl,camera);
});
