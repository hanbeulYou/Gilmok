import { expect, type Page, type TestInfo } from '@playwright/test';
import type { Map as LibreMap } from 'maplibre-gl';

/** Read the existing React ref from the map host; no injected renderer or product debug API. */
export async function installMapProbe(page: Page) {
  await page.addInitScript(() => {
    Object.defineProperty(window, '__gilmokProofMap', { get() {
      const host = document.querySelector('[data-testid="compare-map"]');
      if (!host) return undefined;
      const key = Object.keys(host).find(key => key.startsWith('__reactFiber$'));
      let fiber = key ? Reflect.get(host, key) : undefined;
      while (fiber) {
        let hook = fiber.memoizedState;
        while (hook && typeof hook === 'object') {
          const current = hook.memoizedState?.current;
          if (typeof current?.getCanvas === 'function' && current.getCanvas() === host.querySelector('canvas')) return current;
          hook = hook.next;
        }
        fiber = fiber.return;
      }
      return undefined;
    } });
  });
}

export async function checkBuilding3D(page: Page, info: TestInfo) {
  const calls: string[] = [];
  const resourcesBefore = await page.evaluate(() => performance.getEntriesByType('resource').map(entry=>entry.name));
  expect(resourcesBefore.filter(url=>url.endsWith('/rpc/project_exposure_geometry'))).toEqual([]);
  const scoringCalls: string[] = [], http: {requestBytes:number;responseBytes:number;durationMs:number;status:number}[] = [];
  const workersBefore = await page.locator('html').getAttribute('data-exposure-runs');
  page.on('request', request => { if (request.url().endsWith('/rpc/project_exposure_geometry')) calls.push(request.url()); });
  page.on('request', request => { if (/\/rpc\/(score_inputs|exposure_inputs_v022|score_reference_percentiles)$/.test(request.url())) scoringCalls.push(request.url()); });
  page.on('response', async response => {
    if (!response.url().endsWith('/rpc/project_exposure_geometry')) return;
    await response.finished();
    http.push({requestBytes:Buffer.byteLength(response.request().postData() ?? ''),responseBytes:(await response.body()).length,
      durationMs:response.request().timing().responseEnd,status:response.status()});
  });
  const camera = () => page.evaluate(() => {
    const map = Reflect.get(window, '__gilmokProofMap') as LibreMap;
    return { center:map.getCenter().toArray(), zoom:map.getZoom(), pitch:map.getPitch(), bearing:map.getBearing() };
  });
  await expect.poll(() => page.evaluate(() => !!Reflect.get(window, '__gilmokProofMap'))).toBe(true);
  await page.locator('.map-candidate-list').getByRole('button', { name:/a · 3층$/ }).click();
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
  const before = await camera();
  await expect(page.getByTestId('building-3d')).toHaveCount(0); expect(calls).toHaveLength(0);
  const first3DStart=Date.now();
  await page.getByRole('button', { name:'3D', exact:true }).click();
  await expect(page.getByTestId('building-3d')).toHaveAttribute('data-state','ready');
  await expect(page.getByTestId('building-3d')).toHaveAttribute('data-building-count','4693');
  await expect(page.getByTestId('building-3d')).toContainText('주변 반경 일부의 건물 자료가 없습니다');
  await expect(page.getByTestId('building-3d')).not.toContainText('노출 평가 불가');
  await expect.poll(async () => (await camera()).pitch).toBeCloseTo(55,7);
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
  const first3DReadyMs=Date.now()-first3DStart;
  const proof = await page.evaluate(() => {
    const map = Reflect.get(window, '__gilmokProofMap') as LibreMap;
    const data = (map.getSource('scored-buildings') as unknown as { _data: {features: { id:string;properties:Record<string, unknown> }[]} })._data;
    return { count:data.features.length, unknown:data.features.filter(f=>f.properties.height_source==='unknown').length,
      estimated:data.features.filter(f=>f.properties.height_source==='floors_estimate').length,
      renderedIdsValid:map.queryRenderedFeatures({layers:['scored-buildings-3d']}).every(f=>f.id===f.properties.id),
      layer:map.getLayer('scored-buildings-3d')?.type, camera:{pitch:map.getPitch(),zoom:map.getZoom()},
      otherExtrusions:map.getStyle().layers.filter(l=>l.type==='fill-extrusion' && l.id!=='scored-buildings-3d').length };
  });
  expect(proof).toMatchObject({count:4693,unknown:784,estimated:948,layer:'fill-extrusion',otherExtrusions:0,renderedIdsValid:true});
  expect(calls).toHaveLength(1);
  const resources3D = await page.evaluate(() => performance.getEntriesByType('resource').map(entry=>entry.name));
  if (process.env.BUILDING_3D_FPS === '1') {
    const { measureBuildingPerformance } = await import('./building-performance');
    await measureBuildingPerformance(page, info);
  }
  await page.locator('.map-candidate-list').getByRole('button',{name:/d · 4층$/}).click();
  await expect(page.getByTestId('building-3d')).toHaveAttribute('data-state','ready');
  expect(calls).toHaveLength(1);
  await page.getByRole('button',{name:'2D',exact:true}).click();
  await expect.poll(async () => (await camera()).pitch).toBe(0);
  const after = await camera(); expect(after.zoom).toBeCloseTo(before.zoom,7);
  expect(after.center[0]).toBeCloseTo(before.center[0],7); expect(after.center[1]).toBeCloseTo(before.center[1],7);
  expect(await page.evaluate(() => !!(Reflect.get(window,'__gilmokProofMap') as LibreMap).getLayer('scored-buildings-3d'))).toBe(false);
  for (let toggle=0;toggle<5;toggle++) {
    await page.getByRole('button',{name:'3D',exact:true}).click();
    await page.getByRole('button',{name:'2D',exact:true}).click();
  }
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('tab',{name:'지도',exact:true}).click();
  await page.getByRole('button',{name:'3D',exact:true}).click();
  await expect(page.getByTestId('building-3d')).toHaveAttribute('data-state','ready');
  expect(calls).toHaveLength(1);
  await page.getByRole('button',{name:'2D',exact:true}).click();
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.setViewportSize({width:1440,height:1000});
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
  const totals = await page.locator('.desktop-matrix [data-total]').evaluateAll(nodes=>nodes.map(node=>(node as HTMLElement).dataset.total));
  await page.locator('.map-candidate-list').getByRole('button',{name:/c · 3층$/}).click();
  await page.route('**/rest/v1/rpc/project_exposure_geometry',route=>route.fulfill({status:503,contentType:'application/json',body:'{"message":"projection test failure"}'}));
  await page.getByRole('button',{name:'3D',exact:true}).click();
  await expect(page.getByTestId('building-3d')).toHaveAttribute('data-state','error');
  expect(await page.locator('.desktop-matrix [data-total]').evaluateAll(nodes=>nodes.map(node=>(node as HTMLElement).dataset.total))).toEqual(totals);
  await page.getByRole('button',{name:'2D로 돌아가기',exact:true}).click();
  await page.unroute('**/rest/v1/rpc/project_exposure_geometry');
  await page.getByRole('button',{name:'3D',exact:true}).click();
  await expect(page.getByTestId('building-3d')).toHaveAttribute('data-state','ready');
  await expect(page.getByTestId('building-3d')).toHaveAttribute('data-building-count','3843');
  await page.locator('.map-candidate-list').getByRole('button',{name:/a · 3층$/}).click();
  await expect(page.getByTestId('building-3d')).toHaveAttribute('data-state','ready');
  await page.getByRole('button',{name:'2D',exact:true}).click();
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
  expect(scoringCalls).toEqual([]);
  expect(await page.locator('html').getAttribute('data-exposure-runs')).toBe(workersBefore);
  await expect.poll(()=>http.length).toBe(3);
  expect(http.map(value=>value.status)).toEqual([200,503,200]);
  return {...proof,first3DReadyMs,projectionRequests:calls.length,http,resourcesBefore,resources3D:resources3D.filter(url=>!resourcesBefore.includes(url)),
    restore2D:true,mobileBuildings:true,sameFloorGeometryReused:true,rapidToggles:10,noAdditionalScoring:true,projectionFailureIsolated:true};
}
