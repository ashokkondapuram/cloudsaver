'use client';

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

function DiscoverResources({provider='',category='',intent='',pricing='',armDetail=''}:{provider?:string;category?:Category|'';intent?:Intent;pricing?:Pricing;armDetail?:import('../lib/resources').ArmDetailStatus|''}) {
  const {scan} = useWorkspace();
  const live = isLiveSnapshot(scan);
  return <>
    {live ? <ResourcesView initialProvider={provider} initialCategory={category} initialIntent={intent} initialPricing={pricing} initialArmDetail={armDetail}/>
      : <FindingsGrid initialProvider={provider} initialCategory={category} initialIntent={intent} initialPricing={pricing} navigateToResource/>}
  </>;
}

export function ConsolePage({view,provider='',category='',intent='',pricing='',armDetail=''}:{view:View;provider?:string;category?:Category|'';intent?:Intent;pricing?:Pricing;armDetail?:import('../lib/resources').ArmDetailStatus|''}) {
  const {workspace,scan} = useWorkspace();
  const heading=headings[view];
  return <><div className="page-heading" data-atlas-rollout={`console-${view}`}>{view!=='overview'&&<h1>{heading}</h1>}</div>
    {view==='overview'?<Overview/>:view==='resources'?<DiscoverResources key={`${workspace?.tenant_id}-${scan?.scan_id||'empty'}`} provider={provider} category={category} intent={intent} pricing={pricing} armDetail={armDetail}/>:view==='allocation'?<Allocation/>:view==='automation'?<Automation/>:view==='activity'?<ActivityView/>:<SettingsView/>}
  </>;
}
