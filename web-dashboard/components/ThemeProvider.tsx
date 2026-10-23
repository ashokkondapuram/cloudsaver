'use client';

import {createContext,useContext,useLayoutEffect,useState,type ReactNode} from 'react';
import {Moon,Sun} from 'lucide-react';

type Theme='dark'|'light';
const ThemeContext=createContext<{theme:Theme;toggle:()=>void}|null>(null);

export function ThemeProvider({children}:{children:ReactNode}){
  const [theme,setTheme]=useState<Theme>('dark');
  useLayoutEffect(()=>{
    try{const saved=localStorage.getItem('cloudsaver:ui:theme');if(saved==='light'||saved==='dark'){setTheme(saved);document.documentElement.dataset.theme=saved;}}catch{}
  },[]);
  function toggle(){
    const next=theme==='dark'?'light':'dark';setTheme(next);document.documentElement.dataset.theme=next;
    try{localStorage.setItem('cloudsaver:ui:theme',next);}catch{}
  }
  return <ThemeContext.Provider value={{theme,toggle}}>{children}</ThemeContext.Provider>;
}

export function ThemeToggle(){
  const context=useContext(ThemeContext);
  if(!context)return null;
  const label=`Switch to ${context.theme==='dark'?'light':'dark'} theme`;
  return <button className="icon-button theme-toggle" aria-label={label} title={label} onClick={context.toggle}>{context.theme==='dark'?<Sun size={18}/>:<Moon size={18}/>}</button>;
}
