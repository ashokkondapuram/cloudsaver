'use client';

import {useState} from 'react';
import {Check, Loader2, X} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import {formatBillingDate} from '../../lib/format';
import type {PlanChangeRequest} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {useSession} from '../SessionProvider';
import {Loading, Notice} from '../ui/shared';

const PLAN_NAMES: Record<string, string> = {STARTER: 'Starter', GROWTH: 'Growth', ENTERPRISE: 'Enterprise'};

export function PlanChangeQueue({onChanged}: {onChanged?: () => void}) {
  const {canManageBilling} = useSession();
  const {data, error, loading, reload} = useLoad(() => portal<{items: PlanChangeRequest[]}>('plan-change-requests'), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState('');

  async function decide(request: PlanChangeRequest, action: 'approve' | 'reject') {
    setBusy(request.id);
    setActionError('');
    try {
      await portal(`plan-change-requests/${request.id}/${action}`, {
        method: 'POST',
        body: {version: request.version},
      });
      await reload();
      onChanged?.();
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setBusy(null);
    }
  }

  const rows = data?.items || [];
  if (loading && !data) return <Loading label="Loading plan requests…"/>;
  if (!rows.length && !error) return null;

  return <section className="panel">
    <div className="section-title"><div><h2>Plan change requests</h2><p className="muted">Submitted from CloudSaver for your approval. Stripe checkout will follow approval when billing uses Stripe.</p></div></div>
    {error && <Notice tone="error">{error}</Notice>}
    {actionError && <Notice tone="error">{actionError}</Notice>}
    {rows.length ? <div className="summary-table-scroll"><table className="summary-table">
      <thead><tr><th>Workspace</th><th>Customer</th><th>Change</th><th>Requested</th><th>Status</th><th/></tr></thead>
      <tbody>{rows.map(row => <tr key={row.id}>
        <td>{row.workspace_name || row.tenant_id}</td>
        <td>{row.customer_name || row.customer_id}</td>
        <td>{PLAN_NAMES[row.current_plan_code] || row.current_plan_code} → {PLAN_NAMES[row.requested_plan_code] || row.requested_plan_code}</td>
        <td>{formatBillingDate(row.created_at)}<span className="cell-sub">{row.requested_by}</span></td>
        <td>{row.status === 'pending_payment' ? 'Pending payment' : 'Pending approval'}</td>
        <td className="table-actions">
          {row.status === 'pending_approval' && canManageBilling ? <>
            <button type="button" className="button secondary" disabled={busy === row.id} onClick={() => void decide(row, 'reject')}>
              {busy === row.id ? <Loader2 className="spin" size={15}/> : <X size={15}/>}Reject
            </button>
            <button type="button" className="button" disabled={busy === row.id} onClick={() => void decide(row, 'approve')}>
              {busy === row.id ? <Loader2 className="spin" size={15}/> : <Check size={15}/>}Approve
            </button>
          </> : <span className="muted">Awaiting Stripe</span>}
        </td>
      </tr>)}</tbody>
    </table></div> : !error ? <p className="muted">No pending plan change requests.</p> : null}
  </section>;
}
