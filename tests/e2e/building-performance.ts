import { writeFile } from 'node:fs/promises';
import { expect, type Page, type TestInfo } from '@playwright/test';
import type { Map as LibreMap } from 'maplibre-gl';

export async function measureBuildingPerformance(page: Page, info: TestInfo) {
  const device = await page.evaluate(() => {
    const map = Reflect.get(window,'__gilmokProofMap') as LibreMap;
    const gl = map.getCanvas().getContext('webgl2')!, debug = gl.getExtension('WEBGL_debug_renderer_info');
    return { renderer:debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : 'unavailable',
      userAgent:navigator.userAgent, dpr:devicePixelRatio, viewport:[innerWidth,innerHeight],
      canvas:[map.getCanvas().clientWidth,map.getCanvas().clientHeight,map.getCanvas().width,map.getCanvas().height] };
  });
  expect(device.renderer).toMatch(/Apple M5 Pro/);
  expect(device.renderer).not.toMatch(/SwiftShader|llvmpipe|Software/i);
  expect(device.dpr).toBe(2);
  const results = [];
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Tracing.start', { categories:'disabled-by-default-devtools.timeline.frame,cc,gpu,viz', transferMode:'ReturnAsStream' });
  try {
  for (const zoom of [17,14.5]) {
    for (let run=1;run<=3;run++) {
      await page.bringToFront();
      await page.evaluate(zoom => (Reflect.get(window,'__gilmokProofMap') as LibreMap)
        .jumpTo({center:[127.05758573871447,37.5025721944737],zoom,pitch:55,bearing:0}),zoom);
      await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
      const result = await page.evaluate(async ({zoom,run}) => {
        const map = Reflect.get(window,'__gilmokProofMap') as LibreMap;
        const visible = () => new Set(map.queryRenderedFeatures({layers:['scored-buildings-3d']}).map(f=>f.id)).size;
        const visibleStart = visible(), frames:number[]=[], raf:number[]=[];
        const focusedStart=document.hasFocus() && document.visibilityState==='visible';
        let last=0,rafLast=0; let rafId: number;
        const render = () => {const now=performance.now();if(last) frames.push(now-last);last=now;};
        const tick = (now:number) => {if(rafLast) raf.push(now-rafLast);rafLast=now;rafId=requestAnimationFrame(tick);};
        map.on('render',render); rafId=requestAnimationFrame(tick);
        const start=performance.now();
        // Continuous rendered camera motion, not an idle rAF count.
        map.easeTo({center:[127.059,37.5032],bearing:120,zoom:zoom+0.2,pitch:55,duration:60000,easing:t=>t,essential:true});
        await new Promise<void>(resolve=>setTimeout(resolve,60000));
        const duration=performance.now()-start;
        map.off('render',render);cancelAnimationFrame(rafId);map.stop();
        const sorted=[...frames].sort((a,b)=>a-b), averageFps=frames.length/(duration/1000);
        const p95=sorted[Math.ceil(sorted.length*0.95)-1], over50=frames.filter(ms=>ms>50).length/frames.length;
        return {zoom,run,duration,renderedFrames:frames.length,averageFps,p95,max:sorted.at(-1),over50,
          visibleStart,visibleEnd:visible(),frames,raf,focusedStart,focusedEnd:document.hasFocus(),
          passed:focusedStart && document.hasFocus() && averageFps>=55 && p95<=33.4 && over50<=0.01};
      }, {zoom,run});
      await info.attach(`building-fps-${zoom}-${run}`,{body:JSON.stringify({device,...result}),contentType:'application/json'});
      console.log('building-fps',JSON.stringify({...result,frames:undefined,raf:undefined,device}));
      results.push(result);
    }
  }
  } finally {
    const completed = new Promise<string>(resolve => cdp.once('Tracing.tracingComplete', event => resolve(event.stream!)));
    await cdp.send('Tracing.end');
    const stream = await completed, chunks: Buffer[] = [];
    for (;;) {
      const part = await cdp.send('IO.read',{handle:stream});
      chunks.push(Buffer.from(part.data,part.base64Encoded ? 'base64' : 'utf8'));
      if (part.eof) break;
    }
    await cdp.send('IO.close',{handle:stream}); await cdp.detach();
    const path = info.outputPath('building-frame-trace.json');
    await writeFile(path,Buffer.concat(chunks));
    await info.attach('building-frame-trace',{path,contentType:'application/json'});
  }
  expect(results.every(result=>result.passed),'Every near/wide 60-second run must meet D5').toBe(true);
  return results;
}
