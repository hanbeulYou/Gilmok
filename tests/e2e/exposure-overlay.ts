import {expect,type Page,type TestInfo} from '@playwright/test';
import {measureSliderSet,summarizeSliderSets,sliderPolicy} from './slider-performance';
export async function checkExposureOverlay(page:Page,info:TestInfo,before:string[]) {
 await expect(page.locator('[data-overlay-toggle]')).toHaveAttribute('aria-pressed','true');
 await expect(page.getByTestId('exposure-overlay')).toHaveAttribute('data-state','ready');
 await expect(page.getByTestId('exposure-overlay')).toHaveAttribute('data-sample-count','108');
 await expect(page.getByTestId('exposure-overlay')).toContainText('32/108');await expect(page.getByTestId('exposure-overlay')).toContainText('38.383838%');await expect(page.getByTestId('exposure-overlay')).toContainText('30.707071점');
 await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
 const proof=await page.evaluate(()=>{
  const map=Reflect.get(window,'__gilmokProofMap'),deck=map._controls.find((c:Record<string,unknown>)=>c._deck)?._deck;
  if(!deck)throw new Error('No interleaved deck control');const layers=deck.props.layers,layer=layers.find((l:{id:string})=>l.id==='exposure-samples');const data=layer.props.data;
  return {samples:data.map((d:{sample:Record<string,unknown>;point:number[];original:number[];target:number[]|null})=>({sample:d.sample,point:d.point,original:d.original,target:d.target})),rings:layers.find((l:{id:string})=>l.id==='exposure-rings').props.data,sharedCanvas:deck.getCanvas()===map.getCanvas(),layers:layers.map((l:{id:string})=>l.id)};
 });
 const recorded=await page.evaluate(()=>Reflect.get(window,'__workerExposureResults').findLast((r:{evidence:{values:{floor:number;candidate_wgs84:{lat:number}}}})=>r.evidence.values.floor===3&&Math.abs(r.evidence.values.candidate_wgs84.lat-37.5025721944737)<1e-8));
 expect(proof.samples.map((s:{sample:unknown})=>s.sample)).toEqual(recorded.samples.filter((s:{group:string})=>s.group==='ring'));
 expect(proof.sharedCanvas).toBe(true);expect(proof.samples).toHaveLength(108);
 expect([20,40,60].map(r=>proof.samples.filter((s:{sample:Record<string,unknown>})=>s.sample.radius_m===r&&s.sample.status==='visible').length)).toEqual([20,8,4]);
 for(const s of proof.samples){expect(s.point[2]).toBe(1.5);if(s.target)expect(s.target[2]).toBe(8.6);expect(s.sample.weight).toBe(100/Number(s.sample.radius_m));}
 const pick=await page.evaluate(()=>{
  const m=Reflect.get(window,'__gilmokProofMap'),deck=m._controls.find((c:Record<string,unknown>)=>c._deck)._deck,viewport=deck.getViewports()[0],data=deck.props.layers.find((l:{id:string})=>l.id==='exposure-samples').props.data;
  for(const d of data){const p=viewport.project(d.sample.status==='excluded'?d.original:d.point);if(p[0]<10||p[1]<10||p[0]>m.getCanvas().clientWidth-10||p[1]>m.getCanvas().clientHeight-10)continue;const picked=deck.pickObject({x:p[0],y:p[1],radius:2,layerIds:['exposure-samples']});if(picked?.object?.sample.id===d.sample.id){const b=m.getCanvas().getBoundingClientRect();return {x:b.x+p[0],y:b.y+p[1],id:d.sample.id};}}return null;
 });
 expect(pick).not.toBeNull();await page.mouse.click(pick!.x,pick!.y);
 const evidence=page.getByRole('region',{name:'근거 패널'});await expect(evidence).toBeVisible();await expect(evidence.getByTestId('exposure-selected-sample')).toHaveAttribute('data-sample-id',pick!.id);
 const blocked=proof.samples.find((s:{sample:Record<string,unknown>})=>s.sample.status==='blocked')!.sample;
 await evidence.locator('.sample-evidence-list > summary').click();await evidence.locator('.sample-evidence-list details > summary').filter({hasText:`${blocked.radius_m}m 링`}).click();
 await evidence.locator(`[data-sample-evidence="${blocked.id}"]`).click();await expect(page.getByTestId('exposure-overlay')).toHaveAttribute('data-selected-sample',String(blocked.id));
 await expect.poll(()=>page.evaluate(id=>Reflect.get(window,'__gilmokProofMap').getFeatureState({source:'scored-buildings',id})['exposure-blocker'],String(blocked.building_id))).toBe(true);
 await page.locator('.map-panel').screenshot({path:info.outputPath('exposure-overlay.png')});
 await page.evaluate(()=>Reflect.get(window,'__gilmokProofMap').jumpTo({pitch:0,bearing:0}));await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
 await page.locator('.map-panel').screenshot({path:info.outputPath('exposure-overlay-top.png')});
 await page.evaluate(()=>Reflect.get(window,'__gilmokProofMap').jumpTo({pitch:55,bearing:0}));await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
 const depth=await page.evaluate(async()=>{
  const m=Reflect.get(window,'__gilmokProofMap'),overlay=m._controls.find((c:Record<string,unknown>)=>c._deck),deck=overlay._deck,old=deck.props.layers,sampleLayer=old.find((l:{id:string})=>l.id==='exposure-samples');
  m.jumpTo({pitch:0,bearing:0});await new Promise<void>(resolve=>{m.once('idle',()=>resolve());m.triggerRepaint();});
  const candidate=m.getSource('scored-buildings')._data.features.find((f:{properties:{candidate:boolean}})=>f.properties.candidate),height=candidate.properties.height_m;
  const read=async(z:number)=>{
   const position=[127.05758573871447,37.5025721944737,z];overlay.setProps({layers:[...old.filter((l:{id:string})=>l.id!=='exposure-target'),sampleLayer.clone({id:'exposure-target',data:[{position}],getPosition:(d:{position:number[]})=>d.position,getRadius:2,radiusMinPixels:8,getFillColor:[0,255,255,255],getLineColor:[0,0,0,0],stroked:false,pickable:false})]});await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));
   await new Promise<void>(resolve=>{m.once('idle',()=>resolve());m.triggerRepaint();});
   return await new Promise<number[]>(resolve=>{m.once('render',()=>{const canvas=m.getCanvas(),gl=canvas.getContext('webgl2'),pixel=new Uint8Array(4),p=deck.getViewports()[0].project(position),ratio=canvas.width/canvas.clientWidth;gl.readPixels(Math.floor(p[0]*ratio),canvas.height-1-Math.floor(p[1]*ratio),1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);resolve([...pixel]);});m.triggerRepaint();});
  };
  try{return {above:await read(height+3),inside:await read(1.5),height};}finally{overlay.setProps({layers:old});m.jumpTo({pitch:55,bearing:0});m.triggerRepaint();}
 });
 await info.attach('occlusion-probe',{body:JSON.stringify(depth),contentType:'application/json'});
 expect(depth.above[0]<40&&depth.above[1]>220&&depth.above[2]>220).toBe(true);
 expect(depth.inside[0]<40&&depth.inside[1]>220&&depth.inside[2]>220).toBe(false);
 await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
 await page.evaluate(()=>{const m=Reflect.get(window,'__gilmokProofMap');Reflect.set(window,'__overlayFrames',0);Reflect.set(window,'__overlayFrameListener',()=>Reflect.set(window,'__overlayFrames',Reflect.get(window,'__overlayFrames')+1));m.on('render',Reflect.get(window,'__overlayFrameListener'));Reflect.set(window,'__overlayMarkers',[...document.querySelectorAll('.map-candidate')]);});
 const sets:number[][]=[];for(let i=0;i<3;i++){const result=await page.evaluate(measureSliderSet);expect(result.scoresChanged&&result.restored).toBe(true);sets.push(result.times);}
 const runtime=await page.evaluate(()=>{const m=Reflect.get(window,'__gilmokProofMap');m.off('render',Reflect.get(window,'__overlayFrameListener'));return {mapFrames:Reflect.get(window,'__overlayFrames'),markersPreserved:Reflect.get(window,'__overlayMarkers').every((node:Element,i:number)=>document.querySelectorAll('.map-candidate')[i]===node)};});await info.attach('overlay-slider-runtime',{body:JSON.stringify(runtime),contentType:'application/json'});
 const slider=summarizeSliderSets(sets,sliderPolicy(process.env.SLIDER_PERFORMANCE_POLICY));await info.attach('overlay-slider-performance',{body:JSON.stringify(slider),contentType:'application/json'});expect(slider.passed).toBe(true);
 if(process.env.EXPOSURE_OVERLAY_FPS==='1'){const {measureBuildingPerformance}=await import('./building-performance');await measureBuildingPerformance(page,info);}
 await page.locator('[data-overlay-toggle]').click();await expect(page.getByTestId('exposure-overlay')).toHaveCount(0);
 expect(await page.evaluate(()=>Reflect.get(window,'__gilmokProofMap')._controls.some((c:Record<string,unknown>)=>c._deck))).toBe(false);
 // Classify the unique incremental resources after default-on 3D entry. These
 // diagnostic reads happen after the interaction benchmark, not during startup.
 const overlayResources=await page.evaluate(async before=>{
  const urls=[...new Set(performance.getEntriesByType('resource').map(r=>r.name).filter(u=>!before.includes(u)&&u.includes('/_next/static/')&&/\.(js|css)$/.test(u)))];
  const bodies=await Promise.all(urls.map(async url=>({url,text:await (await fetch(url)).text()})));
  return bodies.filter(({url,text})=>url.endsWith('.css')?text.includes('.exposure-overlay'):!text.includes('data-building-count')).map(r=>r.url);
 },before);
 const overlayJS=overlayResources.filter(u=>u.endsWith('.js'));
 await info.attach('exposure-overlay-proof',{body:JSON.stringify({...proof,depth,overlayJS,workerSampleDiff:0,picked:pick!.id,highlightedBlocker:blocked.building_id,twoWay:true}),contentType:'application/json'});
 return {overlayJS,overlayResources};
}

