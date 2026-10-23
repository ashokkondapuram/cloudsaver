'use client';

import {useState} from 'react';
import {Archive, Eye, Layers, Pencil, Plus, RefreshCw} from 'lucide-react';
import {portal} from '../../lib/api';
import {formatNumber} from '../../lib/format';
import {priceText} from '../../lib/labels';
import type {Plan} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {ConfirmDialog} from '../customers/CustomerDialogs';
import {useSession} from '../SessionProvider';
import {EmptyState, Loading, Notice, PageHeading} from '../ui/shared';
import {BillingOffNotice, plural, ReadOnlyNotice} from '../billing/common';
import {PlanFormDialog} from './PlanDialogs';

export function PlanList() {
  const {canManageBilling} = useSession();
  const [creating, setCreating] = useState(false);
  const [viewing, setViewing] = useState<Plan | null>(null);
  const [editing, setEditing] = useState<Plan | null>(null);
  const [retiring, setRetiring] = useState<Plan | null>(null);
  const [message, setMessage] = useState('');
  const {data, error, loading, reload} = useLoad(() => portal<{items: Plan[]}>('plans'), []);

  async function retire() {
    if (!retiring) return;
    await portal<Plan>(`plans/${encodeURIComponent(retiring.code)}/retire`, {method: 'POST', body: {version: retiring.version}});
    setMessage(`${retiring.name} retired. You can’t assign it to new subscriptions.`);
    setRetiring(null);
    void reload();
  }

  const plans = data?.items || [];
  return <>
    <PageHeading eyebrow="BILLING" title="Plans" actions={<>
      <button type="button" className="button secondary" onClick={() => void reload()}><RefreshCw size={15}/>Refresh</button>
      {canManageBilling && <button type="button" className="button primary" onClick={() => setCreating(true)}><Plus size={15}/>Create plan</button>}
    </>}>Plans set what every workspace of a customer can do. Changes apply within 30 seconds.</PageHeading>
    <BillingOffNotice/>
    <ReadOnlyNotice/>
    {message && <Notice tone="success">{message}</Notice>}
    <section className="panel">
      <div className="section-title"><div><h2>All plans</h2></div></div>
      {error && <Notice tone="error">{error}</Notice>}
      {loading && !data ? <Loading label="Loading plans…"/> : !plans.length ? (!error && <EmptyState icon={Layers} title="No plans yet"
        action={canManageBilling ? <button type="button" className="button primary" onClick={() => setCreating(true)}><Plus size={15}/>Create plan</button> : undefined}>
        Create a plan to start subscribing customers.
      </EmptyState>) : <div className="summary-table-scroll"><table className="summary-table">
        <thead><tr><th>Plan</th><th>Price</th><th className="number">Customers</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>{plans.map(plan => <tr key={plan.code}>
          <td><strong>{plan.name}</strong><span className="cell-sub"><code>{plan.code}</code>{plan.description ? ` · ${plan.description}` : ''}</span></td>
          <td>{plan.list_price_minor === null ? <span className="muted">Custom pricing</span> : priceText(plan.list_price_minor, plan.currency, plan.interval)}</td>
          <td className="number">{formatNumber(plan.customer_count)}<span className="cell-sub">{plural(plan.workspace_count, 'workspace')}</span></td>
          <td><span className={`state-badge plan-${plan.status}`}>{plan.status === 'active' ? 'Active' : 'Retired'}</span></td>
          <td><div className="row-actions">
            {canManageBilling && plan.status === 'active' ? <>
              <button type="button" className="button secondary small" onClick={() => setEditing(plan)} aria-label={`Edit ${plan.name}`}><Pencil size={13}/>Edit</button>
              <button type="button" className="button danger-outline small" onClick={() => setRetiring(plan)} aria-label={`Retire ${plan.name}`}><Archive size={13}/>Retire plan</button>
            </> : <button type="button" className="button secondary small" onClick={() => setViewing(plan)} aria-label={`View ${plan.name}`}><Eye size={13}/>View</button>}
          </div></td>
        </tr>)}</tbody>
      </table></div>}
    </section>

    <PlanFormDialog open={creating} onClose={() => setCreating(false)} onSaved={plan => {setCreating(false); setMessage(`${plan.name} created.`); void reload();}}/>
    <PlanFormDialog open={!!editing} plan={editing} onClose={() => setEditing(null)} onSaved={plan => {
      setEditing(null); setMessage(`This change applies to ${plural(plan.customer_count, 'customer')} within 30 seconds.`); void reload();
    }}/>
    <PlanFormDialog open={!!viewing} plan={viewing} readOnly onClose={() => setViewing(null)} onSaved={() => setViewing(null)}/>
    <ConfirmDialog open={!!retiring} title="Retire this plan?" confirmLabel="Retire plan" destructive
      body={retiring ? `You can’t assign ${retiring.name} to new subscriptions. Its ${plural(retiring.customer_count, 'customer')} and ${plural(retiring.workspace_count, 'workspace')} keep it until you change their plan.` : ''}
      onClose={() => setRetiring(null)} onConfirm={retire}/>
  </>;
}
