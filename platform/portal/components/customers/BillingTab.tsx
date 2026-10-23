'use client';

import Link from 'next/link';
import {useState} from 'react';
import {Ban, CreditCard, ExternalLink, Layers, Pencil, Plus, Receipt, RefreshCw, SlidersHorizontal, XCircle} from 'lucide-react';
import {portal} from '../../lib/api';
import {formatBillingDate, formatDate, formatMoney, formatPeriod} from '../../lib/format';
import {
  ENTITLEMENT_KEYS, billingProviderLabel, entitlementLabel, entitlementSourceLabel, entitlementValueText, paymentMethodLabel, planName, priceText,
  subscriptionStatusLabel,
} from '../../lib/labels';
import type {Customer, CustomerEntitlements, Payment, Plan, Subscription} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {useSession} from '../SessionProvider';
import {BillingStateBadge, EmptyState, Loading, Notice, PaymentStatusBadge, SectionTitle} from '../ui/shared';
import {BillingOffNotice, plural, ReadOnlyNotice} from '../billing/common';
import {workspaceHref} from '../workspaces/WorkspaceTable';
import {
  CancelSubscriptionDialog, ChangePlanDialog, OverridesDialog, PaymentFormDialog, SubscriptionFormDialog, VoidPaymentDialog,
} from './BillingDialogs';

type BillingData = {
  subscriptions: {current: Subscription | null; items: Subscription[]};
  payments: {items: Payment[]};
  entitlements: CustomerEntitlements;
  plans: Plan[];
};
type Pending = 'create' | 'edit' | 'plan' | 'cancel' | 'overrides' | 'payment' | null;

export function BillingTab({customer, onEditCustomer}: {customer: Customer; onEditCustomer?: () => void}) {
  const {session, canManageBilling} = useSession();
  const [pending, setPending] = useState<Pending>(null);
  const [editingPayment, setEditingPayment] = useState<Payment | null>(null);
  const [voiding, setVoiding] = useState<Payment | null>(null);
  const [message, setMessage] = useState('');
  const path = `customers/${encodeURIComponent(customer.id)}`;
  const {data, error, loading, reload} = useLoad(async () => {
    const [subscriptions, payments, entitlements, plans] = await Promise.all([
      portal<BillingData['subscriptions']>(`${path}/subscriptions`),
      portal<BillingData['payments']>(`${path}/payments`),
      portal<CustomerEntitlements>(`${path}/entitlements`),
      portal<{items: Plan[]}>('plans'),
    ]);
    return {subscriptions, payments, entitlements, plans: plans.items};
  }, [path]);

  if (loading && !data) return <Loading label="Loading billing…"/>;
  if (!data) return <Notice tone="error">{error || 'Something went wrong. If the issue persists, contact Support.'}</Notice>;

  const {subscriptions, payments, entitlements, plans} = data;
  const current = subscriptions.current;
  const editable = canManageBilling && customer.status !== 'deleted';
  const stripe = current?.provider === 'stripe';
  const canceling = !!current && (current.cancel_at_period_end || current.status === 'canceled' || current.status === 'expired');
  const plan = plans.find(item => item.code === current?.plan_code);
  const workspaceCount = entitlements.workspaces.length;
  const history = subscriptions.items.filter(item => item.id !== current?.id);
  const done = (text: string) => {setPending(null); setEditingPayment(null); setVoiding(null); setMessage(text); void reload();};
  const showStripeId = session?.billing_provider === 'stripe' || !!customer.external_customer_refs?.stripe;

  return <>
    <BillingOffNotice/>
    <ReadOnlyNotice/>
    {message && <Notice tone="success">{message}</Notice>}
    {error && <Notice tone="error">{error}</Notice>}
    {entitlements.issuance_blocked && <Notice tone="warning">This customer doesn’t have an active subscription. Create a subscription or record a payment before you issue keys.</Notice>}

    <section className="panel">
      <SectionTitle title="Subscription" action={<div className="section-actions">
        <button type="button" className="button secondary small" onClick={() => void reload()}><RefreshCw size={14}/>Refresh</button>
        {editable && !current && <button type="button" className="button primary small" onClick={() => setPending('create')}><Plus size={14}/>Create subscription</button>}
        {editable && current && <>
          {!stripe && !canceling && <button type="button" className="button secondary small" onClick={() => setPending('plan')}><Layers size={14}/>Change plan</button>}
          <button type="button" className="button secondary small" onClick={() => setPending('edit')}><Pencil size={14}/>Edit</button>
          {!stripe && !canceling && <button type="button" className="button danger-outline small" onClick={() => setPending('cancel')}><XCircle size={14}/>Cancel subscription</button>}
        </>}
      </div>}/>
      {current ? <dl className="detail-list">
        <div><dt>Plan</dt><dd>{current.plan_name || planName(current.plan_code)}</dd></div>
        <div><dt>Status</dt><dd><BillingStateBadge state={entitlements.billing_state} status={current.status}/>{current.status === 'past_due' && <span className="cell-sub">Payment past due</span>}</dd></div>
        <div><dt>Period</dt><dd>{formatPeriod(current.current_period_start, current.current_period_end)}</dd></div>
        <div><dt>Amount</dt><dd>{priceText(current.amount_minor, current.currency, current.interval)}</dd></div>
        <div><dt>Grace period</dt><dd>{plural(current.grace_days, 'day')}</dd></div>
        <div><dt>Provider</dt><dd>{billingProviderLabel[current.provider] || current.provider}{current.external_subscription_ref && <span className="cell-sub"><code>{current.external_subscription_ref}</code></span>}</dd></div>
        {current.cancel_at_period_end && <div><dt>Cancels</dt><dd>At the end of the current period ({formatBillingDate(current.current_period_end)})</dd></div>}
        {current.canceled_at && <div><dt>Canceled</dt><dd>{formatBillingDate(current.canceled_at)}</dd></div>}
        <div><dt>Last updated</dt><dd>{formatDate(current.updated_at)}, by {current.updated_by}</dd></div>
        <div className="full"><dt>Notes</dt><dd>{current.notes || <span className="muted">No notes</span>}</dd></div>
      </dl> : <EmptyState icon={CreditCard} title="No subscription"
        action={editable ? <button type="button" className="button primary" onClick={() => setPending('create')}><Plus size={15}/>Create subscription</button> : undefined}>
        {`This customer’s workspaces use the ${entitlements.plan.name || planName(entitlements.plan.code)} plan until you create a subscription.`}
      </EmptyState>}
      {history.length > 0 && <div className="summary-table-scroll"><table className="summary-table">
        <thead><tr><th>Previous subscriptions</th><th>Period</th><th>Amount</th><th>Status</th></tr></thead>
        <tbody>{history.map(item => <tr key={item.id}>
          <td>{item.plan_name || planName(item.plan_code)}<span className="cell-sub">{billingProviderLabel[item.provider]}</span></td>
          <td>{formatPeriod(item.current_period_start, item.current_period_end)}</td>
          <td>{priceText(item.amount_minor, item.currency, item.interval)}</td>
          <td>{subscriptionStatusLabel[item.status] || item.status}</td>
        </tr>)}</tbody>
      </table></div>}
    </section>

    <section className="panel">
      <SectionTitle title="Payments" action={editable ? <button type="button" className="button primary small" onClick={() => setPending('payment')}><Plus size={14}/>Record payment</button> : undefined}/>
      {!payments.items.length ? <EmptyState icon={Receipt} title="No payments yet">{editable ? 'Record a payment when this customer pays an invoice.' : 'Payments appear here once an operator records them.'}</EmptyState>
        : <div className="summary-table-scroll"><table className="summary-table">
          <thead><tr><th>Reference</th><th>Period</th><th className="number">Amount</th><th>Status</th><th>Paid on</th><th>Method</th><th>Recorded by</th>{editable && <th><span className="sr-only">Actions</span></th>}</tr></thead>
          <tbody>{payments.items.map(payment => <tr key={payment.id}>
            <td><strong>{payment.reference}</strong>{payment.notes && <span className="cell-sub" title={payment.notes}>{payment.notes.length > 60 ? `${payment.notes.slice(0, 60)}…` : payment.notes}</span>}</td>
            <td>{formatPeriod(payment.period_start, payment.period_end)}</td>
            <td className="number">{formatMoney(payment.amount_minor, payment.currency)}</td>
            <td><PaymentStatusBadge status={payment.status}/>{payment.status === 'void' && payment.void_reason && <span className="cell-sub" title={payment.void_reason}>{payment.voided_at ? `${formatDate(payment.voided_at)}${payment.voided_by ? `, by ${payment.voided_by}` : ''}` : 'Voided'}</span>}</td>
            <td>{payment.paid_at ? formatBillingDate(payment.paid_at) : <span className="muted">—</span>}</td>
            <td>{paymentMethodLabel[payment.method] || payment.method}{payment.provider === 'stripe' && <span className="cell-sub">Stripe</span>}</td>
            <td>{formatDate(payment.created_at)}, by {payment.created_by}</td>
            {editable && <td><div className="row-actions">{payment.status !== 'void' && <>
              <button type="button" className="button secondary small" onClick={() => setEditingPayment(payment)} aria-label={`Edit payment ${payment.reference}`}><Pencil size={13}/>Edit</button>
              {payment.provider !== 'stripe' && <button type="button" className="button danger-outline small" onClick={() => setVoiding(payment)} aria-label={`Void payment ${payment.reference}`}><Ban size={13}/>Void</button>}
            </>}</div></td>}
          </tr>)}</tbody>
        </table></div>}
    </section>

    <section className="panel">
      <SectionTitle title="Entitlements" action={editable && current ? <button type="button" className="button secondary small" onClick={() => setPending('overrides')}><SlidersHorizontal size={14}/>Edit overrides</button> : undefined}>
        {`What every workspace of this customer can do on the ${entitlements.plan.name || planName(entitlements.plan.code)} plan.`}
      </SectionTitle>
      <div className="summary-table-scroll"><table className="summary-table">
        <thead><tr><th>Feature</th><th>Value</th><th>Source</th></tr></thead>
        <tbody>{ENTITLEMENT_KEYS.map(key => {
          const item = entitlements.effective[key];
          return <tr key={key}>
            <td>{entitlementLabel[key]}</td>
            <td>{entitlementValueText(key, item?.value)}</td>
            <td>{item ? entitlementSourceLabel[item.source] || item.source : <span className="muted">—</span>}</td>
          </tr>;
        })}</tbody>
      </table></div>
      <div className="panel-footer"><span>{workspaceCount ? <>Applies to {plural(workspaceCount, 'workspace')}: {entitlements.workspaces.map((workspace, index) => <span key={workspace.tenant_id}>
        {index > 0 && ', '}<Link className="text-link" href={workspaceHref(workspace.tenant_id)}>{workspace.name}</Link>
      </span>)}</> : 'This customer has no workspaces yet.'}</span></div>
    </section>

    <section className="panel">
      <SectionTitle title="Billing contact" action={onEditCustomer ? <button type="button" className="button secondary small" onClick={onEditCustomer}><Pencil size={14}/>Edit</button> : undefined}/>
      <dl className="detail-list">
        <div><dt>Billing email</dt><dd>{customer.billing_contact_email || <span className="muted">Not set</span>}</dd></div>
        <div><dt>Manage billing link</dt><dd>{customer.manage_billing_url
          ? <a className="text-link" href={customer.manage_billing_url} target="_blank" rel="noopener noreferrer">{customer.manage_billing_url}<ExternalLink size={12} style={{marginLeft: 4}}/></a>
          : <span className="muted">Uses the platform default</span>}</dd></div>
        {showStripeId && <div><dt>Stripe customer ID</dt><dd>{customer.external_customer_refs?.stripe ? <code>{customer.external_customer_refs.stripe}</code> : <span className="muted">Not set</span>}</dd></div>}
      </dl>
    </section>

    <SubscriptionFormDialog open={pending === 'create'} customer={customer} plans={plans} onClose={() => setPending(null)} onSaved={() => done('Subscription created. Changes apply within 30 seconds.')}/>
    <SubscriptionFormDialog open={pending === 'edit' && !!current} customer={customer} subscription={current} plans={plans} onClose={() => setPending(null)} onSaved={() => done('Subscription updated.')}/>
    <ChangePlanDialog subscription={pending === 'plan' ? current : null} plans={plans} workspaceCount={workspaceCount} onClose={() => setPending(null)}
      onSaved={updated => done(`Plan changed to ${updated.plan_name || planName(updated.plan_code)}. Changes apply within 30 seconds.`)}/>
    <CancelSubscriptionDialog subscription={pending === 'cancel' ? current : null} onClose={() => setPending(null)}
      onSaved={updated => done(updated.cancel_at_period_end ? `Subscription cancels on ${formatBillingDate(updated.current_period_end)}.` : 'Subscription canceled.')}/>
    <OverridesDialog subscription={pending === 'overrides' ? current : null} planEntitlements={plan?.entitlements} onClose={() => setPending(null)} onSaved={() => done('Overrides saved. Changes apply within 30 seconds.')}/>
    <PaymentFormDialog open={pending === 'payment'} customer={customer} subscription={current} onClose={() => setPending(null)}
      onSaved={payment => done(`Payment ${payment.reference} recorded.`)}/>
    <PaymentFormDialog open={!!editingPayment} customer={customer} subscription={current} payment={editingPayment} onClose={() => setEditingPayment(null)}
      onSaved={payment => done(`Payment ${payment.reference} updated.`)}/>
    <VoidPaymentDialog payment={voiding} onClose={() => setVoiding(null)} onSaved={payment => done(`Payment ${payment.reference} voided.`)}/>
  </>;
}
