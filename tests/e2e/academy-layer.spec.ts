import { test, expect, type Page } from '@playwright/test';
import type { Map as LibreMap } from 'maplibre-gl';
import { installMapProbe } from './building-3d';
import { mockAcademyApp, xy, center } from './academy-fixture';
import { measureSliderSet, summarizeSliderSets } from './slider-performance';

async function open(page: Page) {
  await installMapProbe(page);
  const mock = await mockAcademyApp(page);
  await page.goto('/compare');
  await expect(page.locator('.desktop-matrix [data-total]')).toHaveCount(3);
  await expect.poll(() => page.evaluate(() => Boolean(Reflect.get(window, '__gilmokProofMap')))).toBe(true);
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
  await zoom(page, 15);
  await expect(page.getByTestId('academy-layer')).toHaveAttribute('data-state', 'ready');
  return mock;
}
async function zoom(page: Page, value: number) {
  await page.evaluate(z => { const map=Reflect.get(window,'__gilmokProofMap') as LibreMap; map.stop(); map.jumpTo({zoom:z}); }, value);
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
}
async function clickPoint(page: Page, point: [number, number]) {
  const pixel=await page.evaluate(point => (Reflect.get(window,'__gilmokProofMap') as LibreMap).project(point),point);
  await page.locator('.maplibregl-canvas').click({position:pixel});
}

test('1,500 circles, N/M, popup privacy, retained zoom data, selection, exposure coexistence', async ({page},info) => {
  const mock=await open(page);
  await expect(page.getByTestId('academy-n')).toHaveText('500');
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
  await expect.poll(async () => Number(await page.getByTestId('academy-m').textContent())).toBeGreaterThan(0);
  const proof=await page.evaluate(() => {
    const map=Reflect.get(window,'__gilmokProofMap') as LibreMap;
    const features=map.queryRenderedFeatures({layers:['academy-other','academy-same']});
    return { layers:['academy-other','academy-same','academy-review'].map(id=>map.getLayer(id)?.type),
      m:new Set(features.filter(f=>f.properties.field==='입시.검정 및 보습').map(f=>f.id)).size,
      sourceCount:(map.getSource('academy-institutions') as unknown as {_data:{features:unknown[]}})._data.features.length };
  });
  expect(proof.layers).toEqual(['circle','circle','circle']); expect(proof.sourceCount).toBe(1500);
  await expect(page.getByTestId('academy-m')).toHaveText(String(proof.m));
  await page.getByRole('button',{name:'합성 1 학원 집적 근거',exact:true}).click();
  await expect(page.getByTestId('academy-radius-evidence')).toContainText('반경 500곳');
  await page.getByRole('button',{name:'근거 닫기'}).click();
  await clickPoint(page,xy(90,90));
  await expect(page.getByTestId('academy-popup')).toBeVisible();
  await expect(page.getByTestId('academy-popup')).toContainText('<b>합성기관</b>');
  await expect(page.getByTestId('academy-popup').locator('b')).toHaveCount(0);
  await expect(page.getByTestId('academy-popup')).toContainText('점수에서 자동 제외하지 않습니다');
  await page.getByLabel('겹친 학원 선택').selectOption('1');
  await expect(page.getByTestId('academy-popup')).toContainText('층 미표기');
  await expect(page.getByTestId('academy-popup')).not.toContainText('합성 주소');
  const fetched=mock.calls.filter(c=>c.name==='academy_layer').length;
  await zoom(page,14); await expect(page.getByTestId('academy-layer')).toHaveAttribute('data-state','hidden');
  await expect(page.getByTestId('academy-popup')).toHaveCount(0);
  await zoom(page,15); await expect(page.getByTestId('academy-layer')).toHaveAttribute('data-state','ready');
  expect(mock.calls.filter(c=>c.name==='academy_layer')).toHaveLength(fetched);
  await page.getByRole('button',{name:'3D',exact:true}).click();
  await expect(page.getByTestId('building-3d')).toHaveAttribute('data-state','ready');
  await expect(page.getByTestId('exposure-overlay')).toHaveAttribute('data-state','ready');
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
  await expect(page.getByTestId('academy-layer')).toHaveAttribute('data-state','ready');
  const overlap = await page.evaluate(() => {
    const map=Reflect.get(window,'__gilmokProofMap');
    const deck=map._controls.find((c:Record<string,unknown>)=>c._deck)._deck;
    const data=deck.props.layers.find((l:{id:string})=>l.id==='exposure-samples').props.data;
    const sample=data.find((d:{sample:{radius_m:number;bearing_deg:number}})=>d.sample.radius_m===20&&d.sample.bearing_deg===0);
    const p=deck.getViewports()[0].project(sample.point);
    return {x:p[0],y:p[1],sampleId:sample.sample.id,hit:deck.pickObject({x:p[0],y:p[1],layerIds:['exposure-samples']})?.object?.sample.id,
      academy:map.queryRenderedFeatures([p[0],p[1]],{layers:['academy-same']}).some((f:{id:string})=>f.id==='synthetic-12')};
  });
  expect(overlap.hit).toBe(overlap.sampleId); expect(overlap.academy).toBe(true);
  await page.locator('.maplibregl-canvas').click({position:{x:overlap.x,y:overlap.y}});
  await expect.poll(()=>page.getByTestId('exposure-overlay').getAttribute('data-selected-sample')).not.toBe('');
  await expect(page.getByTestId('academy-popup')).toHaveCount(0);
  await page.getByRole('button',{name:'근거 닫기'}).click();
  await clickPoint(page,xy(90,90)); await expect(page.getByTestId('academy-popup')).toBeVisible();
  await page.screenshot({path:info.outputPath('academy-3d.png')});
  await page.getByRole('button',{name:'2D',exact:true}).click(); await zoom(page,15);
  await page.screenshot({path:info.outputPath('academy-2d.png')});
  expect(mock.unexpected).toEqual([]);
  await info.attach('synthetic-render-proof',{body:JSON.stringify({proof,calls:mock.calls.filter(c=>c.name==='academy_layer')},null,2),contentType:'application/json'});
});

test('separate unavailable states and strict source/count validation',async({page})=>{
  for(const [status,text] of Object.entries({too_dense:'응답 용량 한도',coordinate_replacement_pending:'좌표 교체·검증',source_mismatch:'데이터 기준이 다릅니다',outside_coverage:'제공 범위(서울) 밖'})) {
    await page.unrouteAll(); await page.goto('about:blank');
    await installMapProbe(page); const mock=await mockAcademyApp(page); mock.control.status=status as typeof mock.control.status;
    await page.goto('/compare');
    await expect(page.locator('.desktop-matrix [data-total]')).toHaveCount(3);
    await expect.poll(()=>page.evaluate(()=>Boolean(Reflect.get(window,'__gilmokProofMap')))).toBe(true);
    await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true'); await zoom(page,15);
    await expect(page.getByTestId('academy-layer')).toHaveAttribute('data-state',status);
    await expect(page.getByTestId('academy-layer')).toContainText(text);
    expect(mock.unexpected).toEqual([]);
  }
});

test('candidate change aborts in-flight response; old status cannot overwrite new result', async ({page}) => {
  await installMapProbe(page); const mock=await mockAcademyApp(page);
  mock.control.status='outside_coverage'; mock.control.delay=2500;
  const cancelled:string[]=[]; page.on('requestfailed',r=>{if(r.url().endsWith('/academy_layer')) cancelled.push(r.failure()?.errorText??'failed');});
  await page.goto('/compare'); await expect(page.locator('.desktop-matrix [data-total]')).toHaveCount(3);
  await expect.poll(()=>page.evaluate(()=>Boolean(Reflect.get(window,'__gilmokProofMap')))).toBe(true);
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true'); await zoom(page,15);
  await expect.poll(()=>mock.calls.filter(c=>c.name==='academy_layer').length).toBe(1);
  mock.control.status='ready'; mock.control.delay=0;
  await page.locator('.map-candidate-list').getByRole('button',{name:/합성 2/}).click();
  await expect(page.getByTestId('academy-layer')).toHaveAttribute('data-state','ready');
  await expect.poll(()=>cancelled.length).toBe(1);
  await expect(page.getByTestId('academy-n')).toHaveText('500');
  expect(mock.calls.filter(c=>c.name==='academy_layer')).toHaveLength(2);
  expect(mock.unexpected).toEqual([]);
});

test('count/source contract mismatch fails closed instead of showing misleading N', async ({page}) => {
  await installMapProbe(page);const mock=await mockAcademyApp(page);mock.control.mismatch=true;
  await page.goto('/compare');await expect(page.locator('.desktop-matrix [data-total]')).toHaveCount(3);
  await expect.poll(()=>page.evaluate(()=>Boolean(Reflect.get(window,'__gilmokProofMap')))).toBe(true);
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');await zoom(page,15);
  await expect(page.getByTestId('academy-layer')).toHaveAttribute('data-state','error');
  await expect(page.getByTestId('academy-n')).toHaveCount(0);
  mock.control.mismatch=false;await page.getByRole('button',{name:'학원 다시 시도'}).click();
  await expect(page.getByTestId('academy-layer')).toHaveAttribute('data-state','ready');expect(mock.unexpected).toEqual([]);
});

test('mobile first render: map and academy bundle/requests absent',async({page},info)=>{
  await page.setViewportSize({width:390,height:844}); await installMapProbe(page); const mock=await mockAcademyApp(page);
  await page.goto('/compare'); await expect(page.locator('.mobile-cards [data-total]')).toHaveCount(3);
  await expect(page.getByTestId('compare-map')).toHaveCount(0);
  expect(mock.calls.filter(c=>['academy_layer','compare_map_context','project_exposure_geometry'].includes(c.name))).toEqual([]);
  const scripts=await page.evaluate(()=>performance.getEntriesByType('resource').map(e=>e.name).filter(n=>n.includes('/_next/')&&n.endsWith('.js')));
  for(const url of scripts) { const script=await page.request.get(url); expect(await script.text()).not.toContain('academy-institutions'); }
  await info.attach('initial-scripts',{body:JSON.stringify(scripts,null,2),contentType:'application/json'});
  await page.getByRole('tab',{name:'지도',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>Boolean(Reflect.get(window,'__gilmokProofMap')))).toBe(true);
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');await zoom(page,15);
  await expect(page.getByTestId('academy-n')).toHaveText('500');
  await expect(page.getByTestId('exposure-overlay')).toHaveCount(0);
  await page.screenshot({path:info.outputPath('academy-mobile.png')});
  expect(mock.unexpected).toEqual([]);
});

test('slider 100 × 3 with academy layer visible',async({page},info)=>{
  const mock=await open(page);
  const callsBefore=mock.calls.filter(c=>c.name==='academy_layer').length;
  const sets=[];for(let i=0;i<3;i++) { const set=await page.evaluate(measureSliderSet);expect(set.scoresChanged).toBe(true);expect(set.restored).toBe(true);sets.push(set.times); }
  expect(mock.calls.filter(c=>c.name==='academy_layer')).toHaveLength(callsBefore);
  await expect(page.getByTestId('academy-n')).toHaveText('500');
  const result=summarizeSliderSets(sets,'ci');
  await info.attach('slider-performance',{body:JSON.stringify(result,null,2),contentType:'application/json'});
  expect(result.passed).toBe(true); expect(mock.unexpected).toEqual([]);
});

test('real GPU FPS: 2D and 3D, 1,500 institutions',async({page},info)=>{
  test.skip(process.env.ACADEMY_FPS!=='1','Requires verified AC/60Hz/low-power off and real M5 Pro GPU');
  const mock=await open(page); const results=[];
  for(const mode of ['2D','3D'] as const) {
    await page.getByRole('button',{name:mode,exact:true}).click();
    if(mode==='3D') { await expect(page.getByTestId('exposure-overlay')).toHaveAttribute('data-state','ready'); }
    await zoom(page,mode==='2D'?15:17);
    for(let run=0;run<3;run++) {
      const sample=await page.evaluate(async({center})=>{
        const map=Reflect.get(window,'__gilmokProofMap') as LibreMap;
        const gl=map.getCanvas().getContext('webgl2')!; const extension=gl.getExtension('WEBGL_debug_renderer_info');
        const renderer=extension?gl.getParameter(extension.UNMASKED_RENDERER_WEBGL):'unknown';
        const times:number[]=[];let last=0,first=0,request=0;
        const start=performance.now(),duration=63000;
        const rendered=()=>{const now=performance.now();if(now-start<3000)return;if(!first)first=now;else times.push(now-last);last=now;};
        map.on('render',rendered);
        await new Promise<void>(resolve=>{const frame=(now:number)=>{
          const t=(now-start)/1000;map.jumpTo({center:[center[0]+Math.sin(t*.5)*.0006,center[1]+Math.cos(t*.5)*.0004]});
          if(now-start<duration)request=requestAnimationFrame(frame);else resolve();};request=requestAnimationFrame(frame);});
        cancelAnimationFrame(request);map.off('render',rendered);
        const sorted=[...times].sort((a,b)=>a-b);return{renderer,frames:times.length,durationMs:last-first,averageFps:times.length*1000/(last-first),p95:sorted[Math.ceil(sorted.length*.95)-1],max:sorted.at(-1)};
      },{center});
      results.push({mode,run:run+1,...sample}); expect(sample.renderer).toContain('Apple'); expect(sample.averageFps).toBeGreaterThanOrEqual(55); expect(sample.p95).toBeLessThanOrEqual(33.4);
    }
  }
  await info.attach('fps',{body:JSON.stringify(results,null,2),contentType:'application/json'}); expect(mock.unexpected).toEqual([]);
});

for (const mode of ['2D', '3D'] as const) test(`academy cleanup ${mode} survives navigation to candidate registration`, async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.stack ?? error.message));
  const mock = await open(page);
  if (mode === '3D') {
    await page.getByRole('button', { name: '3D', exact: true }).click();
    await expect(page.getByTestId('building-3d')).toHaveAttribute('data-state', 'ready');
    await expect(page.getByTestId('exposure-overlay')).toHaveAttribute('data-state', 'ready');
  }
  await page.getByRole('link', { name: '후보 추가', exact: true }).first().click();
  await expect(page).toHaveURL(/\/new$/);
  await info.attach('navigation-errors', { body: JSON.stringify(errors), contentType: 'application/json' });
  expect(errors).toEqual([]);
  await expect(page.getByLabel('주소 *', { exact: true })).toBeEnabled();
  expect(mock.unexpected).toEqual([]);
});
