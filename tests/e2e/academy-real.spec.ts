import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import type { Map as LibreMap } from 'maplibre-gl';
import { installMapProbe } from './building-3d';
import { academyV0 } from '../../lib/scoring/presets';
import { measureSliderSet, summarizeSliderSets } from './slider-performance';
import type { ReadyAcademyLayer } from '../../lib/map/academies';

type Candidate = {name:string;lat:number;lng:number;floor:number;address:string;score_n:number;expected_total:number};
type Proof = {url:string;key:string;session:{access_token:string;user:Record<string,unknown>};cases:Candidate[]};
const proof = (): Proof => JSON.parse(readFileSync('.local/academy-real/private.json','utf8'));
const allowed = new Set(['score_inputs','score_reference_percentiles','exposure_inputs_v022','project_exposure_geometry','compare_map_context','academy_layer']);
async function open(page:Page, expectMap=true) {
  page.setDefaultTimeout(15000);
  const config=proof(), calls:{name:string;status:number;ms:number}[]=[], layers=new Map<string,ReadyAcademyLayer>();
  await installMapProbe(page);
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if((url.hostname==='127.0.0.1'&&url.port==='3106')||url.hostname==='tiles.openfreemap.org'||(process.env.ACADEMY_PREVIEW_URL&&url.origin===new URL(process.env.ACADEMY_PREVIEW_URL).origin)){await route.continue();return;}
    if(url.hostname!==new URL(config.url).hostname&&(url.hostname!=='127.0.0.1'||url.port!=='56999')){await route.abort();throw Error('Unexpected outbound host '+url.hostname);}
    const send=(data:unknown)=>route.fulfill({json:data,headers:{'access-control-allow-origin':'*'}});
    if(route.request().method()==='OPTIONS'){await send({});return;}
    if(url.pathname.includes('/auth/')){await send(url.pathname.endsWith('/user')?config.session.user:config.session);return;}
    if(url.pathname.endsWith('/user_weight_presets')){await send([]);return;}
    const name=url.pathname.split('/').at(-1)!;
    if(name==='touch_user_activity'){await route.fulfill({status:204});return;}
    if(name==='load_comparison'){
      const ids=config.cases.map((_,i)=>`00000000-0000-4000-8000-00000000000${i+1}`);
      await send({comparison:{id:ids[0],candidate_ids:ids,weights:academyV0.weights,preset_version:'0.3',scoring_model_version:'0.4.0',reference_snapshot:'20261016T040000Z',manual_order:true},candidates:config.cases.map((c,i)=>({id:ids[i],alias:c.name,lat:c.lat,lng:c.lng,floor:c.floor,address:c.address,pnu:null,deposit:null,user_rent:null,management_fee:null,area_m2:null,address_provenance:{selection:{pnu:'',road_address:c.address},location:{lat:c.lat,lng:c.lng,provider:'vworld'}},registration_context:{status:'matched',context:{inside_seoul:true,seoul_boundary_distance_m:2000},building:null},lookup_status:'ready',lookup_request_id:null}))});return;
    }
    if(!allowed.has(name)){await route.abort();throw Error('Write/unexpected RPC blocked: '+name);}
    const start=Date.now();
    const response=await route.fetch({url:config.url+url.pathname+url.search,headers:{apikey:config.key,Authorization:'Bearer '+config.session.access_token,'content-type':'application/json'},timeout:30000});
    calls.push({name,status:response.status(),ms:Date.now()-start});
    expect(response.status(),`${name}: ${response.status()}`).toBe(200);
    const data=await response.json();
    if(name==='academy_layer')layers.set(JSON.stringify(data.center),data);
    if(name==='compare_map_context')await page.evaluate(data=>Reflect.set(window,'__gilmokRealContext',data),data);
    await route.fulfill({response,json:data});
  });
  await page.goto('/compare');
  await expect(page.locator('.desktop-matrix [data-total]')).toHaveCount(3,{timeout:60000});
  if(expectMap)await expect.poll(()=>page.evaluate(()=>Boolean(Reflect.get(window,'__gilmokProofMap')))).toBe(true);
  return {config,calls,layers};
}
async function select(page:Page,c:Candidate,mode:'2D'|'3D'){
  await page.locator('.map-candidate-list').getByRole('button',{name:new RegExp(`${c.name} · ${c.floor}층$`)}).click();
  await page.getByRole('button',{name:mode,exact:true}).click();
  if(mode==='3D')await expect(page.getByTestId('exposure-overlay')).toHaveAttribute('data-state','ready',{timeout:60000});
  await expect.poll(()=>page.evaluate(c=>{const m=Reflect.get(window,'__gilmokProofMap') as LibreMap;const context=Reflect.get(window,'__gilmokRealContext');const source=m.getSource('comparison-context') as unknown as {_data:unknown};return context?.center[0]===c.lng&&context?.center[1]===c.lat&&JSON.stringify(source?._data)===JSON.stringify(context.collection)&&!m.isMoving();},c),{timeout:60000}).toBe(true);
  await page.evaluate(({c,mode})=>{const m=Reflect.get(window,'__gilmokProofMap') as LibreMap;m.stop();m.jumpTo({center:[c.lng,c.lat],zoom:mode==='2D'?15:17,bearing:0});},{c,mode});
  await expect(page.getByTestId('academy-layer')).toHaveAttribute('data-state','ready',{timeout:60000});
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true',{timeout:60000});
  await expect(page.getByTestId('academy-n')).toHaveText(String(c.score_n));
}
test('promoted a/b/c: real RPC geometry, N/M, popup, evidence, overlay and slider',async({page},info)=>{
  test.setTimeout(300000);const {config,calls,layers}=await open(page);const results=[];
  const totals=await page.locator('.desktop-matrix [data-total]').evaluateAll(es=>es.map(e=>Number(e.getAttribute('data-total'))));
  expect(totals.map(x=>x.toFixed(4)).sort()).toEqual(config.cases.map(c=>c.expected_total.toFixed(4)).sort());
  for(const c of config.cases)for(const mode of ['2D','3D'] as const){
    await select(page,c,mode);
    const data=layers.get(JSON.stringify([c.lng,c.lat]))!;expect(data.status).toBe('ready');
    const rendered=await page.evaluate(()=>{const map=Reflect.get(window,'__gilmokProofMap') as LibreMap;const f=map.queryRenderedFeatures({layers:['academy-other','academy-same']});const source=(map.getSource('academy-institutions') as unknown as {_data:ReadyAcademyLayer['collection']})._data;return{source,m:new Set(f.filter(x=>x.properties.field==='입시.검정 및 보습').map(x=>x.id)).size,buildings:modeCount(map)};function modeCount(m:LibreMap){return m.getLayer('scored-buildings-3d')?m.queryRenderedFeatures({layers:['scored-buildings-3d']}).length:0;}});
    expect(rendered.source).toEqual({...data.collection,features:data.collection.features.map(f=>({...f,properties:{...f.properties,academy_id:String(f.id)}}))});await expect(page.getByTestId('academy-m')).toHaveText(String(rendered.m));
    if(mode==='2D'){
      await page.locator('.maplibregl-canvas').scrollIntoViewIfNeeded();
      const pick=await page.evaluate(()=>{const map=Reflect.get(window,'__gilmokProofMap') as LibreMap;for(const f of map.queryRenderedFeatures({layers:['academy-same','academy-other']})){if(f.geometry.type!=='Point')continue;const p=map.project(f.geometry.coordinates as [number,number]);const r=map.getCanvas().getBoundingClientRect();if(p.x>40&&p.y>40&&p.x<map.getCanvas().clientWidth-80&&p.y<map.getCanvas().clientHeight-80&&document.elementFromPoint(r.left+p.x,r.top+p.y)===map.getCanvas())return{x:p.x,y:p.y};}return null;});
      expect(pick).not.toBeNull();await page.locator('.maplibregl-canvas').click({position:pick!});
      await expect(page.getByTestId('academy-popup')).toBeVisible();await expect(page.getByTestId('academy-popup')).toContainText('층');
      const popupText=await page.getByTestId('academy-popup').innerText();expect(data.collection.features.some(f=>popupText.includes(f.properties.name))).toBe(true);
      const unobscured=await page.getByTestId('academy-popup').evaluate(el=>{const r=el.getBoundingClientRect();const target=document.elementFromPoint(r.left+r.width/2,r.bottom-5);return !!target&&el.contains(target);});expect(unobscured).toBe(true);
      await page.screenshot({path:info.outputPath(`${c.name}-popup.png`)});
      await page.locator('.maplibregl-popup-close-button').click();
    }
    await page.getByRole('button',{name:`${c.name} 학원 집적 근거`}).click();await expect(page.getByTestId('academy-radius-evidence')).toContainText(`반경 ${c.score_n}곳`);await page.getByRole('button',{name:'근거 닫기'}).click();
    await page.screenshot({path:info.outputPath(`${c.name}-${mode}.png`)});results.push({candidate:c.name,mode,n:c.score_n,m:rendered.m,features:data.collection.features.length,geometry_equal:true,buildings:rendered.buildings});
  }
  const before=calls.filter(x=>x.name==='academy_layer').length,sets=[];
  for(let i=0;i<3;i++){const set=await page.evaluate(measureSliderSet);expect(set.scoresChanged).toBe(true);expect(set.restored).toBe(true);sets.push(set.times);}
  const slider=summarizeSliderSets(sets,'production');expect(slider.passed).toBe(true);expect(calls.filter(x=>x.name==='academy_layer')).toHaveLength(before);
  await info.attach('real-render',{body:JSON.stringify({results,totals,slider,calls},null,2),contentType:'application/json'});
});
test('promoted a/b/c: real GPU FPS 2D/3D three sets',async({page},info)=>{
  test.skip(process.env.ACADEMY_FPS!=='1','Requires hardware gate');test.setTimeout(1500000);
  const {config,calls}=await open(page);const results=[];
  const cdp=await page.context().newCDPSession(page);
  const requested=process.env.ACADEMY_FPS_CASES?.split(',')??['a','b','c'];
  for(const c of config.cases.filter(c=>requested.includes(c.name)))for(const mode of ['2D','3D'] as const){await select(page,c,mode);for(let run=1;run<=3;run++){
    await page.bringToFront();const browserWindow=await cdp.send('Browser.getWindowForTarget');await cdp.send('Browser.setWindowBounds',{windowId:browserWindow.windowId,bounds:{left:0,top:30,width:1442,height:1050,windowState:'normal'}});
    const {bounds:windowBefore}=await cdp.send('Browser.getWindowBounds',{windowId:browserWindow.windowId});if(windowBefore.left===undefined||windowBefore.top===undefined||windowBefore.width===undefined||windowBefore.height===undefined)throw Error('Chrome window bounds missing');expect(windowBefore.left).toBeGreaterThanOrEqual(0);expect(windowBefore.top).toBeGreaterThanOrEqual(0);expect(windowBefore.left+windowBefore.width).toBeLessThanOrEqual(1920);expect(windowBefore.top+windowBefore.height).toBeLessThanOrEqual(1080);
    const before=calls.length;
    const sample=await page.evaluate(async c=>{const map=Reflect.get(window,'__gilmokProofMap') as LibreMap;const gl=map.getCanvas().getContext('webgl2')!,ext=gl.getExtension('WEBGL_debug_renderer_info');const renderer=ext?String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)):'unknown';const times:number[]=[];let first=0,last=0;const start=performance.now();const render=()=>{const n=performance.now();if(n-start<3000)return;if(!first)first=n;else times.push(n-last);last=n;};map.on('render',render);await new Promise<void>(resolve=>{function frame(now:number){const t=(now-start)/1000;map.jumpTo({center:[c.lng+Math.sin(t*.5)*.0006,c.lat+Math.cos(t*.5)*.0004]});if(now-start<63000)requestAnimationFrame(frame);else resolve();}requestAnimationFrame(frame);});map.off('render',render);const sorted=[...times].sort((a,b)=>a-b);return{renderer,averageFps:times.length*1000/(last-first),p95:sorted[Math.ceil(sorted.length*.95)-1],max:sorted.at(-1),frames:times.length,focus:document.hasFocus(),visible:document.visibilityState};},c);
    const {bounds:windowAfter}=await cdp.send('Browser.getWindowBounds',{windowId:browserWindow.windowId});expect(windowAfter).toEqual(windowBefore);expect(sample.averageFps,'60Hz environment changed').toBeLessThanOrEqual(65);
    results.push({candidate:c.name,mode,run,windowBefore,windowAfter,...sample});console.info('academy-real-fps',JSON.stringify(results.at(-1)));await info.attach(`fps-${c.name}-${mode}-${run}`,{body:JSON.stringify(results.at(-1)),contentType:'application/json'});
    expect(sample.renderer).toContain('Apple M5 Pro');expect(sample.focus).toBe(true);expect(sample.visible).toBe('visible');expect(sample.averageFps).toBeGreaterThanOrEqual(55);expect(sample.p95).toBeLessThanOrEqual(33.4);expect(calls.length).toBe(before);
  }}await info.attach('real-fps',{body:JSON.stringify(results,null,2),contentType:'application/json'});
});

test('promoted mobile: initial academy bundle/request zero and same scores',async({page},info)=>{
  test.setTimeout(120000);await page.setViewportSize({width:390,height:844});const {config,calls}=await open(page,false);
  await expect.poll(async()=>page.locator('.mobile-cards [data-total]').evaluateAll(es=>es.map(e=>Number(e.getAttribute('data-total')).toFixed(4)).sort())).toEqual(config.cases.map(c=>c.expected_total.toFixed(4)).sort());
  await expect(page.getByTestId('compare-map')).toHaveCount(0);expect(calls.filter(c=>['academy_layer','compare_map_context','project_exposure_geometry'].includes(c.name))).toEqual([]);
  const scripts=await page.evaluate(()=>performance.getEntriesByType('resource').map(e=>e.name).filter(n=>n.includes('/_next/')&&n.endsWith('.js'))), sizes=[];
  for(const url of scripts){const response=await page.request.get(url);const body=await response.body();expect(body.toString()).not.toContain('academy-institutions');sizes.push({file:new URL(url).pathname,raw:body.length,gzip:gzipSync(body).length});}
  await page.getByRole('tab',{name:'지도',exact:true}).click();await expect.poll(()=>page.evaluate(()=>Boolean(Reflect.get(window,'__gilmokProofMap')))).toBe(true);
  await select(page,config.cases[0],'2D');await expect(page.getByTestId('exposure-overlay')).toHaveCount(0);await page.screenshot({path:info.outputPath('real-mobile.png')});
  await info.attach('real-mobile',{body:JSON.stringify({initial_scripts:sizes,initial_js_gzip:sizes.reduce((n,s)=>n+s.gzip,0),n:config.cases[0].score_n,calls},null,2),contentType:'application/json'});
});
