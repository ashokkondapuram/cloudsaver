'use client';

import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {useEffect, useState} from 'react';
import {Loader2, Pause, Pencil, Play, Trash2} from 'lucide-react';
import {ApiError, errorMessage, portal} from '../../lib/api';
import {formatAttribution, formatDateTime} from '../../lib/format';
import {PLANS, planName} from '../../lib/labels';
import type {Customer, Page, PlanTier, Workspace} from '../../lib/types';
import {customerBillingHref} from '../billing/common';
import {ConfirmDialog} from '../customers/CustomerDialogs';
import {useSession} from '../SessionProvider';
import {StepUpPrompt} from '../StepUpPrompt';
import {Dialog} from '../ui/Dialog';
import {Notice, ProviderList, SectionTitle, StatusBadge} from '../ui/shared';

type Props = {workspace: Workspace; onChange: (workspace: Workspace) => void; reload: () => Promise<void>};

export function OverviewTab({workspace, onChange, reload}: Props) {
  const router = useRouter();
  const {canWrite} = useSession();
  const [pending, setPending] = useState<'edit' | 'suspend' | 'reactivate' | 'delete' | null>(null);
  const [message, setMessage] = useState('');
  const path = `workspaces/${encodeURIComponent(workspace.tenant_id)}`;
  const editable = canWrite && workspace.status !== 'deleted';

  async function lifecycle(action: 'suspend' | 'reactivate') {
    const updated = await portal<Workspace>(`${path}/${action}`, {method: 'POST', body: {version: workspace.version}});
    onChange(updated);
    setPending(null);
    setMessage(action === 'suspend' ? 'Workspace suspended. Its keys stop working right away.' : 'Workspace reactivated. Its active keys work again.');
  }

  return <>
    {message && <Notice tone="success">{message}</Notice>}
    <section className="panel">
      <SectionTitle title="Overview" action={editable ? <div className="section-actions">
        <button type="button" className="button secondary small" onClick={() => setPending('edit')}><Pencil size={14}/>Edit</button>
        {workspace.status === 'active' && <button type="button" className="button secondary small" onClick={() => setPending('suspend')}><Pause size={14}/>Suspend workspace</button>}
        {workspace.status === 'suspended' && <button type="button" className="button secondary small" onClick={() => setPending('reactivate')}><Play size={14}/>Reactivate workspace</button>}
        <button type="button" className="button danger-outline small" onClick={() => setPending('delete')}><Trash2 size={14}/>Delete workspace</button>
      </div> : undefined}/>
      <dl className="detail-list">
        <div><dt>Name</dt><dd>{workspace.name}</dd></div>
        <div><dt>Customer</dt><dd>{workspace.customer_name}</dd></div>
        <div><dt>Plan</dt><dd>{planName(workspace.plan_tier, workspace.plan_name)}{workspace.plan_locked && <span className="cell-sub">Set by the customer’s subscription. Change it on the customer’s <Link className="text-link" href={customerBillingHref(workspace.customer_id)}>Billing tab</Link>.</span>}</dd></div>
        <div><dt>Status</dt><dd><StatusBadge status={workspace.status}/>{workspace.suspended_at && workspace.status === 'suspended' && <span className="cell-sub">Since {formatDateTime(workspace.suspended_at)}</span>}</dd></div>
        <div><dt>Workspace ID</dt><dd><code>{workspace.tenant_id}</code></dd></div>
        <div><dt>Providers</dt><dd><ProviderList providers={workspace.providers} empty="No cloud accounts yet"/></dd></div>
        <div><dt>Azure app client ID</dt><dd>{workspace.identity.azure_app_client_id ? <code>{workspace.identity.azure_app_client_id}</code> : <span className="muted">Not set</span>}</dd></div>
        <div><dt>GCP service account</dt><dd>{workspace.identity.gcp_service_account ? <code>{workspace.identity.gcp_service_account}</code> : <span className="muted">Not set</span>}</dd></div>
        <div><dt>Created</dt><dd>{formatAttribution(workspace.created_at, workspace.created_by)}</dd></div>
        <div><dt>Last updated</dt><dd>{formatAttribution(workspace.updated_at, workspace.updated_by)}</dd></div>
      </dl>
    </section>
    <EditWorkspaceDialog open={pending === 'edit'} workspace={workspace} onClose={() => setPending(null)} onSaved={updated => {onChange(updated); setPending(null); setMessage('Workspace updated.');}}/>
    <ConfirmDialog open={pending === 'suspend'} title="Suspend this workspace?" confirmLabel="Suspend workspace" destructive
      body="Every key for this workspace stops working right away. Keys aren't revoked, and you can reactivate the workspace later."
      onClose={() => setPending(null)} onConfirm={() => lifecycle('suspend')}/>
    <ConfirmDialog open={pending === 'reactivate'} title="Reactivate this workspace?" confirmLabel="Reactivate workspace"
      body="Active keys for this workspace work again right away."
      onClose={() => setPending(null)} onConfirm={() => lifecycle('reactivate')}/>
    <DeleteWorkspaceDialog open={pending === 'delete'} workspace={workspace} onClose={() => setPending(null)} onDeleted={() => {setPending(null); void reload(); router.push('/workspaces');}}/>
  </>;
}

function EditWorkspaceDialog({open, workspace, onClose, onSaved}: {open: boolean; workspace: Workspace; onClose: () => void; onSaved: (workspace: Workspace) => void}) {
  const [name, setName] = useState('');
  const [plan, setPlan] = useState<PlanTier>('STARTER');
  const [customerId, setCustomerId] = useState('');
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!open) return;
    setName(workspace.name); setPlan(workspace.plan_tier); setCustomerId(workspace.customer_id); setError('');
    portal<Page<Customer>>('customers', {query: {status: 'active', limit: 100}}).then(page => setCustomers(page.items)).catch(() => setCustomers([]));
  }, [open, workspace]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      const body: Record<string, unknown> = {version: workspace.version};
      if (name.trim() !== workspace.name) body.name = name.trim();
      if (!workspace.plan_locked && plan !== workspace.plan_tier) body.plan_tier = plan;
      if (customerId !== workspace.customer_id) body.customer_id = customerId;
      onSaved(await portal<Workspace>(`workspaces/${encodeURIComponent(workspace.tenant_id)}`, {method: 'PATCH', body}));
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  const customerOptions = customers.some(item => item.id === workspace.customer_id) ? customers : [{id: workspace.customer_id, name: workspace.customer_name} as Customer, ...customers];
  return <Dialog open={open} onClose={onClose} title="Edit workspace">
    <form className="dialog-form" onSubmit={submit}>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        <label className="field">Workspace name<input type="text" value={name} onChange={event => setName(event.target.value)} maxLength={120} required/></label>
        <div className="form-grid">
          <label className="field">Customer<select value={customerId} onChange={event => setCustomerId(event.target.value)}>{customerOptions.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          {workspace.plan_locked
            ? <label className="field">Plan<input type="text" value={planName(workspace.plan_tier, workspace.plan_name)} disabled/><span className="field-hint">Set by the customer’s subscription. Change it on the customer’s Billing tab.</span></label>
            : <label className="field">Plan<select value={plan} onChange={event => setPlan(event.target.value as PlanTier)}>{(PLANS.includes(workspace.plan_tier) ? PLANS : [workspace.plan_tier, ...PLANS]).map(tier => <option key={tier} value={tier}>{planName(tier, tier === workspace.plan_tier ? workspace.plan_name : null)}</option>)}</select></label>}
        </div>
      </div>
      <div className="dialog-actions">
        <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
        <button type="submit" className="button primary" disabled={busy || !name.trim()}>{busy && <Loader2 className="spin" size={15}/>}Save changes</button>
      </div>
    </form>
  </Dialog>;
}

function DeleteWorkspaceDialog({open, workspace, onClose, onDeleted}: {open: boolean; workspace: Workspace; onClose: () => void; onDeleted: () => void}) {
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [stepUp, setStepUp] = useState(false);
  useEffect(() => {if (open) {setTyped(''); setError(''); setStepUp(false);}}, [open]);

  async function remove() {
    setBusy(true); setError('');
    try {
      await portal<Workspace>(`workspaces/${encodeURIComponent(workspace.tenant_id)}`, {method: 'DELETE', query: {version: workspace.version}});
      onDeleted();
    } catch (cause) {
      if (cause instanceof ApiError && cause.stepUp) setStepUp(true);
      else setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <Dialog open={open} onClose={onClose} title="Delete this workspace?">
    <div className="dialog-content">
      {error && <Notice tone="error">{error}</Notice>}
      {stepUp && <StepUpPrompt onSignedIn={() => {setStepUp(false); void remove();}}/>}
      <p>This revokes every key for this workspace. You can’t undo this.</p>
      <label className="field">Type <strong>{workspace.name}</strong> to confirm<input type="text" value={typed} onChange={event => setTyped(event.target.value)} autoComplete="off" autoFocus/></label>
    </div>
    <div className="dialog-actions">
      <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
      <button type="button" className="button danger" disabled={busy || typed !== workspace.name} onClick={() => void remove()}>{busy && <Loader2 className="spin" size={15}/>}Delete workspace</button>
    </div>
  </Dialog>;
}
