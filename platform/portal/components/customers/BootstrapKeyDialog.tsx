'use client';

import {useEffect, useState} from 'react';
import {Loader2} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import type {Customer, IssuedKey, Workspace} from '../../lib/types';
import {Dialog} from '../ui/Dialog';
import {Notice} from '../ui/shared';
import {SecretReveal} from '../workspaces/KeyFields';

const LIFETIMES = [24, 48, 72];

export function ClaimStatusBadge({status}: {status?: Customer['claim_status']}) {
  if (!status) return null;
  return <span className={`state-badge ${status === 'claimed' ? 'active' : 'suspended'}`}>{status === 'claimed' ? 'Claimed' : 'Awaiting claim'}</span>;
}

/** Issues the single-use onboarding key the customer's first administrator uses to claim the account. */
export function BootstrapKeyDialog({open, customer, workspaces, onClose, onIssued}: {
  open: boolean; customer: Customer; workspaces: Workspace[]; onClose: () => void; onIssued: () => void;
}) {
  const active = workspaces.filter(w => w.status === 'active');
  const [tenantId, setTenantId] = useState('');
  const [hours, setHours] = useState(24);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [secret, setSecret] = useState('');

  useEffect(() => {
    if (!open) return;
    setTenantId(active[0]?.tenant_id || ''); setHours(24); setError(''); setSecret('');
    // Reloading the customer after issuing must not discard the one-time secret.
  }, [open]);

  function close() {setSecret(''); onClose();}

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!tenantId) return;
    setBusy(true); setError('');
    try {
      const expires = new Date(Date.now() + hours * 3600000).toISOString();
      const issued = await portal<IssuedKey>(`customers/${encodeURIComponent(customer.id)}/bootstrap-key`, {
        method: 'POST', body: {tenant_id: tenantId, expires_at: expires},
      });
      setSecret(issued.secret);
      onIssued();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return <Dialog open={open} onClose={close} title={secret ? 'Onboarding key' : 'Issue onboarding key'} dismissible={!secret}>
    {secret ? <>
      <div className="dialog-content"><Notice tone="info">Send this key to {customer.name}’s first administrator through a secure channel. It works once, and they use it to claim the account on the CloudSaver claim page.</Notice></div>
      <SecretReveal secret={secret} onClose={close}/>
    </> : <form className="dialog-form" onSubmit={submit} noValidate>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        {!active.length && <Notice tone="warning">Create an active workspace for this customer first.</Notice>}
        <p>The first administrator uses this single-use key to claim {customer.name}. After that, they manage their own users and keys.</p>
        <label className="field">Workspace
          <select value={tenantId} onChange={event => setTenantId(event.target.value)} disabled={!active.length}>
            {active.map(w => <option key={w.tenant_id} value={w.tenant_id}>{w.name}</option>)}
          </select>
          <span className="field-hint">The administrator gets workspace admin access here.</span>
        </label>
        <label className="field">Expires after
          <select value={hours} onChange={event => setHours(Number(event.target.value))}>
            {LIFETIMES.map(h => <option key={h} value={h}>{h} hours</option>)}
          </select>
        </label>
      </div>
      <div className="dialog-actions">
        <button type="button" className="button secondary" onClick={close}>Cancel</button>
        <button type="submit" className="button primary" disabled={busy || !tenantId}>{busy && <Loader2 className="spin" size={15}/>}Issue key</button>
      </div>
    </form>}
  </Dialog>;
}
