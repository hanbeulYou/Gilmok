import { expect, it, vi } from 'vitest';
import { buildingCollection, buildingCoverage, createBuildingProjectionLoader, geometryItems, heightLabel } from '../../lib/map/buildings';
import { building, rectangle, scene } from '../visibility/fixtures';

function populated() {
  return { ...scene(), candidate_building_id: 'candidate', buildings: [
    building('candidate', rectangle(-5, -5, 5, 5)),
    { ...building('unknown', rectangle(10, 10, 15, 15), 4), height_source:'unknown' as const, estimated:true, source:'vworld_wfs' },
  ] };
}
it('distinguishes partial context from an uncovered scoring ring, unavailable sources and observed zero', () => {
  const a=populated(); a.coverage={...a.coverage,query_within_loaded_region:false};
  expect(buildingCoverage(a,true)).toContain('주변 반경 일부의 건물 자료가 없습니다.');
  expect(buildingCoverage(a,true).join()).not.toContain('노출 평가 불가');
  const outside={...a,buildings:[],coverage:{...a.coverage,score_ring_within_loaded_region:false}};
  expect(buildingCoverage(outside,false).join()).toContain('서울 밖');
  expect(buildingCoverage(outside,false).join()).toContain('노출 평가 불가');
  expect(buildingCoverage({...outside,sources:{}},true).join()).toContain('아직 적재되지');
  expect(buildingCoverage({...a,buildings:[],coverage:{...a.coverage,query_within_loaded_region:true}},true).join()).toContain('조회된 건물은 0개');
});
it('preserves holes/IDs/height metadata and rejects partial or reordered projection', () => {
  const value = populated();
  const items = geometryItems(value), original = structuredClone(value);
  const collection = buildingCollection(value, items);
  expect(collection.features[1].properties).toMatchObject({height_m:4,estimated:true,source:'vworld_wfs',height_source:'unknown'});
  expect(collection.features[0].properties.candidate).toBe(true);
  expect(heightLabel(value.buildings[1])).toContain('4m 가정');
  expect(() => buildingCollection(value, items.slice(1))).toThrow();
  expect(() => buildingCollection(value, [...items].reverse())).toThrow();
  expect(value).toEqual(original);
});
it('shares exact geometry between floors but invalidates source/geometry, retaining only two scenes', async () => {
  const fetcher = vi.fn(async (items) => items), loader = createBuildingProjectionLoader(fetcher);
  const a = populated(), b = {...a, candidate:[1, 0] as const}, c = {...a, candidate:[2, 0] as const};
  await loader.load(a); await loader.load({...a,floor:4}); expect(fetcher).toHaveBeenCalledTimes(1);
  await loader.load(b); await loader.load(c); await loader.load(a); expect(fetcher).toHaveBeenCalledTimes(4);
  await loader.load({...a,sources:{building_shp:{available:true,source_version:'new'}}});
  expect(fetcher).toHaveBeenCalledTimes(5);
  loader.dispose(); await loader.load(a); expect(fetcher).toHaveBeenCalledTimes(6);
});
it('serializes requests, discards a late aborted result and clears owner/route cache', async () => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release=resolve; });
  let active=0, max=0;
  const fetcher=vi.fn(async (items) => { active++; max=Math.max(max,active); await gate; active--; return items; });
  const loader=createBuildingProjectionLoader(fetcher), a=populated();
  const first=loader.load(a); const failed=expect(first).rejects.toMatchObject({name:'AbortError'});
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  loader.cancel(); const next=loader.load({...a,candidate:[1,0]});
  release(); await failed; await next;
  expect(max).toBe(1); loader.dispose();
});
it('keeps the two most recently used scenes, not just the two most recently inserted', async () => {
  const fetcher=vi.fn(async items=>items), loader=createBuildingProjectionLoader(fetcher), a=populated();
  await loader.load(a); await loader.load({...a,candidate:[1,0]}); await loader.load(a);
  await loader.load({...a,candidate:[2,0]}); await loader.load(a);
  expect(fetcher).toHaveBeenCalledTimes(3); loader.dispose();
});
