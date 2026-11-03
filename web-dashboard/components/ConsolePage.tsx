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
import {isLiveSnapshot} from '../lib/resources';

export type View = 'overview'|'resources'|'allocation'|'automation'|'activity'|'settings';
const headings:Record<View,string>={
  overview:'Overview', resources:'Resources', allocation:'Cost allocation',
  automation:'Automation & GitOps', activity:'Activity & delivery', settings:'Settings',
};

function DiscoverResources({provider='',category='',intent='',pricing=''}:{provider?:string;category?:Category|'';intent?:Intent;pricing?:Pricing}) {
  const {scan} = useWorkspace();
  const live = isLiveSnapshot(scan);
  return <>
    {live ? <ResourcesView initialProvider={provider} initialCategory={category} initialIntent={intent} initialPricing={pricing}/>
      : <FindingsGrid initialProvider={provider} initialCategory={category} initialIntent={intent} initialPricing={pricing} navigateToResource/>}
  </>;
}

export function ConsolePage({view,provider='',category='',intent='',pricing=''}:{view:View;provider?:string;category?:Category|'';intent?:Intent;pricing?:Pricing}) {
  const {workspace,scan,canAdmin,busy,setOverlay,refresh,notify} = useWorkspace();
  const heading=headings[view];
  function exportSnapshot(format:'json'|'csv') {
    if(!scan)return;
    if(format==='json')downloadFile(JSON.stringify(scan,null,2),`cloudsaver-${scan.scan_id}.json`,'application/json');
    else exportFindings(scan.findings,'csv',`cloudsaver-${scan.scan_id}`);
    notify(`${format.toUpperCase()} download is ready.`);
  }
  return <><div className="page-heading">{view!=='overview'&&<h1>{heading}</h1>}<div className="page-heading-actions">{view==='resources'&&<Link className="button secondary" href="/workloads"><Layers size={15}/>Workload assessments</Link>}{['overview','resources','allocation'].includes(view)&&<><button className="icon-button refresh-workspace" aria-label="Refresh workspace" disabled={!!busy} onClick={refresh}><RefreshCw size={17}/></button>{view!=='overview'&&<details className="export-menu"><summary className={`button secondary ${!scan?'unavailable':''}`} aria-disabled={!scan}><Download size={15}/><span>Export snapshot</span><ChevronDown size={13}/></summary><div className="menu-surface"><span className="menu-label">COMPLETE SELECTED SNAPSHOT</span><button disabled={!scan} onClick={()=>exportSnapshot('csv')}>Export CSV</button><button disabled={!scan} onClick={()=>exportSnapshot('json')}>Export JSON</button></div></details>}{canAdmin&&(view!=='overview'||!!scan)&&<button className="button primary" disabled={!!busy} onClick={()=>setOverlay('scan')}><Plus size={17}/>Run new scan</button>}</>}</div></div>
    {view==='overview'?<Overview/>:view==='resources'?<DiscoverResources key={`${workspace?.tenant_id}-${scan?.scan_id||'empty'}`} provider={provider} category={category} intent={intent} pricing={pricing}/>:view==='allocation'?<Allocation/>:view==='automation'?<Automation/>:view==='activity'?<ActivityView/>:<SettingsView/>}
  </>;
}
