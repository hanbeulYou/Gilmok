'use client';
import {createContext,useContext,useState,useRef,useMemo,useCallback,type ReactNode} from 'react';
import type {ComparisonCandidate} from '../../lib/compare/store';
interface LinkState { enabled:boolean; sampleId:string|null; desktop:boolean; setEnabled:(on:boolean)=>void; pick:(id:string,from:'map'|'evidence')=>void }
const Context=createContext<LinkState>({enabled:false,sampleId:null,desktop:false,setEnabled:()=>{},pick:()=>{}});
export const useExposureLink=()=>useContext(Context);
/** Ephemeral UI selection, never serialized with candidates, scores or weight presets. */
export function ExposureLinkProvider({row,desktop,openEvidence,children}:{row?:ComparisonCandidate;desktop:boolean;openEvidence:()=>void;children:ReactNode}) {
  const owner=row?.inputs?.exposure, key=`${row?.id}:${row?.generation}:${row?.candidate.floor}`;
  const [state,setState]=useState({owner,key,enabled:false,sampleId:null as string|null});
  const openRef=useRef(openEvidence);openRef.current=openEvidence;
  const valid=state.key===key && state.owner===owner;
  const setEnabled=useCallback((enabled:boolean)=>setState(previous=>({owner,key,enabled,sampleId:previous.key===key&&previous.owner===owner?previous.sampleId:null})),[owner,key]);
  const pick=useCallback((sampleId:string,from:'map'|'evidence')=>{
    if (!owner?.samples?.some(s=>s.group==='ring' && s.id===sampleId)) return;
    setState({owner,key,enabled:desktop,sampleId});
    if (from==='map') openRef.current();
    else requestAnimationFrame(()=>{const el=document.querySelector<HTMLButtonElement>('[data-overlay-toggle]');el?.scrollIntoView({block:'nearest'});el?.focus();});
  },[owner,key,desktop]);
  const enabled=state.enabled&&desktop,sampleId=valid?state.sampleId:null;
  const value=useMemo(()=>({enabled,sampleId,desktop,setEnabled,pick}),[enabled,sampleId,desktop,setEnabled,pick]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
