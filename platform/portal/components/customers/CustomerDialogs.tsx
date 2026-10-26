'use client';

import {useEffect, useState} from 'react';
import {Loader2} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import {httpsUrlError} from '../../lib/format';
import type {Customer} from '../../lib/types';
import {useSession} from '../SessionProvider';
import {Dialog} from '../ui/Dialog';
import {Notice} from '../ui/shared';

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const STRIPE_CUSTOMER = /^cus_[A-Za-z0-9]+$/;

/** Creates a customer, or edits one (including billing contact details) when `customer` is provided. */
export function CustomerFormDialog({open, customer, onClose, onSaved}: {
  open: boolean; customer?: Customer | null; onClose: () => void; onSaved: (customer: Customer) => void;
}) {
  const {session} = useSession();
  const [name, setName] = useState('');
  const [notes, setNotes] = useState('');
  const [billingEmail, setBillingEmail] = useState('');
  const [manageUrl, setManageUrl] = useState('');
  const [stripeId, setStripeId] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!open) return;
    setName(customer?.name || ''); setNotes(customer?.notes || ''); setError(''); setSubmitted(false);
    setBillingEmail(customer?.billing_contact_email || ''); setManageUrl(customer?.manage_billing_url || ''); setStripeId(customer?.external_customer_refs?.stripe || '');
  }, [open, customer]);

  const showStripe = !!customer && (session?.billing_provider === 'stripe' || !!customer.external_customer_refs?.stripe);
  const errors = {
    email: billingEmail.trim() && !EMAIL.test(billingEmail.trim()) ? 'Enter an email address, such as billing@example.com.' : '',
    url: httpsUrlError(manageUrl),
    stripe: stripeId.trim() && !STRIPE_CUSTOMER.test(stripeId.trim()) ? 'Enter a Stripe customer ID that starts with cus_.' : '',
  };

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitted(true);
    if (customer && Object.values(errors).some(Boolean)) return;
    setBusy(true); setError('');
    try {
      let saved: Customer;
      if (customer) {
        const body: Record<string, unknown> = {version: customer.version, name: name.trim(), notes: notes.trim() || null};
        const email = billingEmail.trim() || null;
        const url = manageUrl.trim() || null;
        if (email !== (customer.billing_contact_email || null)) body.billing_contact_email = email;
        if (url !== (customer.manage_billing_url || null)) body.manage_billing_url = url;
        if (showStripe && stripeId.trim() !== (customer.external_customer_refs?.stripe || '')) {
          const refs = {...(customer.external_customer_refs || {})};
          if (stripeId.trim()) refs.stripe = stripeId.trim(); else delete refs.stripe;
          body.external_customer_refs = refs;
        }
        saved = await portal<Customer>(`customers/${encodeURIComponent(customer.id)}`, {method: 'PATCH', body});
      } else {
        saved = await portal<Customer>('customers', {method: 'POST', body: {name: name.trim(), notes: notes.trim() || undefined}});
      }
      onSaved(saved);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  const show = (key: keyof typeof errors) => (submitted ? errors[key] : '');
  const title = customer ? 'Edit customer' : 'Create customer';
  return <Dialog open={open} onClose={onClose} title={title}>
    <form className="dialog-form" onSubmit={submit} noValidate={!!customer}>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        <label className="field">Customer name<input type="text" value={name} onChange={event => setName(event.target.value)} maxLength={120} required autoFocus data-autofocus/></label>
        <label className="field">Notes<span className="field-hint">Optional. Only platform operators and auditors can see notes.</span><textarea rows={4} value={notes} onChange={event => setNotes(event.target.value)} maxLength={2000}/></label>
        {customer && <>
          <label className="field">Billing email
            <input type="email" value={billingEmail} onChange={event => setBillingEmail(event.target.value)} maxLength={254} placeholder="billing@example.com" aria-invalid={!!show('email')}/>
            {show('email') ? <span className="field-error">{show('email')}</span> : <span className="field-hint">Optional. Where invoices and billing questions go.</span>}
          </label>
          <label className="field">Manage billing link
            <input type="url" value={manageUrl} onChange={event => setManageUrl(event.target.value)} maxLength={2048} placeholder="https://billing.example.com/customer" aria-invalid={!!show('url')}/>
            {show('url') ? <span className="field-error">{show('url')}</span> : <span className="field-hint">Optional. CloudSaver shows a Manage billing button with this link. Leave blank to use the platform default.</span>}
          </label>
          {showStripe && <label className="field">Stripe customer ID
            <input type="text" value={stripeId} onChange={event => setStripeId(event.target.value)} maxLength={255} placeholder="cus_..." aria-invalid={!!show('stripe')}/>
            {show('stripe') ? <span className="field-error">{show('stripe')}</span> : <span className="field-hint">Optional. Links Stripe subscriptions and invoices to this customer.</span>}
          </label>}
        </>}
      </div>
      <div className="dialog-actions">
        <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
        <button type="submit" className="button primary" disabled={busy || !name.trim()}>{busy && <Loader2 className="spin" size={15}/>}{customer ? 'Save changes' : 'Create customer'}</button>
      </div>
    </form>
  </Dialog>;
}

type ConfirmProps = {
  open: boolean; title: string; body: React.ReactNode; confirmLabel: string; destructive?: boolean;
  onClose: () => void; onConfirm: () => Promise<void>;
};

export function ConfirmDialog({open, title, body, confirmLabel, destructive, onClose, onConfirm}: ConfirmProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {if (open) setError('');}, [open]);
  async function confirm() {
    setBusy(true); setError('');
    try {await onConfirm();} catch (cause) {setError(errorMessage(cause));} finally {setBusy(false);}
  }
  return <Dialog open={open} onClose={onClose} title={title}>
    <div className="dialog-content">
      {error && <Notice tone="error">{error}</Notice>}
      <p>{body}</p>
    </div>
    <div className="dialog-actions">
      <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
      <button type="button" className={`button ${destructive ? 'danger' : 'primary'}`} disabled={busy} onClick={() => void confirm()}>{busy && <Loader2 className="spin" size={15}/>}{confirmLabel}</button>
    </div>
  </Dialog>;
}
