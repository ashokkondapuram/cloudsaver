'use client';

import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {useState} from 'react';
import {CreditCard, Loader2, RefreshCw} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import {formatBillingDate, formatMoney} from '../../lib/format';
import {BILLING_STATES, billingStateLabel, priceText} from '../../lib/labels';
import type {BillingRow, Page, Plan} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {EmptyState, Loading, Notice, PageHeading, BillingStateBadge} from '../ui/shared';
import {BillingOffNotice, customerBillingHref} from './common';

export function BillingList() {
  const router = useRouter();
  const [state, setState] = useState('');
  const [plan, setPlan] = useState('');
  const [renewsBefore, setRenewsBefore] = useState('');
  const [more, setMore] = useState(false);
  const [moreError, setMoreError] = useState('');
  const query = {billing_state: state, plan, renews_before: renewsBefore, limit: 50};
  const {data, setData, error, loading, reload} = useLoad(() => portal<Page<BillingRow>>('billing/customers', {query}), [state, plan, renewsBefore]);
  const {data: plans} = useLoad(() => portal<{items: Plan[]}>('plans'), []);

  async function loadMore() {
    if (!data?.next_cursor) return;
    setMore(true); setMoreError('');
    try {
      const page = await portal<Page<BillingRow>>('billing/customers', {query: {...query, cursor: data.next_cursor}});
      setData({items: [...data.items, ...page.items], next_cursor: page.next_cursor});
    } catch (cause) {setMoreError(errorMessage(cause));} finally {setMore(false);}
  }

  const rows = data?.items || [];
  const mixed = new Set(rows.flatMap(row => [row.currency, row.last_payment?.currency]).filter(Boolean)).size > 1;
  const filtered = !!(state || plan || renewsBefore);
  return <>
    <PageHeading eyebrow="BILLING" title="Billing" actions={<button type="button" className="button secondary" onClick={() => void reload()}><RefreshCw size={15}/>Refresh</button>}>
      Subscriptions and payments for every customer. Each customer’s plan applies to all of its workspaces.
    </PageHeading>
    <BillingOffNotice/>
    <section className="panel">
      <div className="section-title"><div><h2>All customers</h2></div></div>
      <div className="filter-bar">
        <label className="field">Status<select value={state} onChange={event => setState(event.target.value)}>
          <option value="">All statuses</option>{BILLING_STATES.map(value => <option key={value} value={value}>{billingStateLabel[value]}</option>)}
        </select></label>
        <label className="field">Plan<select value={plan} onChange={event => setPlan(event.target.value)}>
          <option value="">All plans</option>{(plans?.items || []).map(item => <option key={item.code} value={item.code}>{item.name}</option>)}
        </select></label>
        <label className="field">Renews before<input type="date" value={renewsBefore} onChange={event => setRenewsBefore(event.target.value)}/></label>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {loading && !data ? <Loading label="Loading billing…"/> : !rows.length ? (!error && <EmptyState icon={CreditCard} title={filtered ? 'No matching customers' : 'No customers yet'}>
        {filtered ? 'Try a different status, plan or date.' : 'Customers appear here once you create them.'}
      </EmptyState>) : <>
        <div className="summary-table-scroll"><table className="summary-table">
          <thead><tr><th>Customer</th><th>Plan</th><th>Status</th><th>Renews</th><th>Last payment</th><th>Amount</th></tr></thead>
          <tbody>{rows.map(row => <tr key={row.customer_id} className="clickable" onClick={() => router.push(customerBillingHref(row.customer_id))}>
            <td><Link className="table-link" href={customerBillingHref(row.customer_id)} onClick={event => event.stopPropagation()}>{row.customer_name}</Link></td>
            <td>{row.plan_name || row.plan_code}</td>
            <td><BillingStateBadge state={row.billing_state} status={row.subscription_status}/></td>
            <td>{row.current_period_end ? formatBillingDate(row.current_period_end) : <span className="muted">—</span>}</td>
            <td>{row.last_payment ? <>{formatBillingDate(row.last_payment.paid_at)}<span className="cell-sub">{row.last_payment.reference} · {formatMoney(row.last_payment.amount_minor, row.last_payment.currency, {code: mixed})}</span></> : <span className="muted">None</span>}</td>
            <td>{row.amount_minor === null ? <span className="muted">—</span> : priceText(row.amount_minor, row.currency, row.interval, {code: mixed})}</td>
          </tr>)}</tbody>
        </table></div>
        {moreError && <Notice tone="error">{moreError}</Notice>}
        {data?.next_cursor && <div className="load-more"><button type="button" className="button secondary" disabled={more} onClick={() => void loadMore()}>{more && <Loader2 className="spin" size={15}/>}Load more</button></div>}
      </>}
    </section>
  </>;
}
