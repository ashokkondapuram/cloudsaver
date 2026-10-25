'use client';

import Link from 'next/link';
import {useState} from 'react';
import {Activity, ArrowLeft, BarChart3, Cloud, KeyRound, LayoutGrid, ListChecks, RefreshCw} from 'lucide-react';
import {portal} from '../../lib/api';
import type {Workspace} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {AuditList} from '../activity/AuditList';
import {Loading, Notice, PageHeading, StatusBadge} from '../ui/shared';
import {CloudAccountsTab} from './CloudAccountsTab';
import {KeysTab} from './KeysTab';
import {OverviewTab} from './OverviewTab';
import {ResourceAccessTab} from './ResourceAccessTab';
import {RulesTab} from './RulesTab';
import {UsageTab} from './UsageTab';

const TABS = [
  {id: 'overview', label: 'Overview', icon: LayoutGrid},
  {id: 'cloud', label: 'Cloud accounts', icon: Cloud},
  {id: 'access', label: 'Resource access', icon: Cloud},
  {id: 'rules', label: 'Rules', icon: ListChecks},
  {id: 'keys', label: 'Keys', icon: KeyRound},
  {id: 'usage', label: 'Usage', icon: BarChart3},
  {id: 'activity', label: 'Activity', icon: Activity},
] as const;
type Tab = typeof TABS[number]['id'];

export function WorkspaceDetail({tenantId}: {tenantId: string}) {
  const [tab, setTab] = useState<Tab>('overview');
  const {data: workspace, setData, error, loading, reload} = useLoad(() => portal<Workspace>(`workspaces/${encodeURIComponent(tenantId)}`), [tenantId]);

  if (loading && !workspace) return <Loading label="Loading workspace…"/>;
  if (!workspace) return <>
    <Link className="breadcrumb" href="/workspaces"><ArrowLeft size={14}/>Workspaces</Link>
    <Notice tone="error">{error || 'Something went wrong. If the issue persists, contact Support.'}</Notice>
  </>;

  return <>
    <Link className="breadcrumb" href="/workspaces"><ArrowLeft size={14}/>Workspaces</Link>
    <PageHeading eyebrow="WORKSPACE" title={workspace.name} actions={<button type="button" className="button secondary" onClick={() => void reload()}><RefreshCw size={15}/>Refresh</button>}>
      <StatusBadge status={workspace.status}/> <Link className="text-link" href={`/customers/${encodeURIComponent(workspace.customer_id)}`}>{workspace.customer_name}</Link> · <code>{workspace.tenant_id}</code>
    </PageHeading>
    {error && <Notice tone="error">{error}</Notice>}
    {workspace.status === 'suspended' && <Notice tone="warning">This workspace is suspended. Its keys don’t work until you reactivate it.</Notice>}
    {workspace.status === 'deleted' && <Notice tone="warning">This workspace was deleted. Its keys are revoked and it can’t be changed.</Notice>}
    <div className="page-tabs" role="tablist" aria-label="Workspace sections">
      {TABS.map(item => <button key={item.id} type="button" role="tab" id={`tab-${item.id}`} aria-controls={`panel-${item.id}`} aria-selected={tab === item.id} onClick={() => setTab(item.id)}><item.icon size={15}/>{item.label}</button>)}
    </div>
    <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
      {tab === 'overview' && <OverviewTab workspace={workspace} onChange={setData} reload={reload}/>}
      {tab === 'cloud' && <CloudAccountsTab workspace={workspace} onChange={setData} reload={reload}/>}
      {tab === 'access' && <ResourceAccessTab workspace={workspace} onChange={setData}/>}
      {tab === 'rules' && <RulesTab workspace={workspace}/>}
      {tab === 'keys' && <KeysTab workspace={workspace} reloadWorkspace={reload}/>}
      {tab === 'usage' && <UsageTab workspace={workspace}/>}
      {tab === 'activity' && <section className="panel"><AuditList filters={{tenant_id: workspace.tenant_id}} title="Activity" description="Changes to this workspace and its keys."/></section>}
    </div>
  </>;
}
