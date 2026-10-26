'use client';

import {useCallback, useEffect, useRef, useState, type DependencyList, type SetStateAction} from 'react';
import {errorMessage} from './api';

export function useLoad<T>(load: () => Promise<T>, deps: DependencyList) {
  const run=useCallback(load,deps);
  const active=useRef(run);active.current=run;
  const generation=useRef(0);
  const [state,setState]=useState<{run:(()=>Promise<T>)|null;generation:number;data:T|null;error:string;loading:boolean}>({run:null,generation:0,data:null,error:'',loading:true});
  const reload=useCallback(async()=>{
    const version=++generation.current;
    setState({run,generation:version,data:null,error:'',loading:true});
    try{
      const data=await run();
      if(active.current===run&&generation.current===version)setState({run,generation:version,data,error:'',loading:false});
    }catch(cause){
      if(active.current===run&&generation.current===version)setState({run,generation:version,data:null,error:errorMessage(cause),loading:false});
    }
  },[run]);
  useEffect(()=>{void reload();return()=>{generation.current++;};},[reload]);
  // Pagination and mutations close over this setter. Reject their late writes
  // after a filter, customer, refresh generation or unmount has changed.
  const setData=useCallback((value:SetStateAction<T|null>)=>{
    if(active.current!==run||generation.current!==state.generation)return;
    setState(current=>current.run===run&&current.generation===state.generation?{...current,data:typeof value==='function'?(value as (previous:T|null)=>T|null)(current.data):value}:current);
  },[run,state.generation]);
  const current=state.run===run;
  return {data:current?state.data:null,setData,error:current?state.error:'',loading:current?state.loading:true,reload};
}
