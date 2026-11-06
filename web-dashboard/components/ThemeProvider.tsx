'use client';

import {createContext,useContext,useLayoutEffect,useState,type ReactNode} from 'react';
import {Moon,Sun} from '@phosphor-icons/react';
import {getThemeMeta,normalizeUiThemePreset,type UiThemePreset} from '../lib/ui-theme';

type Theme='dark'|'light';
const ThemeContext=createContext<{theme:Theme;toggle:()=>void;appearanceLocked:boolean;preset:UiThemePreset}|null>(null);

export function ThemeProvider({children}:{children:ReactNode}){
  const [theme,setTheme]=useState<Theme>('dark');
  const [preset,setPreset]=useState<UiThemePreset>('atlas');
  useLayoutEffect(()=>{
    const root=document.documentElement;
    const syncPreset=()=>setPreset(normalizeUiThemePreset(root.dataset.uiPreset));
    syncPreset();
    const observer=new MutationObserver(syncPreset);
    observer.observe(root,{attributes:true,attributeFilter:['data-ui-preset']});
    return ()=>observer.disconnect();
  },[]);
  useLayoutEffect(()=>{
    try{
      const meta=getThemeMeta(preset);
      if(meta.appearanceLock){
        setTheme(meta.appearanceLock);
        document.documentElement.dataset.theme=meta.appearanceLock;
        return;
      }
      const saved=localStorage.getItem('cloudsaver:ui:theme');
      if(saved==='light'||saved==='dark'){setTheme(saved);document.documentElement.dataset.theme=saved;}
    }catch{}
  },[preset]);
  const appearanceLocked=getThemeMeta(preset).appearanceLock!=null;
  function toggle(){
    if(appearanceLocked)return;
    const next=theme==='dark'?'light':'dark';setTheme(next);document.documentElement.dataset.theme=next;
    try{localStorage.setItem('cloudsaver:ui:theme',next);}catch{}
  }
  return <ThemeContext.Provider value={{theme,toggle,appearanceLocked,preset}}>{children}</ThemeContext.Provider>;
}

export function useUiThemePreset(){
  const context=useContext(ThemeContext);
  return context?.preset ?? 'console';
}

export function ThemeToggle(){
  const context=useContext(ThemeContext);
  if(!context||context.appearanceLocked)return null;
  const label=`Switch to ${context.theme==='dark'?'light':'dark'} theme`;
  return <button type="button" className="icon-button theme-toggle" aria-label={label} title={label} onClick={context.toggle}>{context.theme==='dark'?<Sun size={18} weight="regular"/>:<Moon size={18} weight="regular"/>}</button>;
}
