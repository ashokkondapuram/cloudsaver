'use client';

import {Download, Plus, RefreshCw, ChevronDown} from 'lucide-react';
import {downloadFile, exportFindings} from '../lib/finops';
import {useWorkspace} from './WorkspaceProvider';
import {Overview} from './Overview';
import type {Category,Intent,Pricing} from '../lib/resource-insights';
import {FindingsGrid} from './datagrid/FindingsGrid';
import {ActivityView, Allocation, Automation, SettingsView} from './WorkspaceViews';

export type View = 'overview'|'findings'|'allocation'|'automation'|'activity'|'settings';
const headings:Record<View,{eyebrow:string;title:string;description:string}>={
  overview:{eyebrow:'WORKSPACE INTELLIGENCE',title:'Your cloud, in focus.',description:'Understand the signals. Prioritize the right resources. Review with confidence.'},
  findings:{eyebrow:'INVENTORY & FINDINGS',title:'Every resource. The full picture.',description:'Explore resource signals across your clouds, accounts, and scopes.'},
  allocation:{eyebrow:'COST ALLOCATION',title:'Know where the evidence leads.',description:'Explore cost coverage and resource ownership across your accounts.'},
  automation:{eyebrow:'AUTOMATION ENGINE',title:'From insight to reviewed code.',description:'Prepare change reviews and check infrastructure plans before they reach production.'},
  activity:{eyebrow:'WORKSPACE ACTIVITY',title:'A clear record of workspace activity.',description:'Inspect delivery state, saved scans, AI assessments and provider-reported usage.'},
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
  return <><div className="page-heading"><div><div className="eyebrow">{heading.eyebrow}</div><h1>{heading.title}</h1><p>{heading.description}</p></div><div className="page-heading-actions">{['overview','findings','allocation'].includes(view)&&<><button className="icon-button refresh-workspace" aria-label="Refresh workspace" disabled={!!busy} onClick={refresh}><RefreshCw size={17}/></button><details className="export-menu"><summary className={`button secondary ${!scan?'unavailable':''}`} aria-disabled={!scan}><Download size={15}/><span>Export snapshot</span><ChevronDown size={13}/></summary><div className="menu-surface"><span className="menu-label">COMPLETE SELECTED SNAPSHOT</span><button disabled={!scan} onClick={()=>exportSnapshot('csv')}>Export CSV</button><button disabled={!scan} onClick={()=>exportSnapshot('json')}>Export JSON</button></div></details>{canAdmin&&<button className="button primary" disabled={!!busy} onClick={()=>setOverlay('scan')}><Plus size={17}/>Run new scan</button>}</>}</div></div>
    {view==='overview'?<Overview/>:view==='findings'?<FindingsGrid key={`${workspace?.tenant_id}-${scan?.scan_id||'empty'}`} initialProvider={provider} initialCategory={category} initialIntent={intent} initialPricing={pricing}/>:view==='allocation'?<Allocation/>:view==='automation'?<Automation/>:view==='activity'?<ActivityView/>:<SettingsView/>}
  </>;
}
