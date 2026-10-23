'use client';

import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {useEffect, useState} from 'react';
import {ArrowLeft, CreditCard, KeyRound, LayoutGrid, Pause, Pencil, Play, Plus, RefreshCw, Trash2} from 'lucide-react';
import {portal} from '../../lib/api';
import {formatAttribution} from '../../lib/format';
import type {Customer, Workspace} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {useSession} from '../SessionProvider';
import {CreateWorkspaceDialog} from '../workspaces/CreateWorkspaceDialog';
import {WorkspaceTable, workspaceHref} from '../workspaces/WorkspaceTable';
import {BillingStateBadge, EmptyState, Loading, Notice, PageHeading, SectionTitle, StatusBadge} from '../ui/shared';
import {BillingTab} from './BillingTab';
import {BootstrapKeyDialog, ClaimStatusBadge} from './BootstrapKeyDialog';
import {ConfirmDialog, CustomerFormDialog} from './CustomerDialogs';

type Detail = {customer: Customer; workspaces: Workspace[]};
type Pending = 'edit' | 'suspend' | 'reactivate' | 'delete' | 'workspace' | 'bootstrap' | null;

const TABS = [
  {id: 'overview', label: 'Overview', icon: LayoutGrid},
  {id: 'billing', label: 'Billing', icon: CreditCard},
] as const;
type Tab = typeof TABS[number]['id'];

export function CustomerDetail({id}: {id: string}) {
  const router = useRouter();
  const {canWrite} = useSession();
  const [tab, setTab] = useState<Tab>('overview');
  const [pending, setPending] = useState<Pending>(null);
  const [message, setMessage] = useState('');
  const {data, setData, error, loading, reload} = useLoad(() => portal<Detail>(`customers/${encodeURIComponent(id)}`), [id]);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('tab') === 'billing') setTab('billing');
  }, []);

  if (loading && !data) return <Loading label="Loading customer…"/>;
  if (!data) return <>
    <Link className="breadcrumb" href="/customers"><ArrowLeft size={14}/>Customers</Link>
    <Notice tone="error">{error || 'Something went wrong. If the issue persists, contact Support.'}</Notice>
  </>;

  const {customer, workspaces} = data;
  const path = `customers/${encodeURIComponent(customer.id)}`;
  const lifecycle = async (action: 'suspend' | 'reactivate') => {
    const updated = await portal<Customer>(`${path}/${action}`, {method: 'POST', body: {version: customer.version}});
    setPending(null);
    setMessage(action === 'suspend' ? 'Customer suspended. Its workspaces can’t use their keys until you reactivate it.' : 'Customer reactivated.');
    setData({customer: updated, workspaces});
    void reload();
  };
  const remove = async () => {
    await portal<Customer>(path, {method: 'DELETE', query: {version: customer.version}});
    router.push('/customers');
  };
  const editable = canWrite && customer.status !== 'deleted';
  const selectTab = (next: Tab) => {
    setTab(next);
    window.history.replaceState(null, '', next === 'billing' ? `?tab=billing` : window.location.pathname);
  };

  return <>
    <Link className="breadcrumb" href="/customers"><ArrowLeft size={14}/>Customers</Link>
    <PageHeading eyebrow="CUSTOMER" title={customer.name} actions={<button type="button" className="button secondary" onClick={() => void reload()}><RefreshCw size={15}/>Refresh</button>}>
      <StatusBadge status={customer.status}/> <ClaimStatusBadge status={customer.claim_status}/> {customer.billing_state && <BillingStateBadge state={customer.billing_state}/>}
    </PageHeading>
    {message && <Notice tone="success">{message}</Notice>}
    {error && <Notice tone="error">{error}</Notice>}
    <div className="page-tabs" role="tablist" aria-label="Customer sections">
      {TABS.map(item => <button key={item.id} type="button" role="tab" id={`tab-${item.id}`} aria-controls={`panel-${item.id}`} aria-selected={tab === item.id} onClick={() => selectTab(item.id)}><item.icon size={15}/>{item.label}</button>)}
    </div>
    <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
      {tab === 'overview' && <>
        <section className="panel">
          <SectionTitle title="Overview" action={editable ? <div className="section-actions">
            <button type="button" className="button secondary small" onClick={() => setPending('edit')}><Pencil size={14}/>Edit</button>
            {customer.claim_status === 'pending' && customer.status === 'active' && <button type="button" className="button secondary small" onClick={() => setPending('bootstrap')}><KeyRound size={14}/>Issue onboarding key</button>}
            {customer.status === 'active' && <button type="button" className="button secondary small" onClick={() => setPending('suspend')}><Pause size={14}/>Suspend customer</button>}
            {customer.status === 'suspended' && <button type="button" className="button secondary small" onClick={() => setPending('reactivate')}><Play size={14}/>Reactivate customer</button>}
            <button type="button" className="button danger-outline small" onClick={() => setPending('delete')}><Trash2 size={14}/>Delete customer</button>
          </div> : undefined}/>
          <dl className="detail-list">
            <div><dt>Name</dt><dd>{customer.name}</dd></div>
            <div><dt>Status</dt><dd><StatusBadge status={customer.status}/></dd></div>
            <div><dt>Account ownership</dt><dd>{customer.claim_status === 'claimed' ? 'Claimed. The customer manages its own users and keys.' : 'Awaiting claim. Issue an onboarding key to the first administrator.'}</dd></div>
            <div><dt>Workspaces</dt><dd>{customer.workspace_count} total, {customer.active_workspace_count} active</dd></div>
            <div><dt>Created</dt><dd>{formatAttribution(customer.created_at, customer.created_by)}</dd></div>
            <div><dt>Last updated</dt><dd>{formatAttribution(customer.updated_at, customer.updated_by)}</dd></div>
            <div className="full"><dt>Notes</dt><dd>{customer.notes || <span className="muted">No notes</span>}</dd></div>
          </dl>
        </section>
        <section className="panel">
          <SectionTitle title="Workspaces" action={editable ? <button type="button" className="button primary small" onClick={() => setPending('workspace')}><Plus size={14}/>Create workspace</button> : undefined}/>
          {workspaces.length ? <WorkspaceTable workspaces={workspaces} showCustomer={false}/> : <EmptyState icon={LayoutGrid} title="No workspaces yet">Create a workspace to connect this customer’s cloud accounts and issue keys.</EmptyState>}
        </section>
      </>}
      {tab === 'billing' && <BillingTab customer={customer} onEditCustomer={editable ? () => setPending('edit') : undefined}/>}
    </div>

    <CustomerFormDialog open={pending === 'edit'} customer={customer} onClose={() => setPending(null)} onSaved={updated => {setPending(null); setMessage('Customer updated.'); setData({customer: updated, workspaces});}}/>
    <ConfirmDialog open={pending === 'suspend'} title="Suspend this customer?" confirmLabel="Suspend customer" destructive
      body={`Every workspace for ${customer.name} stops accepting its keys right away. Keys aren't revoked, and you can reactivate the customer later.`}
      onClose={() => setPending(null)} onConfirm={() => lifecycle('suspend')}/>
    <ConfirmDialog open={pending === 'reactivate'} title="Reactivate this customer?" confirmLabel="Reactivate customer"
      body={`Workspaces for ${customer.name} can use their active keys again.`}
      onClose={() => setPending(null)} onConfirm={() => lifecycle('reactivate')}/>
    <ConfirmDialog open={pending === 'delete'} title="Delete this customer?" confirmLabel="Delete customer" destructive
      body={customer.active_workspace_count || workspaces.some(w => w.status !== 'deleted')
        ? `${customer.name} still has workspaces. Delete each workspace first, then delete the customer.`
        : `${customer.name} will be removed from the directory. You can't undo this.`}
      onClose={() => setPending(null)} onConfirm={remove}/>
    <BootstrapKeyDialog open={pending === 'bootstrap'} customer={customer} workspaces={workspaces} onClose={() => setPending(null)} onIssued={() => void reload()}/>
    <CreateWorkspaceDialog open={pending === 'workspace'} customer={customer} onClose={() => setPending(null)} onCreated={workspace => {setPending(null); router.push(workspaceHref(workspace.tenant_id));}}/>
  </>;
}
