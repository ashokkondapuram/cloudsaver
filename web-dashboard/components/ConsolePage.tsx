'use client';

import {Download, Plus, RefreshCw, ChevronDown} from 'lucide-react';
import {downloadFile, exportFindings} from '../lib/finops';
import {useWorkspace} from './WorkspaceProvider';
import {Overview} from './Overview';
import type {Category,Intent,Pricing} from '../lib/resource-insights';
import {SettingsView} from './WorkspaceViews';
import {ResourcesView} from './resources/ResourcesView';

export type View = 'overview'|'resources'|'settings';
const headings:Record<View,{eyebrow:string;title:string;description:string}>={
  overview:{eyebrow:'WORKSPACE INTELLIGENCE',title:'Your cloud, in focus.',description:'Understand the signals. Prioritize the right resources. Review with confidence.'},
  resources:{eyebrow:'RESOURCE ANALYSIS',title:'One assessment per resource.',description:'Review merged five-pillar evidence, AI suggestions and your team’s decisions for each resource.'},
  settings:{eyebrow:'SETTINGS & INTEGRATIONS',title:'Your workspace, connected.',description:'Review cloud sources, approved integrations, plan limits, and access.'},
};

export function ConsolePage({view,provider='',category='',intent='',pricing=''}:{view:View;provider?:string;category?:Category|'';intent?:Intent;pricing?:Pricing}) {
  const {workspace,scan,canAdmin,busy,setOverlay,refresh,notify} = useWorkspace();
  const heading=headings[view];
  function exportSnapshot(format:'json'|'csv') {
    if(!scan)return;
    if(format==='json')downloadFile(JSON.stringify(scan,null,2),`cloudsaver-${scan.scan_id}.json`,'application/json');
    else exportFindings(scan.findings,'csv',`cloudsaver-${scan.scan_id}`);
    notify(`${format.toUpperCase()} snapshot download prepared.`);
  }
  return <><div className="page-heading"><div><div className="eyebrow">{heading.eyebrow}</div><h1>{heading.title}</h1><p>{heading.description}</p></div><div className="page-heading-actions">{view==='overview'&&<><button className="icon-button refresh-workspace" aria-label="Refresh workspace" disabled={!!busy} onClick={refresh}><RefreshCw size={17}/></button><details className="export-menu"><summary className={`button secondary ${!scan?'unavailable':''}`} aria-disabled={!scan}><Download size={15}/><span>Export snapshot</span><ChevronDown size={13}/></summary><div className="menu-surface"><span className="menu-label">COMPLETE SELECTED SNAPSHOT</span><button disabled={!scan} onClick={()=>exportSnapshot('csv')}>Export CSV</button><button disabled={!scan} onClick={()=>exportSnapshot('json')}>Export JSON</button></div></details>{canAdmin&&<button className="button primary" disabled={!!busy} onClick={()=>setOverlay('scan')}><Plus size={17}/>Run new scan</button>}</>}</div></div>
    {view==='overview'?<Overview/>:view==='resources'?<ResourcesView/>:<SettingsView/>}
  </>;
}
