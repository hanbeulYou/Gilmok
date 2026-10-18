import { describe, expect, it } from 'vitest';
import { academyRequest, academyUnavailable } from '../../lib/map/academy-view';
import { registerExposurePicker, exposureHitAt } from '../../lib/map/picking';
import type { ComparisonCandidate } from '../../lib/compare/store';
import type { Map } from 'maplibre-gl';

function row(): ComparisonCandidate {
  return { id:'synthetic', generation:1, stage:'scored', candidate:{lat:37.5,lng:127.05},
    inputs:{primary:{meta:{radius_m:800,sources:{academies:{available:true,source_version:'synthetic'}}}}},
    result:{axes:[{key:'cluster',evidence:{values:{n_field:0,field:'입시.검정 및 보습'}}}]} } as unknown as ComparisonCandidate;
}
describe('academy layer binds to the scored candidate',()=>{
  it('keeps exact scoring coordinates, radius, field, source and zero (not missing)',()=>{
    const r=row();const request=academyRequest(r)!;
    expect(request).toMatchObject({lat:37.5,lng:127.05,radius_m:800,field:'입시.검정 및 보습',expected_same_field_count:0});
    expect(request.expected_source).toBe(r.inputs!.primary!.meta.sources.academies);
  });
  it('does not combine a refreshed/incomplete candidate with old evidence',()=>{
    for(const change of [{refreshing:true},{stage:'scoring'},{inputs:undefined},{result:undefined}]) expect(academyRequest({...row(),...change} as ComparisonCandidate)).toBeNull();
    const missing=row(); delete missing.result!.axes[0].evidence.values.n_field;
    expect(academyRequest(missing)).toBeNull();
  });
  it('has distinct guidance for all four unavailable statuses',()=>{
    expect(new Set(Object.values(academyUnavailable)).size).toBe(4);
  });
  it('exposure hit priority is independent of registration order and removed on unmount',()=>{
    const map={} as Map;expect(exposureHitAt(map,1,2)).toBe(false);
    const remove=registerExposurePicker(map,(x,y)=>x===1&&y===2);
    expect(exposureHitAt(map,1,2)).toBe(true);expect(exposureHitAt(map,3,4)).toBe(false);
    remove();expect(exposureHitAt(map,1,2)).toBe(false);
  });
});
