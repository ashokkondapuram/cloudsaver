'use client';

import Link from 'next/link';
import {Download, Layers, Plus, RefreshCw, ChevronDown} from 'lucide-react';
import {downloadFile, exportFindings} from '../lib/finops';
import {useWorkspace} from './WorkspaceProvider';
import {Overview} from './Overview';
import type {Category,Intent,Pricing} from '../lib/resource-insights';
import {FindingsGrid} from './datagrid/FindingsGrid';
import {ActivityView, Allocation, Automation, SettingsView} from './WorkspaceViews';
import {ResourcesView} from './resources/ResourcesView';

export type View = 'overview'|'findings'|'resources'|'allocation'|'automation'|'activity'|'settings';
const headings:Record<View,{eyebrow:string;title:string;description:string}>={
  overview:{eyebrow:'DISCOVER & ANALYZE',title:'Overview',description:'See what’s connected, what was analyzed and what needs your attention.'},
  findings:{eyebrow:'DISCOVER & ANALYZE',title:'Inventory & findings',description:'Search and filter every resource signal across your clouds, accounts and scopes.'},
  resources:{eyebrow:'DISCOVER & ANALYZE',title:'Resource analysis',description:'Review one five-pillar assessment per resource, with AI suggestions and your team’s decisions.'},
  allocation:{eyebrow:'MODEL & ATTRIBUTE',title:'Cost allocation',description:'See billed costs, pricing coverage and ownership evidence by account and scope.'},
  automation:{eyebrow:'ACT & GOVERN',title:'Automation & GitOps',description:'Prepare reviewed code changes, check plans against guardrails and track execution.'},
  activity:{eyebrow:'ACT & GOVERN',title:'Activity & delivery',description:'Inspect delivery status, saved scans and AI assessments.'},
  settings:{eyebrow:'REPORT & ADMINISTER',title:'Settings',description:'Manage cloud scopes, access, analysis rules and your plan.'},
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
  return <><div className="page-heading"><div><div className="eyebrow">{heading.eyebrow}</div><h1>{heading.title}</h1><p>{heading.description}</p></div><div className="page-heading-actions">{view==='resources'&&<Link className="button secondary" href="/workloads"><Layers size={15}/>Workload assessments</Link>}{['overview','findings','allocation'].includes(view)&&<><button className="icon-button refresh-workspace" aria-label="Refresh workspace" disabled={!!busy} onClick={refresh}><RefreshCw size={17}/></button><details className="export-menu"><summary className={`button secondary ${!scan?'unavailable':''}`} aria-disabled={!scan}><Download size={15}/><span>Export snapshot</span><ChevronDown size={13}/></summary><div className="menu-surface"><span className="menu-label">COMPLETE SELECTED SNAPSHOT</span><button disabled={!scan} onClick={()=>exportSnapshot('csv')}>Export CSV</button><button disabled={!scan} onClick={()=>exportSnapshot('json')}>Export JSON</button></div></details>{canAdmin&&<button className="button primary" disabled={!!busy} onClick={()=>setOverlay('scan')}><Plus size={17}/>Run new scan</button>}</>}</div></div>
    {view==='overview'?<Overview/>:view==='findings'?<FindingsGrid key={`${workspace?.tenant_id}-${scan?.scan_id||'empty'}`} initialProvider={provider} initialCategory={category} initialIntent={intent} initialPricing={pricing}/>:view==='resources'?<ResourcesView/>:view==='allocation'?<Allocation/>:view==='automation'?<Automation/>:view==='activity'?<ActivityView/>:<SettingsView/>}
  </>;
}
