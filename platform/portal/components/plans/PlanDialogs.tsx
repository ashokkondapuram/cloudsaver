'use client';

import {useEffect, useState} from 'react';
import {Loader2} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import {isCurrencyCode, moneyInput, parseMoney} from '../../lib/format';
import {INTERVALS, intervalLabel} from '../../lib/labels';
import type {BillingInterval, Entitlements, Plan} from '../../lib/types';
import {useSession} from '../SessionProvider';
import {Dialog} from '../ui/Dialog';
import {Notice} from '../ui/shared';
import {plural} from '../billing/common';
import {draftErrors, EntitlementFields, fromDraft, toDraft, type EntitlementDraft} from '../billing/EntitlementFields';

const CODE = /^[A-Z][A-Z0-9_]{1,15}$/;
const STRIPE_PRICE = /^price_[A-Za-z0-9]+$/;

/** Creates a plan, edits one, or shows it read-only when `readOnly` is set. */
export function PlanFormDialog({open, plan, readOnly = false, onClose, onSaved}: {
  open: boolean; plan?: Plan | null; readOnly?: boolean; onClose: () => void; onSaved: (plan: Plan) => void;
}) {
  const {session} = useSession();
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [price, setPrice] = useState('');
  const [currency, setCurrency] = useState('USD');
  const [interval, setBillingInterval] = useState<BillingInterval>('month');
  const [stripePrices, setStripePrices] = useState('');
  const [draft, setDraft] = useState<EntitlementDraft>(() => toDraft({}));
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setCode(plan?.code || ''); setName(plan?.name || ''); setDescription(plan?.description || '');
    setCurrency(plan?.currency || 'USD'); setPrice(moneyInput(plan?.list_price_minor, plan?.currency || 'USD'));
    setBillingInterval(plan?.interval || 'month'); setStripePrices((plan?.external_price_refs?.stripe || []).join(', '));
    setDraft(toDraft(plan?.entitlements || {})); setSubmitted(false); setError('');
  }, [open, plan]);

  const showStripe = session?.billing_provider === 'stripe' || !!plan?.external_price_refs?.stripe?.length;
  const priceIds = stripePrices.split(/[\s,]+/).map(item => item.trim()).filter(Boolean);
  const currencyCode = currency.trim().toUpperCase();
  const priceMinor = price.trim() ? parseMoney(price, currencyCode) : null;
  const errors = {
    code: !plan && !CODE.test(code.trim()) ? 'Use 2 to 16 uppercase letters, numbers or underscores, starting with a letter.' : '',
    name: !name.trim() ? 'Enter a plan name.' : '',
    currency: price.trim() && !isCurrencyCode(currencyCode) ? 'Enter a 3-letter currency code, such as USD.' : '',
    price: price.trim() && priceMinor === null ? 'Enter an amount, such as 1,200.00.' : '',
    stripe: priceIds.some(id => !STRIPE_PRICE.test(id)) ? 'Enter Stripe price IDs that start with price_, separated by commas.' : '',
  };
  const entitlementErrors = draftErrors(draft);
  const invalid = Object.values(errors).some(Boolean) || Object.keys(entitlementErrors).length > 0;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitted(true);
    if (invalid || readOnly) return;
    setBusy(true); setError('');
    const hasPrice = priceMinor !== null;
    const body = {
      name: name.trim(), description: description.trim() || null,
      list_price_minor: hasPrice ? priceMinor : null, currency: hasPrice ? currencyCode : null, interval: hasPrice ? interval : null,
      entitlements: fromDraft(draft) as Entitlements,
      ...(showStripe ? {external_price_refs: {...(plan?.external_price_refs || {}), stripe: priceIds}} : {}),
    };
    try {
      onSaved(plan
        ? await portal<Plan>(`plans/${encodeURIComponent(plan.code)}`, {method: 'PATCH', body: {version: plan.version, ...body}})
        : await portal<Plan>('plans', {method: 'POST', body: {code: code.trim(), ...body}}));
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  const title = readOnly ? plan?.name || 'Plan' : plan ? 'Edit plan' : 'Create plan';
  return <Dialog open={open} onClose={onClose} title={title} wide>
    <form className="dialog-form" onSubmit={submit} noValidate>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        {plan && !readOnly && <Notice tone="info">This plan applies to {plural(plan.customer_count, 'customer')} and {plural(plan.workspace_count, 'workspace')}. Changes apply within 30 seconds.</Notice>}
        <fieldset className="plain-fieldset" disabled={readOnly}>
          <div className="form-grid">
            <label className="field">Plan code
              <input type="text" value={code} onChange={event => setCode(event.target.value.toUpperCase())} maxLength={16} disabled={!!plan} placeholder="GROWTH" autoFocus={!plan} aria-invalid={submitted && !!errors.code}/>
              {submitted && errors.code ? <span className="field-error">{errors.code}</span> : <span className="field-hint">{plan ? 'You can’t change the code.' : 'Uppercase letters, numbers and underscores. You can’t change it later.'}</span>}
            </label>
            <label className="field">Name
              <input type="text" value={name} onChange={event => setName(event.target.value)} maxLength={60} autoFocus={!!plan && !readOnly} aria-invalid={submitted && !!errors.name}/>
              {submitted && errors.name && <span className="field-error">{errors.name}</span>}
            </label>
            <label className="field full">Description<span className="field-hint">Optional. Shown to operators only.</span><textarea rows={2} value={description} onChange={event => setDescription(event.target.value)} maxLength={300}/></label>
            <label className="field">List price
              <input type="text" inputMode="decimal" value={price} onChange={event => setPrice(event.target.value)} placeholder="1,200.00" aria-invalid={submitted && !!errors.price}/>
              {submitted && errors.price ? <span className="field-error">{errors.price}</span> : <span className="field-hint">Optional. Leave blank for custom pricing.</span>}
            </label>
            <div className="form-grid">
              <label className="field">Currency
                <input type="text" value={currency} onChange={event => setCurrency(event.target.value.toUpperCase())} maxLength={3} aria-invalid={submitted && !!errors.currency}/>
                {submitted && errors.currency && <span className="field-error">{errors.currency}</span>}
              </label>
              <label className="field">Billing interval<select value={interval} onChange={event => setBillingInterval(event.target.value as BillingInterval)}>{INTERVALS.map(value => <option key={value} value={value}>{intervalLabel[value]}</option>)}</select></label>
            </div>
            {showStripe && <label className="field full">Stripe price IDs
              <input type="text" value={stripePrices} onChange={event => setStripePrices(event.target.value)} placeholder="price_..." aria-invalid={submitted && !!errors.stripe}/>
              {submitted && errors.stripe ? <span className="field-error">{errors.stripe}</span> : <span className="field-hint">Optional. Separate IDs with commas. Each price ID can belong to one plan only.</span>}
            </label>}
          </div>
          <h3 className="form-subheading">Entitlements</h3>
          <EntitlementFields draft={draft} onChange={setDraft} errors={entitlementErrors} showErrors={submitted} disabled={readOnly}/>
        </fieldset>
      </div>
      <div className="dialog-actions">
        {readOnly ? <button type="button" className="button primary" onClick={onClose}>Close</button> : <>
          <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={busy}>{busy && <Loader2 className="spin" size={15}/>}{plan ? 'Save changes' : 'Create plan'}</button>
        </>}
      </div>
    </form>
  </Dialog>;
}
