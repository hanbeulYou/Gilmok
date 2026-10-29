import type { Page } from '@playwright/test';
import type { AcademyLayer, AcademyLayerRequest, ReadyAcademyLayer } from '../../lib/map/academies';
import { academyV0 } from '../../lib/scoring/presets';
import { inputs, reference } from '../scoring/fixtures';
import { building, rectangle, scene } from '../visibility/fixtures';
export const center = [127.05, 37.5] as const;
export const xy = (x: number, y: number): [number, number] => [center[0] + x / 88000, center[1] + y / 111000];
const ids = ['00000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000002','00000000-0000-4000-8000-000000000003'];
export function institutions(r: AcademyLayerRequest): ReadyAcademyLayer {
  const fields = [r.field, '예능', '직업기술'];
  const features: ReadyAcademyLayer['collection']['features'] = Array.from({ length: 1500 }, (_, i) => {
    const angle = i * 2.3999632297, radius = 750 * Math.sqrt((i + 1) / 1500);
    const point = i < 10 ? xy(90, 90) : xy(Math.cos(angle) * radius, Math.sin(angle) * radius);
    // One academy coincides exactly with the 20m north exposure sample.
    if (i === 12) point.splice(0, 2, ...xy(0, 20));
    return { type: 'Feature', id: `synthetic-${i}`, geometry: { type: 'Point', coordinates: point },
      properties: { name: i === 0 ? '<b>합성기관</b>' : `합성 학원 ${i}`, field: fields[i % 3],
        floor_label: i % 3 === 0 ? '3층' : null, floor_status: i % 3 === 0 ? 'explicit' : i % 3 === 1 ? 'missing' : 'ambiguous',
        coordinate_verification_pending: i < 99, coordinate_review_reason: i < 99 ? 'movement_gt_500m' : null,
        coordinate_review_version: i < 99 ? 'synthetic-review' : null } };
  });
  return { schema_version: '1.0', status: 'ready', reason: null, center: [r.lng, r.lat], radius_m: r.radius_m, field: r.field,
    collection: { type: 'FeatureCollection', features },
    counts: { radius_all: 1500, radius_same_field: 500, radius_pending: 99, radius_same_field_pending: 33,
      by_field: Object.fromEntries(fields.map(field => [field, 500])) },
    meta: { crs: 'EPSG:4326', source: { ...r.expected_source }, source_revision: 'synthetic-only', coordinate_provider: 'juso',
      review_version: 'synthetic-review', unlocated_count_seoul: 0, quality_inventory: { academy: 99, school: 0 } } };
}
export async function mockAcademyApp(page: Page) {
  const calls: { name: string; args: Record<string, unknown> }[] = [], unexpected: string[] = [];
  const control = { status: 'ready' as AcademyLayer['status'], delay: 0, mismatch: false };
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.hostname === '127.0.0.1' && url.port === '3106') { await route.continue(); return; }
    const send = (data: unknown) => route.fulfill({ json: data, headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*' } });
    if (url.hostname === 'map.gilmok.test') { await send({ version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#eee' } }] }); return; }
    if (url.hostname !== '127.0.0.1' || url.port !== '56999') { unexpected.push(url.href); await route.abort(); return; }
    if (route.request().method() === 'OPTIONS') { await send({}); return; }
    const user = { id: '11111111-1111-4111-8111-111111111111', aud: 'authenticated', role: 'authenticated', is_anonymous: true, created_at: new Date().toISOString() };
    if (url.pathname.includes('/auth/')) {
      const jwt = [Buffer.from(JSON.stringify({ alg: 'HS256' })).toString('base64url'), Buffer.from(JSON.stringify({ sub: user.id, exp: Math.floor(Date.now()/1000)+3600, role: 'authenticated' })).toString('base64url'), 'synthetic'].join('.');
      await send(url.pathname.endsWith('/user') ? user : { access_token: jwt, refresh_token: 'synthetic-refresh', expires_in: 3600, token_type: 'bearer', user }); return;
    }
    if (url.pathname.endsWith('/user_weight_presets')) { await send([]); return; }
    const name = url.pathname.split('/').at(-1)!, args = route.request().postDataJSON() ?? {};
    calls.push({ name, args });
    if (name === 'touch_user_activity') { await send(null); return; }
    if (name === 'load_comparison') {
      await send({ comparison: { id: ids[0], candidate_ids: ids, weights: academyV0.weights, preset_version: '0.3', scoring_model_version: '0.4.0', reference_snapshot: 'synthetic', manual_order: false },
        candidates: ids.map((id, i) => ({ id, alias: `합성 ${i+1}`, lat: center[1], lng: center[0], floor: i+1, address: '합성 주소',
          pnu: null, deposit: null, user_rent: null, management_fee: null, area_m2: 100,
          address_provenance: { selection: { pnu: '', road_address: '합성 주소' }, location: { lat: center[1], lng: center[0], provider: 'juso' } },
          registration_context: { status: 'matched', context: { inside_seoul: true, seoul_boundary_distance_m: 2000 }, building: null }, lookup_status: 'ready', lookup_request_id: null })) }); return;
    }
    if (name === 'score_inputs') {
      const value = inputs(args.radius_m); value.meta.floor = args.floor; value.compete.academies_by_field = { [academyV0.cluster_field]: 500 };
      await send(value); return;
    }
    if (name === 'score_reference_percentiles') {
      const base = reference();
      await send({ ...base, distributions: undefined, kind: 'percentiles', percentiles: Object.entries(args.requested_raw).map(([key, raw]) => ({
        radius_m: 800, key, raw, percentile: raw === null ? null : 50, cell_count: 4, population_size: 3,
        histogram: { min: 0, max: 10000, bins: [1,1,1,...Array(17).fill(0)] } })) }); return;
    }
    if (name === 'exposure_inputs_v022') {
      const value = scene();
      // Synthetic metre grid: 900 buildings, no obstruction inside the 60m rings.
      for (let x=-15;x<15;x++) for (let y=-15;y<15;y++) {
        const bx=x*32+16, by=y*32+16; if (Math.hypot(bx,by)<80) continue;
        const b=building(`${x}:${y}`,rectangle(bx,by,bx+12,by+12),Math.abs(x+y)%3===0?4:12);
        if (Math.abs(x+y)%3===0) { b.height_source='unknown'; b.estimated=true; }
        else if (Math.abs(x+y)%3===1) { b.height_source='floors_estimate'; b.estimated=true; }
        value.buildings = [...value.buildings, b];
      }
      await send(value); return;
    }
    if (name === 'project_exposure_geometry') {
      const convert = (c: number[] | unknown[]): unknown => typeof c[0] === 'number' ? xy(c[0], c[1] as number) : c.map(p => convert(p as unknown[]));
      await send(args.items.map((item: { id: string; geometry: { type: string; coordinates: unknown[] } }) => ({ ...item, geometry: { ...item.geometry, coordinates: convert(item.geometry.coordinates) } }))); return;
    }
    if (name === 'compare_map_context') {
      const source={available:true,source_versions:['synthetic'],sources:['synthetic'],latest_ingested_at:null,unlocated_count:0};
      await send({ schema_version:'1.0',center:[args.lng,args.lat],collection:{type:'FeatureCollection',features:[]},meta:{covered:true,crs:'EPSG:4326',sources:{transit_stops:source,schools:source}} }); return;
    }
    if (name === 'academy_layer') {
      const r={lat:args.lat,lng:args.lng,radius_m:args.radius_m,field:args.requested_field,expected_source:args.expected_source,expected_same_field_count:500};
      const status=control.status, mismatch=control.mismatch, delay=control.delay;
      if (delay) await new Promise(resolve => setTimeout(resolve,delay));
      const ready=institutions(r); if (mismatch) ready.counts.radius_same_field--;
      const data=status==='ready'?ready:{schema_version:'1.0',center:ready.center,radius_m:r.radius_m,field:r.field,status,reason:status==='too_dense'?'response_budget_exceeded':'synthetic',collection:null,counts:null,meta:status==='too_dense'?{radius_count:50000,jsonb_bytes:2000000,raw_budget_bytes:1572864}:null};
      await send(data); return;
    }
    unexpected.push(url.href); await route.abort();
  });
  return { calls, unexpected, control };
}
