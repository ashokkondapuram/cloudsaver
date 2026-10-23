'use client';

import {useEffect, useState} from 'react';
import {Loader2} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import {
  addDays, addMonths, billingDay, containsCardNumber, dayToTimestamp, formatBillingDate, formatMoney, isCurrencyCode, moneyInput,
  parseMoney, toDateInput,
} from '../../lib/format';
import {INTERVALS, PAYMENT_METHODS, intervalLabel, paymentMethodLabel, paymentStatusLabel, planName, subscriptionStatusLabel} from '../../lib/labels';
import type {
  BillingInterval, Customer, EntitlementKey, Entitlements, Payment, PaymentMethod, PaymentStatus, Plan, Subscription, SubscriptionStatus,
} from '../../lib/types';
import {Dialog} from '../ui/Dialog';
import {Notice} from '../ui/shared';
import {draftErrors, EntitlementFields, fromDraft, toDraft, type EntitlementDraft} from '../billing/EntitlementFields';

const CARD_ERROR = 'Remove the card number. Use the invoice or remittance reference instead.';
const DEFAULT_CURRENCY = 'USD';

function today() {
  return toDateInput(new Date());
}

/** Default end of a period that starts on `start` ("YYYY-MM-DD"). */
function periodEnd(start: string, interval: BillingInterval) {
  const [year, month, day] = start.split('-').map(Number);
  const from = new Date(year, month - 1, day);
  return toDateInput(interval === 'year' ? addMonths(from, 12) : interval === 'month' ? addMonths(from, 1) : addDays(from, 30));
}

function Field({label, error, hint, children, className = ''}: {label: string; error?: string; hint?: string; children: React.ReactNode; className?: string}) {
  return <label className={`field ${className}`}>{label}{children}{error ? <span className="field-error">{error}</span> : hint ? <span className="field-hint">{hint}</span> : null}</label>;
}

function DialogButtons({busy, label, onClose, disabled}: {busy: boolean; label: string; onClose: () => void; disabled?: boolean}) {
  return <div className="dialog-actions">
    <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
    <button type="submit" className="button primary" disabled={busy || disabled}>{busy && <Loader2 className="spin" size={15}/>}{label}</button>
  </div>;
}

function useSubmit() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('');
    try {await action();} catch (cause) {setError(errorMessage(cause));} finally {setBusy(false);}
  }
  return {busy, error, setError, run};
}

const EDITABLE_STATUSES: SubscriptionStatus[] = ['trialing', 'active', 'past_due'];

/** Creates the customer's subscription, or edits terms of the current one. Stripe subscriptions allow notes only. */
export function SubscriptionFormDialog({open, customer, subscription, plans, defaultGraceDays, onClose, onSaved}: {
  open: boolean; customer: Customer; subscription?: Subscription | null; plans: Plan[]; defaultGraceDays?: number;
  onClose: () => void; onSaved: (subscription: Subscription) => void;
}) {
  const [planCode, setPlanCode] = useState('');
  const [status, setStatus] = useState<SubscriptionStatus>('active');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState(DEFAULT_CURRENCY);
  const [interval, setBillingInterval] = useState<BillingInterval>('month');
  const [grace, setGrace] = useState('');
  const [notes, setNotes] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const {busy, error, setError, run} = useSubmit();
  const activePlans = plans.filter(plan => plan.status === 'active');
  const stripe = subscription?.provider === 'stripe';

  function applyPlan(code: string) {
    setPlanCode(code);
    const plan = plans.find(item => item.code === code);
    if (!plan) return;
    if (plan.currency) setCurrency(plan.currency);
    setAmount(moneyInput(plan.list_price_minor ?? 0, plan.currency || currency));
    if (plan.interval) {setBillingInterval(plan.interval); if (start) setEnd(periodEnd(start, plan.interval));}
  }

  useEffect(() => {
    if (!open) return;
    setSubmitted(false); setError('');
    if (subscription) {
      setPlanCode(subscription.plan_code); setStatus(subscription.status);
      setStart(billingDay(subscription.current_period_start)); setEnd(billingDay(subscription.current_period_end));
      setCurrency(subscription.currency); setAmount(moneyInput(subscription.amount_minor, subscription.currency));
      setBillingInterval(subscription.interval); setGrace(String(subscription.grace_days)); setNotes(subscription.notes || '');
      return;
    }
    const first = activePlans[0];
    const from = today();
    setStatus('active'); setStart(from); setGrace(''); setNotes('');
    setCurrency(first?.currency || DEFAULT_CURRENCY); setAmount(moneyInput(first?.list_price_minor ?? 0, first?.currency || DEFAULT_CURRENCY));
    setBillingInterval(first?.interval || 'month'); setEnd(periodEnd(from, first?.interval || 'month')); setPlanCode(first?.code || '');
  }, [open, subscription]);

  const currencyCode = currency.trim().toUpperCase();
  const amountMinor = parseMoney(amount, currencyCode);
  const graceDays = grace.trim() === '' ? null : Number(grace);
  const errors = {
    plan: !planCode ? 'Select a plan.' : '',
    start: !start ? 'Choose a start date.' : '',
    end: !end ? 'Choose an end date.' : end <= start ? 'Choose an end date after the start date.' : '',
    amount: amountMinor === null ? 'Enter an amount, such as 1,200.00. Use 0 for a free plan.' : '',
    currency: !isCurrencyCode(currencyCode) ? 'Enter a 3-letter currency code, such as USD.' : '',
    grace: graceDays !== null && (!/^\d+$/.test(grace.trim()) || graceDays > 60) ? 'Enter a whole number of days from 0 to 60.' : '',
    notes: containsCardNumber(notes) ? CARD_ERROR : '',
  };
  const invalid = stripe ? !!errors.notes : Object.values(errors).some(Boolean);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitted(true);
    if (invalid) return;
    await run(async () => {
      if (subscription) {
        const body: Record<string, unknown> = {version: subscription.version};
        if ((notes.trim() || null) !== (subscription.notes || null)) body.notes = notes.trim() || null;
        if (!stripe) {
          if (status !== subscription.status) body.status = status;
          if (start !== billingDay(subscription.current_period_start)) body.current_period_start = dayToTimestamp(start);
          if (end !== billingDay(subscription.current_period_end)) body.current_period_end = dayToTimestamp(end);
          if (amountMinor !== subscription.amount_minor) body.amount_minor = amountMinor;
          if (currencyCode !== subscription.currency) body.currency = currencyCode;
          if (interval !== subscription.interval) body.interval = interval;
          if (graceDays !== null && graceDays !== subscription.grace_days) body.grace_days = graceDays;
        }
        onSaved(await portal<Subscription>(`subscriptions/${encodeURIComponent(subscription.id)}`, {method: 'PATCH', body}));
      } else {
        onSaved(await portal<Subscription>(`customers/${encodeURIComponent(customer.id)}/subscriptions`, {method: 'POST', body: {
          plan_code: planCode, status, current_period_start: dayToTimestamp(start), current_period_end: dayToTimestamp(end),
          amount_minor: amountMinor, currency: currencyCode, interval, ...(graceDays !== null ? {grace_days: graceDays} : {}),
          ...(notes.trim() ? {notes: notes.trim()} : {}),
        }}));
      }
    });
  }

  const show = (key: keyof typeof errors) => (submitted ? errors[key] : '');
  const statuses = subscription && !EDITABLE_STATUSES.includes(subscription.status) ? [subscription.status, ...EDITABLE_STATUSES] : subscription ? EDITABLE_STATUSES : (['trialing', 'active'] as SubscriptionStatus[]);
  return <Dialog open={open} onClose={onClose} title={subscription ? 'Edit subscription' : 'Create subscription'} wide>
    <form className="dialog-form" onSubmit={submit} noValidate>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        {stripe && <Notice tone="info">Stripe manages this subscription. You can change notes here, and entitlement overrides from the Entitlements section.</Notice>}
        {!subscription && !activePlans.length && <Notice tone="warning">There are no active plans. Create a plan on the Plans page first.</Notice>}
        <fieldset className="plain-fieldset" disabled={stripe}>
          <div className="form-grid">
            {subscription ? <Field label="Plan" hint="To change the plan, use Change plan."><input type="text" value={subscription.plan_name || planName(subscription.plan_code)} disabled/></Field>
              : <Field label="Plan" error={show('plan')}><select value={planCode} onChange={event => applyPlan(event.target.value)}>
                {activePlans.map(plan => <option key={plan.code} value={plan.code}>{plan.name}</option>)}
              </select></Field>}
            <Field label="Status"><select value={status} onChange={event => setStatus(event.target.value as SubscriptionStatus)}>
              {statuses.map(value => <option key={value} value={value}>{subscriptionStatusLabel[value]}</option>)}
            </select></Field>
            <Field label="Period start" error={show('start')}><input type="date" value={start} onChange={event => {setStart(event.target.value); if (!subscription && event.target.value) setEnd(periodEnd(event.target.value, interval));}}/></Field>
            <Field label="Period end" error={show('end')} hint="The subscription renews on this date."><input type="date" value={end} min={start || undefined} onChange={event => setEnd(event.target.value)}/></Field>
            <Field label="Amount" error={show('amount')}><input type="text" inputMode="decimal" value={amount} onChange={event => setAmount(event.target.value)} placeholder="1,200.00"/></Field>
            <div className="form-grid">
              <Field label="Currency" error={show('currency')}><input type="text" value={currency} onChange={event => setCurrency(event.target.value.toUpperCase())} maxLength={3}/></Field>
              <Field label="Billing interval"><select value={interval} onChange={event => setBillingInterval(event.target.value as BillingInterval)}>
                {INTERVALS.map(value => <option key={value} value={value}>{intervalLabel[value]}</option>)}
              </select></Field>
            </div>
            <Field label="Grace period (days)" error={show('grace')} hint={subscription ? 'From 0 to 60 days after the period ends.' : `Optional. Leave blank to use the platform default${defaultGraceDays !== undefined ? ` (${defaultGraceDays} days)` : ''}.`}>
              <input type="number" inputMode="numeric" min={0} max={60} step={1} value={grace} onChange={event => setGrace(event.target.value)}/>
            </Field>
          </div>
        </fieldset>
        <Field label="Notes" error={show('notes')} hint="Optional. Only platform operators and auditors can see notes."><textarea rows={3} value={notes} onChange={event => setNotes(event.target.value)} maxLength={500}/></Field>
      </div>
      <DialogButtons busy={busy} disabled={!subscription && !activePlans.length} label={subscription ? 'Save changes' : 'Create subscription'} onClose={onClose}/>
    </form>
  </Dialog>;
}

export function ChangePlanDialog({subscription, plans, workspaceCount, onClose, onSaved}: {
  subscription: Subscription | null; plans: Plan[]; workspaceCount: number; onClose: () => void; onSaved: (subscription: Subscription) => void;
}) {
  const [planCode, setPlanCode] = useState('');
  const {busy, error, setError, run} = useSubmit();
  useEffect(() => {if (subscription) {setPlanCode(''); setError('');}}, [subscription]);
  if (!subscription) return null;
  const options = plans.filter(plan => plan.status === 'active' && plan.code !== subscription.plan_code);
  const target = plans.find(plan => plan.code === planCode);
  const from = subscription.plan_name || planName(subscription.plan_code);
  const preview = !target ? '' : workspaceCount === 0
    ? `This customer has no workspaces yet. Workspaces you create later use ${target.name}.`
    : `${workspaceCount.toLocaleString('en-US')} ${workspaceCount === 1 ? 'workspace moves' : 'workspaces move'} from ${from} to ${target.name}. Changes apply within 30 seconds.`;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!subscription || !planCode) return;
    await run(async () => {
      onSaved(await portal<Subscription>(`subscriptions/${encodeURIComponent(subscription.id)}`, {method: 'PATCH', body: {version: subscription.version, plan_code: planCode}}));
    });
  }

  return <Dialog open onClose={onClose} title="Change plan">
    <form className="dialog-form" onSubmit={submit}>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        <p>Current plan: <strong>{from}</strong>. The amount and period stay the same. To change them, edit the subscription.</p>
        <Field label="New plan"><select value={planCode} onChange={event => setPlanCode(event.target.value)} required autoFocus>
          <option value="">Select a plan</option>
          {options.map(plan => <option key={plan.code} value={plan.code}>{plan.name}</option>)}
        </select></Field>
        {preview && <Notice tone="info">{preview}</Notice>}
      </div>
      <div className="dialog-actions">
        <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
        <button type="submit" className="button primary" disabled={busy || !planCode}>{busy && <Loader2 className="spin" size={15}/>}Change plan</button>
      </div>
    </form>
  </Dialog>;
}

export function CancelSubscriptionDialog({subscription, onClose, onSaved}: {subscription: Subscription | null; onClose: () => void; onSaved: (subscription: Subscription) => void}) {
  const [atPeriodEnd, setAtPeriodEnd] = useState(true);
  const [reason, setReason] = useState('');
  const {busy, error, setError, run} = useSubmit();
  useEffect(() => {if (subscription) {setAtPeriodEnd(true); setReason(''); setError('');}}, [subscription]);
  if (!subscription) return null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!subscription || !reason.trim()) return;
    if (containsCardNumber(reason)) {setError(CARD_ERROR); return;}
    await run(async () => {
      onSaved(await portal<Subscription>(`subscriptions/${encodeURIComponent(subscription.id)}/cancel`, {method: 'POST', body: {version: subscription.version, at_period_end: atPeriodEnd, reason: reason.trim()}}));
    });
  }

  const end = formatBillingDate(subscription.current_period_end);
  return <Dialog open onClose={onClose} title="Cancel this subscription?">
    <form className="dialog-form" onSubmit={submit}>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        <fieldset className="choice-group">
          <legend>When</legend>
          <div className="radio-row">
            <label className={atPeriodEnd ? 'chosen' : ''}><input type="radio" name="cancel-when" checked={atPeriodEnd} onChange={() => setAtPeriodEnd(true)}/>At the end of the current period</label>
            <label className={!atPeriodEnd ? 'chosen' : ''}><input type="radio" name="cancel-when" checked={!atPeriodEnd} onChange={() => setAtPeriodEnd(false)}/>Now</label>
          </div>
          <span className="field-hint">{atPeriodEnd
            ? `The customer keeps the ${subscription.plan_name || planName(subscription.plan_code)} plan until ${end}.`
            : 'The subscription ends right away, and the customer’s workspaces move to the lapsed plan or are suspended, based on your billing settings.'}</span>
        </fieldset>
        <Field label="Reason" hint="Recorded in the activity log."><textarea rows={3} value={reason} onChange={event => setReason(event.target.value)} maxLength={500} placeholder="For example, the customer chose not to renew" required/></Field>
      </div>
      <div className="dialog-actions">
        <button type="button" className="button secondary" onClick={onClose}>Close</button>
        <button type="submit" className="button danger" disabled={busy || !reason.trim()}>{busy && <Loader2 className="spin" size={15}/>}Cancel subscription</button>
      </div>
    </form>
  </Dialog>;
}

const NEW_PAYMENT_STATUSES: PaymentStatus[] = ['paid', 'pending', 'failed'];
const NEXT_STATUSES: Partial<Record<PaymentStatus, PaymentStatus[]>> = {pending: ['pending', 'paid', 'failed'], paid: ['paid', 'refunded']};

/** Records a payment, or edits status, dates and notes of an existing one. */
export function PaymentFormDialog({open, customer, subscription, payment, onClose, onSaved}: {
  open: boolean; customer: Customer; subscription: Subscription | null; payment?: Payment | null; onClose: () => void; onSaved: (payment: Payment) => void;
}) {
  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState(DEFAULT_CURRENCY);
  const [periodStart, setPeriodStart] = useState('');
  const [periodEndDay, setPeriodEnd] = useState('');
  const [reference, setReference] = useState('');
  const [invoiceDate, setInvoiceDate] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [status, setStatus] = useState<PaymentStatus>('paid');
  const [paidOn, setPaidOn] = useState('');
  const [method, setMethod] = useState<PaymentMethod>('bank_transfer');
  const [notes, setNotes] = useState('');
  const [extend, setExtend] = useState(true);
  const [submitted, setSubmitted] = useState(false);
  const {busy, error, setError, run} = useSubmit();
  const stripe = payment?.provider === 'stripe';

  useEffect(() => {
    if (!open) return;
    setSubmitted(false); setError('');
    if (payment) {
      setAmount(moneyInput(payment.amount_minor, payment.currency)); setCurrency(payment.currency);
      setPeriodStart(payment.period_start); setPeriodEnd(payment.period_end); setReference(payment.reference);
      setInvoiceDate(payment.invoice_date || ''); setDueDate(payment.due_date || ''); setStatus(payment.status);
      setPaidOn(billingDay(payment.paid_at) || (payment.status === 'pending' ? today() : '')); setMethod(payment.method); setNotes(payment.notes || ''); setExtend(false);
      return;
    }
    const start = billingDay(subscription?.current_period_end) || today();
    setCurrency(subscription?.currency || DEFAULT_CURRENCY); setAmount(subscription && subscription.amount_minor > 0 ? moneyInput(subscription.amount_minor, subscription.currency) : '');
    setPeriodStart(start); setPeriodEnd(periodEnd(start, subscription?.interval || 'month'));
    setReference(''); setInvoiceDate(''); setDueDate(''); setStatus('paid'); setPaidOn(today()); setMethod('bank_transfer'); setNotes('');
    setExtend(!!subscription);
  }, [open, payment, subscription]);

  function changeStatus(next: PaymentStatus) {
    setStatus(next);
    if (!payment) setExtend(next === 'paid' && !!subscription);
    else setExtend(next === 'paid' && payment.status !== 'paid' && !!payment.subscription_id);
  }

  const currencyCode = currency.trim().toUpperCase();
  const amountMinor = parseMoney(amount, currencyCode);
  const errors = {
    amount: amountMinor === null || amountMinor <= 0 ? 'Enter an amount greater than 0, such as 1,200.00.' : '',
    currency: !isCurrencyCode(currencyCode) ? 'Enter a 3-letter currency code, such as USD.' : '',
    reference: !reference.trim() ? 'Enter the invoice or remittance reference.' : containsCardNumber(reference) ? CARD_ERROR : '',
    periodStart: !periodStart ? 'Choose a start date.' : '',
    periodEnd: !periodEndDay ? 'Choose an end date.' : periodEndDay < periodStart ? 'Choose an end date on or after the start date.' : '',
    paidOn: status === 'paid' && !paidOn ? 'Choose the date the payment was received.' : '',
    dueDate: dueDate && invoiceDate && dueDate < invoiceDate ? 'Choose a due date on or after the invoice date.' : '',
    notes: containsCardNumber(notes) ? CARD_ERROR : '',
  };
  const invalid = payment
    ? !!(errors.paidOn || errors.dueDate || errors.notes)
    : Object.values(errors).some(Boolean);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitted(true);
    if (invalid) return;
    const paidAt = status === 'paid' && paidOn ? dayToTimestamp(paidOn) : null;
    await run(async () => {
      if (payment) {
        const body: Record<string, unknown> = {version: payment.version};
        if ((notes.trim() || null) !== (payment.notes || null)) body.notes = notes.trim() || null;
        if (!stripe) {
          if (status !== payment.status) body.status = status;
          if (status === 'paid' && paidOn !== billingDay(payment.paid_at)) body.paid_at = paidAt;
          if ((invoiceDate || null) !== payment.invoice_date) body.invoice_date = invoiceDate || null;
          if ((dueDate || null) !== payment.due_date) body.due_date = dueDate || null;
          if (status === 'paid' && payment.status !== 'paid' && payment.subscription_id) body.extend_period = extend;
        }
        onSaved(await portal<Payment>(`payments/${encodeURIComponent(payment.id)}`, {method: 'PATCH', body}));
      } else {
        onSaved(await portal<Payment>(`customers/${encodeURIComponent(customer.id)}/payments`, {method: 'POST', body: {
          ...(subscription ? {subscription_id: subscription.id} : {}),
          amount_minor: amountMinor, currency: currencyCode, status, method, reference: reference.trim(),
          ...(invoiceDate ? {invoice_date: invoiceDate} : {}), ...(dueDate ? {due_date: dueDate} : {}), ...(paidAt ? {paid_at: paidAt} : {}),
          period_start: periodStart, period_end: periodEndDay, ...(notes.trim() ? {notes: notes.trim()} : {}),
          extend_period: status === 'paid' && !!subscription && extend,
        }}));
      }
    });
  }

  const show = (key: keyof typeof errors) => (submitted ? errors[key] : '');
  const statuses = payment ? NEXT_STATUSES[payment.status] || [payment.status] : NEW_PAYMENT_STATUSES;
  const canExtend = status === 'paid' && (payment ? payment.status !== 'paid' && !!payment.subscription_id : !!subscription);
  return <Dialog open={open} onClose={onClose} title={payment ? 'Edit payment' : 'Record payment'} wide>
    <form className="dialog-form" onSubmit={submit} noValidate>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        {stripe && <Notice tone="info">Stripe recorded this payment. You can change its notes only.</Notice>}
        {!payment && !subscription && <Notice tone="warning">This customer doesn’t have a subscription, so this payment won’t extend a billing period. Create a subscription first if you want it to.</Notice>}
        <div className="form-grid">
          <Field label="Amount" error={show('amount')}><input type="text" inputMode="decimal" value={amount} onChange={event => setAmount(event.target.value)} placeholder="1,200.00" disabled={!!payment} autoFocus={!payment}/></Field>
          <Field label="Currency" error={show('currency')}><input type="text" value={currency} onChange={event => setCurrency(event.target.value.toUpperCase())} maxLength={3} disabled={!!payment}/></Field>
          <Field label="Billing period start" error={show('periodStart')}><input type="date" value={periodStart} onChange={event => setPeriodStart(event.target.value)} disabled={!!payment}/></Field>
          <Field label="Billing period end" error={show('periodEnd')}><input type="date" value={periodEndDay} min={periodStart || undefined} onChange={event => setPeriodEnd(event.target.value)} disabled={!!payment}/></Field>
          <Field label="Invoice or reference" className="full" error={show('reference')} hint="Don't enter card numbers. Use the invoice or remittance reference.">
            <input type="text" value={reference} onChange={event => setReference(event.target.value)} maxLength={80} placeholder="INV-1042" disabled={!!payment} autoComplete="off"/>
          </Field>
          <fieldset className="plain-fieldset full" disabled={stripe}>
            <div className="form-grid">
              <Field label="Invoice date"><input type="date" value={invoiceDate} onChange={event => setInvoiceDate(event.target.value)}/></Field>
              <Field label="Due date" error={show('dueDate')}><input type="date" value={dueDate} min={invoiceDate || undefined} onChange={event => setDueDate(event.target.value)}/></Field>
              <Field label="Status"><select value={status} onChange={event => changeStatus(event.target.value as PaymentStatus)} disabled={statuses.length < 2}>
                {statuses.map(value => <option key={value} value={value}>{paymentStatusLabel[value]}</option>)}
              </select></Field>
              <Field label="Paid on" error={show('paidOn')} hint={status === 'paid' ? 'Required for paid payments.' : undefined}><input type="date" value={status === 'paid' ? paidOn : ''} onChange={event => setPaidOn(event.target.value)} disabled={status !== 'paid'}/></Field>
              <Field label="Method"><select value={method} onChange={event => setMethod(event.target.value as PaymentMethod)} disabled={!!payment}>
                {PAYMENT_METHODS.map(value => <option key={value} value={value}>{paymentMethodLabel[value]}</option>)}
              </select></Field>
            </div>
          </fieldset>
        </div>
        <Field label="Notes" error={show('notes')} hint="Optional. Don't enter card numbers."><textarea rows={3} value={notes} onChange={event => setNotes(event.target.value)} maxLength={500}/></Field>
        {canExtend && !stripe && <label className="checkbox-row top"><input type="checkbox" checked={extend} onChange={event => setExtend(event.target.checked)}/>
          <span>Extend subscription to the end of this period<span className="field-hint" style={{display: 'block'}}>The subscription renews on {formatBillingDate(periodEndDay)} unless it already runs later.</span></span>
        </label>}
      </div>
      <DialogButtons busy={busy} label={payment ? 'Save changes' : 'Record payment'} onClose={onClose}/>
    </form>
  </Dialog>;
}

export function VoidPaymentDialog({payment, onClose, onSaved}: {payment: Payment | null; onClose: () => void; onSaved: (payment: Payment) => void}) {
  const [reason, setReason] = useState('');
  const {busy, error, setError, run} = useSubmit();
  useEffect(() => {if (payment) {setReason(''); setError('');}}, [payment]);
  if (!payment) return null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!payment || !reason.trim()) return;
    if (containsCardNumber(reason)) {setError(CARD_ERROR); return;}
    await run(async () => {
      onSaved(await portal<Payment>(`payments/${encodeURIComponent(payment.id)}/void`, {method: 'POST', body: {version: payment.version, reason: reason.trim()}}));
    });
  }

  return <Dialog open onClose={onClose} title="Void this payment?">
    <form className="dialog-form" onSubmit={submit}>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        <p><strong>{payment.reference}</strong> · {formatMoney(payment.amount_minor, payment.currency)}</p>
        <p>Voided payments stay in the history and no longer extend the subscription.</p>
        <Field label="Reason" hint="Recorded in the activity log."><textarea rows={3} value={reason} onChange={event => setReason(event.target.value)} maxLength={500} placeholder="For example, recorded against the wrong customer" required autoFocus/></Field>
      </div>
      <div className="dialog-actions">
        <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
        <button type="submit" className="button danger" disabled={busy || !reason.trim()}>{busy && <Loader2 className="spin" size={15}/>}Void payment</button>
      </div>
    </form>
  </Dialog>;
}

/** Edits per-customer entitlement overrides on top of the subscription's plan. */
export function OverridesDialog({subscription, planEntitlements, onClose, onSaved}: {
  subscription: Subscription | null; planEntitlements: Entitlements | undefined; onClose: () => void; onSaved: (subscription: Subscription) => void;
}) {
  const [selected, setSelected] = useState<EntitlementKey[]>([]);
  const [draft, setDraft] = useState<EntitlementDraft>(() => toDraft({}));
  const [submitted, setSubmitted] = useState(false);
  const {busy, error, setError, run} = useSubmit();
  useEffect(() => {
    if (!subscription) return;
    const overrides = subscription.entitlement_overrides || {};
    setSelected(Object.keys(overrides) as EntitlementKey[]);
    setDraft(toDraft(overrides, planEntitlements)); setSubmitted(false); setError('');
  }, [subscription]);
  if (!subscription) return null;
  const errors = draftErrors(draft, selected);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!subscription) return;
    setSubmitted(true);
    if (Object.keys(errors).length) return;
    await run(async () => {
      onSaved(await portal<Subscription>(`subscriptions/${encodeURIComponent(subscription.id)}`, {method: 'PATCH', body: {
        version: subscription.version, entitlement_overrides: selected.length ? fromDraft(draft, selected) : null,
      }}));
    });
  }

  const toggleKey = (key: EntitlementKey) => setSelected(current => current.includes(key) ? current.filter(item => item !== key) : [...current, key]);
  return <Dialog open onClose={onClose} title="Edit overrides" wide>
    <form className="dialog-form" onSubmit={submit} noValidate>
      <div className="dialog-content">
        {error && <Notice tone="error">{error}</Notice>}
        <p>Overrides replace plan values for every workspace of this customer. Changes apply within 30 seconds.</p>
        <EntitlementFields draft={draft} onChange={setDraft} errors={errors} showErrors={submitted} planValues={planEntitlements} overrides={{selected, onToggle: toggleKey}}/>
      </div>
      <DialogButtons busy={busy} label="Save changes" onClose={onClose}/>
    </form>
  </Dialog>;
}
