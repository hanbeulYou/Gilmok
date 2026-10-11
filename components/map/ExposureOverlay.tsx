'use client';
import {useEffect,useMemo,useRef,useState} from 'react';
import type {Map as LibreMap} from 'maplibre-gl';
import {MapboxOverlay} from '@deck.gl/mapbox';
import {ScatterplotLayer,PathLayer,LineLayer} from '@deck.gl/layers';
import type {PickingInfo} from '@deck.gl/core';
import type {ComparisonCandidate} from '../../lib/compare/store';
import type {GeometryItem} from '../../lib/map/buildings';
import {exposureGeometryItems,exposureGeometry,sampleLabel,type ExposureGeometry,type DisplaySample} from '../../lib/map/exposure';
import {getSupabaseClient} from '../../lib/supabase/client';
import {projectGeometry} from '../../lib/map/project';
import {useExposureLink} from '../compare/ExposureLink';
import {ExposureEvidence} from '../compare/ExposureEvidence';
import './exposure-overlay.css';
const source='scored-buildings';
export default function ExposureOverlay({map,row,active}:{map:LibreMap;row?:ComparisonCandidate;active:boolean}) {
 const link=useExposureLink(),scene=row?.inputs?.scene,samples=row?.inputs?.exposure?.samples;
 const [data,setData]=useState<ExposureGeometry|null>(null),[error,setError]=useState(''),[attempt,retry]=useState(0),[hover,setHover]=useState<string|null>(null);
 const cache=useRef(new Map<string,GeometryItem[]>()),control=useRef<MapboxOverlay|null>(null);
 useEffect(()=>{const store=cache.current;let owner:string|null|undefined;const {data:auth}=getSupabaseClient().auth.onAuthStateChange((_e,s)=>{if(owner!==undefined&&owner!==s?.user.id){store.clear();setData(null)}owner=s?.user.id??null});return()=>{store.clear();auth.subscription.unsubscribe()};},[]);
 useEffect(()=>{
  setData(null);setError('');setHover(null);
  if(!active||!scene||!samples?.some(s=>s.group==='ring'))return;
  const controller=new AbortController();let alive=true;const timer=setTimeout(()=>controller.abort(),15000);
  const items=exposureGeometryItems(samples),key=JSON.stringify([row?.id,row?.generation,scene.floor,scene.sources,items]);
  void(async()=>{let projected=cache.current.get(key);if(!projected){projected=await projectGeometry(items,controller.signal);}
   controller.signal.throwIfAborted();const geometry=exposureGeometry(scene,samples,projected);if(!alive)return;cache.current.delete(key);cache.current.set(key,projected);if(cache.current.size>2)cache.current.delete(cache.current.keys().next().value!);setData(geometry);
  })().catch(e=>{if(alive)setError(e?.name==='AbortError'?'노출 표시 요청 시간이 초과되었습니다.':e instanceof Error?e.message:'노출 표시 실패');}).finally(()=>clearTimeout(timer));
  return()=>{alive=false;clearTimeout(timer);controller.abort()};
 },[active,scene,samples,row?.id,row?.generation,attempt]);
 useEffect(()=>{setHover(null);},[link.sampleId]);
 useEffect(()=>{const clear=()=>setHover(null);map.on('mouseout',clear);return()=>{map.off('mouseout',clear)};},[map]);
 const selected=data?.samples.find(s=>s.sample.id===link.sampleId),emphasis=data?.samples.find(s=>s.sample.id===(hover??link.sampleId));
 useEffect(()=>{
  const id=emphasis?.sample.status==='blocked'?emphasis.sample.building_id:null;
  if(!active||!id)return;
  const apply=()=>{if(map.getSource(source)){map.setFeatureState({source,id},{'exposure-blocker':true});map.off('idle',apply);}};
  if(map.getSource(source))apply();else map.on('idle',apply);
  return()=>{map.off('idle',apply);if(map.getSource(source))map.removeFeatureState({source,id},'exposure-blocker')};
 },[active,emphasis,map]);
 const layers=useMemo(()=>{
  if(!active||!data)return [];
  const color=(d:DisplaySample):[number,number,number,number]=>d.sample.status==='visible'?[48,220,110,255]:d.sample.status==='blocked'?[140,30,45,255]:[140,140,140,255];
  return [new PathLayer({id:'exposure-rings',data:data.rings,getPath:d=>d.path,getColor:[70,100,180,150],getWidth:1,widthUnits:'pixels',pickable:false}),
   new LineLayer({id:'exposure-moved',data:data.samples.filter(d=>d.sample.moved_m>0&&d.sample.status!=='excluded'),getSourcePosition:d=>d.original,getTargetPosition:d=>d.point,getColor:[245,190,40,230],getWidth:1.5,pickable:false}),
   new ScatterplotLayer<DisplaySample>({id:'exposure-samples',data:data.samples,getPosition:d=>d.sample.status==='excluded'?d.original:d.point,getRadius:d=>d.sample.id===link.sampleId?1.5:1,radiusMinPixels:4,radiusMaxPixels:10,getFillColor:color,stroked:true,getLineColor:d=>d.sample.id===link.sampleId?[255,255,255,255]:d.sample.moved_m>0?[245,190,40,255]:[0,0,0,0],getLineWidth:2,lineWidthUnits:'pixels',pickable:true,onClick:(i:PickingInfo<DisplaySample>)=>{if(i.object){link.pick(i.object.sample.id,'map');return true;}return false;},onHover:(i:PickingInfo<DisplaySample>)=>setHover(i.object?.sample.id??null),updateTriggers:{getRadius:[link.sampleId],getLineColor:[link.sampleId]}}),
   new LineLayer({id:'exposure-sightline',data:selected?.target&&selected.sample.status!=='excluded'?[selected]:[],getSourcePosition:d=>d.point,getTargetPosition:d=>d.target!,getColor:[255,220,80,255],getWidth:2,pickable:false}),
   new ScatterplotLayer({id:'exposure-target',data:selected?.target&&selected.sample.status!=='excluded'?[selected]:[],getPosition:d=>d.target!,getRadius:.7,radiusMinPixels:4,getFillColor:[255,220,80,255],pickable:false})];
 },[active,data,selected,link]);
 useEffect(()=>{if(!active||!data)return;const overlay=new MapboxOverlay({interleaved:true,layers:[]});map.addControl(overlay);control.current=overlay;return()=>{control.current=null;map.removeControl(overlay)};},[active,Boolean(data),map]);
 useEffect(()=>{control.current?.setProps({layers,getTooltip:({object}:PickingInfo<DisplaySample>)=>object?.sample?`${sampleLabel(object.sample)} · 이동 ${object.sample.moved_m.toFixed(3)}m`:null});},[layers]);
 if(!active)return null;
 return <section className="exposure-overlay" data-testid="exposure-overlay" data-state={error?'error':data?'ready':samples?.length?'loading':'missing'} data-sample-count={data?.samples.length??0} data-selected-sample={link.sampleId??''} aria-label="노출 샘플 지도">
  <p>초록 가시 · 빨강 차폐 · 회색 제외 · 노랑 테두리 이동 · 분홍 선택 차폐 건물</p>
  {error?<p role="alert">{error} <button onClick={()=>retry(v=>v+1)}>오버레이 다시 시도</button></p>:!data&&samples?.length?<p role="status">노출 표시 좌표를 준비하는 중입니다.</p>:null}
  {row&&<ExposureEvidence row={row} interactive={false}/>}
 </section>;
}
