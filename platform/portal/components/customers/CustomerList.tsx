'use client';

import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {useEffect, useState} from 'react';
import {Building2, Loader2, Plus, RefreshCw, Search} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import {formatDate, formatNumber} from '../../lib/format';
import {STATUSES, statusLabel} from '../../lib/labels';
import type {Customer, Page} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {useSession} from '../SessionProvider';
import {EmptyState, Loading, Notice, PageHeading, StatusBadge} from '../ui/shared';
import {CustomerFormDialog} from './CustomerDialogs';

export function useDebounced<T>(value: T, delay = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {const timer = setTimeout(() => setDebounced(value), delay); return () => clearTimeout(timer);}, [value, delay]);
  return debounced;
}

export function CustomerList() {
  const router = useRouter();
  const {canWrite} = useSession();
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [creating, setCreating] = useState(false);
  const [more, setMore] = useState(false);
  const [moreError, setMoreError] = useState('');
  const q = useDebounced(query.trim());
  const {data, setData, error, loading, reload} = useLoad(() => portal<Page<Customer>>('customers', {query: {q, status, limit: 50}}), [q, status]);

  async function loadMore() {
    if (!data?.next_cursor) return;
    setMore(true); setMoreError('');
    try {
      const page = await portal<Page<Customer>>('customers', {query: {q, status, limit: 50, cursor: data.next_cursor}});
      setData({items: [...data.items, ...page.items], next_cursor: page.next_cursor});
    } catch (cause) {setMoreError(errorMessage(cause));} finally {setMore(false);}
  }

  return <>
    <PageHeading eyebrow="DIRECTORY" title="Customers" actions={<>
      <button type="button" className="button secondary" onClick={() => void reload()}><RefreshCw size={15}/>Refresh</button>
      {canWrite && <button type="button" className="button primary" onClick={() => setCreating(true)}><Plus size={15}/>Create customer</button>}
    </>}>Each customer owns one or more workspaces.</PageHeading>
    <section className="panel">
      <div className="section-title"><div><h2>All customers</h2></div></div>
      <div className="filter-bar">
        <label className="field grow">Search<span className="search-input"><Search size={15}/><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search by customer name"/></span></label>
        <label className="field">Status<select value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option>{STATUSES.map(value => <option key={value} value={value}>{statusLabel[value]}</option>)}</select></label>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {loading && !data ? <Loading label="Loading customers…"/> : !data?.items.length ? (
        !error && <EmptyState icon={Building2} title={q || status ? 'No matching customers' : 'No customers yet'} action={canWrite && !q && !status ? <button type="button" className="button primary" onClick={() => setCreating(true)}><Plus size={15}/>Create customer</button> : undefined}>
          {q || status ? 'Try a different search or status.' : 'Create a customer to start adding workspaces.'}
        </EmptyState>
      ) : <>
        <div className="summary-table-scroll"><table className="summary-table">
          <thead><tr><th>Customer</th><th>Status</th><th className="number">Workspaces</th><th>Created</th></tr></thead>
          <tbody>{data.items.map(customer => <tr key={customer.id} className="clickable" onClick={() => router.push(`/customers/${encodeURIComponent(customer.id)}`)}>
            <td><Link className="table-link" href={`/customers/${encodeURIComponent(customer.id)}`} onClick={event => event.stopPropagation()}>{customer.name}</Link></td>
            <td><StatusBadge status={customer.status}/></td>
            <td className="number">{formatNumber(customer.workspace_count)}<span className="cell-sub">{formatNumber(customer.active_workspace_count)} active</span></td>
            <td>{formatDate(customer.created_at)}<span className="cell-sub">by {customer.created_by}</span></td>
          </tr>)}</tbody>
        </table></div>
        {moreError && <Notice tone="error">{moreError}</Notice>}
        {data.next_cursor && <div className="load-more"><button type="button" className="button secondary" disabled={more} onClick={() => void loadMore()}>{more && <Loader2 className="spin" size={15}/>}Load more</button></div>}
      </>}
    </section>
    <CustomerFormDialog open={creating} onClose={() => setCreating(false)} onSaved={customer => {setCreating(false); router.push(`/customers/${encodeURIComponent(customer.id)}`);}}/>
  </>;
}
