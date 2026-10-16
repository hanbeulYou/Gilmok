import { describe, expect, it, vi } from 'vitest';
import { academyLayerArgs, academyViewportCounts, createAcademyLayerLoader, parseAcademyLayer,
  type AcademyLayerRequest, type ReadyAcademyLayer } from '../../lib/map/academies';

function request(field='보습'): AcademyLayerRequest {
  return {lat:37.5,lng:127,radius_m:800,field,expected_source:{available:true,source_version:'synthetic'},expected_same_field_count:2};
}
function response(r=request()): ReadyAcademyLayer {
  return {schema_version:'1.0',status:'ready',reason:null,center:[r.lng,r.lat],radius_m:r.radius_m,field:r.field,
    collection:{type:'FeatureCollection',features:[0,1,2].map(i=>({type:'Feature',id:`synthetic-${i}`,
      geometry:{type:'Point',coordinates:[127,37.5]},properties:{name:i===0?'<b>합성 공개 기관</b>':'합성 기관',
        field:i<2?r.field:'예능',floor_label:i===0?'지하 1층':null,floor_status:i===0?'explicit':'missing',
        coordinate_verification_pending:i===0,coordinate_review_reason:i===0?'movement_gt_500m':null,
        coordinate_review_version:i===0?'fixture-review':null}}))},
    counts:{radius_all:3,radius_same_field:2,radius_pending:1,radius_same_field_pending:1,by_field:{[r.field]:2,'예능':1}},
    meta:{crs:'EPSG:4326',source:{...r.expected_source},source_revision:'fixture',coordinate_provider:'juso',
      review_version:'fixture-review',unlocated_count_seoul:6,quality_inventory:{academy:99,school:2}}};
}

describe('academy layer contract, synthetic only',()=>{
  it('uses scoring coordinates without rounding and sends no personal candidate fields',()=>{
    const r={...request(),lng:127.0000000000001};
    expect(academyLayerArgs(r)).toEqual({lat:r.lat,lng:r.lng,radius_m:800,requested_field:'보습',expected_source:r.expected_source});
    expect(parseAcademyLayer(response(r),r).center).toEqual([r.lng,r.lat]);
    expect(()=>parseAcademyLayer(response(),r)).toThrow('재계산');
  });
  it('preserves all fields, public name as text and explicit floor; counts institutions, not coordinates',()=>{
    const value=parseAcademyLayer(response(),request()) as ReadyAcademyLayer;
    expect(value.collection.features).toHaveLength(3);
    expect(value.collection.features[0].properties.name).toBe('<b>합성 공개 기관</b>');
    expect(academyViewportCounts(value,['synthetic-0','synthetic-0','synthetic-2','unknown']))
      .toEqual({radiusSameFieldN:2,viewportSameFieldM:1,viewportAll:2,radiusSameFieldPending:1,viewportSameFieldPending:1});
    expect(academyViewportCounts(value,[]).radiusSameFieldN).toBe(2);
    expect(academyViewportCounts(value,[]).viewportSameFieldM).toBe(0);
  });
  it.each(['outside_coverage','coordinate_replacement_pending','source_mismatch'] as const)('keeps %s distinct from ready zero',status=>{
    const value={...response(),status,reason:'fixture',collection:null,counts:null,meta:null};
    expect(parseAcademyLayer(value,request()).status).toBe(status);
    expect(()=>parseAcademyLayer({...value,collection:{type:'FeatureCollection',features:[]}},request())).toThrow();
  });
  it('accepts genuine zero and explicit too_dense without partial features',()=>{
    const r={...request(),expected_same_field_count:0},v=response(r);
    v.collection.features=[];v.counts={radius_all:0,radius_same_field:0,radius_pending:0,radius_same_field_pending:0,by_field:{}};
    expect(parseAcademyLayer(v,r).status).toBe('ready');
    expect(parseAcademyLayer({...v,status:'too_dense',reason:'response_budget_exceeded',counts:null,collection:null,
      meta:{radius_count:5001,jsonb_bytes:1900000,raw_budget_bytes:1572864}},r).status).toBe('too_dense');
  });
  it.each([
    (v: ReadyAcademyLayer)=>{v.meta.source.source_version='old';},
    (v: ReadyAcademyLayer)=>{v.counts.radius_same_field=1;},
    (v: ReadyAcademyLayer)=>{v.counts.by_field['보습']=3;},
    (v: ReadyAcademyLayer)=>{v.collection.features[1].id=v.collection.features[0].id;},
    (v: ReadyAcademyLayer)=>{v.collection.features[1].properties.floor_label='301호';},
    (v: ReadyAcademyLayer)=>{v.collection.features[0].properties.coordinate_review_version='old';},
    (v: ReadyAcademyLayer)=>{Object.assign(v.collection.features[0].properties,{phone:'hidden'});},
  ])('rejects stale source, counts, duplicate IDs, inferred floors or extra personal fields',mutate=>{
    const v=response();mutate(v);expect(()=>parseAcademyLayer(v,request())).toThrow('재계산');
  });
  it('rejects a missing scoring count/source before calling an RPC',()=>{
    expect(()=>academyLayerArgs({...request(),expected_same_field_count:NaN})).toThrow();
    expect(()=>academyLayerArgs({...request(),expected_source:{}})).toThrow();
  });
});

describe('academy loader generations and bounded memory',()=>{
  it('reuses matching response but not a changed scoring source/radius/field',async()=>{
    const fetcher=vi.fn(async(args: ReturnType<typeof academyLayerArgs>)=>response({
      ...request(args.requested_field),lat:args.lat,lng:args.lng,radius_m:args.radius_m,expected_source:args.expected_source}));
    const loader=createAcademyLayerLoader(fetcher);
    await loader.load(request());await loader.load(request());expect(fetcher).toHaveBeenCalledTimes(1);
    await loader.load({...request(),radius_m:1000});await loader.load(request('국제화'));
    await loader.load({...request(),expected_source:{available:true,source_version:'new'}});
    expect(fetcher).toHaveBeenCalledTimes(4);loader.dispose();
  });
  it('never caches missing states and evicts beyond five requests',async()=>{
    const fetcher=vi.fn(async(args: ReturnType<typeof academyLayerArgs>)=>response({...request(),lng:args.lng}));
    const loader=createAcademyLayerLoader(fetcher);
    for(let i=0;i<6;i++)await loader.load({...request(),lng:127+i/1000});
    await loader.load(request());expect(fetcher).toHaveBeenCalledTimes(7);loader.dispose();
    const missing={...response(),status:'coordinate_replacement_pending',reason:'release_missing',collection:null,counts:null,meta:null};
    const unavailable=vi.fn(async()=>missing),other=createAcademyLayerLoader(unavailable);
    await other.load(request());await other.load(request());expect(unavailable).toHaveBeenCalledTimes(2);other.dispose();
  });
  it('aborts previous work and rejects late results even if the fetcher ignores abort',async()=>{
    let resolve!: (v:unknown)=>void;
    const fetcher=vi.fn().mockImplementationOnce(()=>new Promise(r=>{resolve=r;})).mockResolvedValue(response({...request(),lng:127.01}));
    const loader=createAcademyLayerLoader(fetcher),first=loader.load(request());
    const rejected=expect(first).rejects.toMatchObject({name:'AbortError'});
    await vi.waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(1));
    const second=loader.load({...request(),lng:127.01});
    expect(fetcher.mock.calls[0][1].aborted).toBe(true);
    resolve(response());await rejected;await expect(second).resolves.toMatchObject({center:[127.01,37.5]});loader.dispose();
  });
  it('rejects disposed in-flight results and skips superseded queued requests',async()=>{
    const fetcher=vi.fn(async()=>response());const loader=createAcademyLayerLoader(fetcher);
    const first=loader.load(request());const rejected=expect(first).rejects.toMatchObject({name:'AbortError'});
    loader.dispose();await rejected;expect(fetcher).not.toHaveBeenCalled();
  });
});
