'use client';

import {useEffect, useState} from 'react';
import {Loader2} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import {PLANS, planLabel} from '../../lib/labels';
import type {Customer, Page, PlanTier, Workspace} from '../../lib/types';
import {useSession} from '../SessionProvider';
import {Dialog} from '../ui/Dialog';
import {Notice} from '../ui/shared';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function CreateWorkspaceDialog({open, customer, onClose, onCreated}: {
  open: boolean; customer?: Pick<Customer, 'id' | 'name'> | null; onClose: () => void; onCreated: (workspace: Workspace) => void;
}) {
  const {session} = useSession();
  const planLocked = !!session?.billing_enabled;
  const [tenantId, setTenantId] = useState('');
  const [name, setName] = useState('');
  const [customerId, setCustomerId] = useState('');
  const [plan, setPlan] = useState<PlanTier>('STARTER');
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setTenantId(''); setName(''); setPlan('STARTER'); setError(''); setCustomerId(customer?.id || '');
    if (customer) return;
    portal<Page<Customer>>('customers', {query: {status: 'active', limit: 100}})
      .then(page => setCustomers(page.items))
      .catch(cause => setError(errorMessage(cause)));
  }, [open, customer]);

  const tenantInvalid = tenantId.trim() !== '' && !UUID.test(tenantId.trim());

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      const workspace = await portal<Workspace>('workspaces', {method: 'POST', body: {
        tenant_id: tenantId.trim().toLowerCase(), customer_id: customerId, name: name.trim(), ...(planLocked ? {} : {plan_tier: plan}),
      }});
      onCreated(workspace);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <Dialog open={open} onClose={onClose} title="Create workspace">
    <form className="dialog-form" onSubmit={submit}>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        <label className="field">Workspace ID
          <input type="text" value={tenantId} onChange={event => setTenantId(event.target.value)} placeholder="00000000-0000-0000-0000-000000000000" required autoFocus aria-invalid={tenantInvalid}/>
          {tenantInvalid ? <span className="field-error">Enter a workspace ID in the format 00000000-0000-0000-0000-000000000000.</span> : <span className="field-hint">If the customer connects Azure, use their Microsoft Entra tenant ID. AWS uses it as the external ID. You can’t change it later.</span>}
        </label>
        <label className="field">Workspace name<input type="text" value={name} onChange={event => setName(event.target.value)} maxLength={120} required/></label>
        <div className="form-grid">
          <label className="field">Customer
            {customer ? <input type="text" value={customer.name} disabled/> : <select value={customerId} onChange={event => setCustomerId(event.target.value)} required>
              <option value="">Select a customer</option>
              {customers.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>}
          </label>
          {planLocked
            ? <label className="field">Plan<input type="text" value="Set by the customer’s subscription" disabled/></label>
            : <label className="field">Plan<select value={plan} onChange={event => setPlan(event.target.value as PlanTier)}>{PLANS.map(tier => <option key={tier} value={tier}>{planLabel[tier]}</option>)}</select></label>}
        </div>
      </div>
      <div className="dialog-actions">
        <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
        <button type="submit" className="button primary" disabled={busy || !name.trim() || !customerId || !UUID.test(tenantId.trim())}>{busy && <Loader2 className="spin" size={15}/>}Create workspace</button>
      </div>
    </form>
  </Dialog>;
}
