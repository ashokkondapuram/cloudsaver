'use client';

import Link from 'next/link';
import {useState} from 'react';
import {RefreshCw, ShieldCheck} from 'lucide-react';
import {portal} from '../../lib/api';
import {formatDateTime, formatNumber} from '../../lib/format';
import {failureReasonLabel} from '../../lib/labels';
import type {Failure, FailureReason} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {useDebounced} from '../customers/CustomerList';
import {EmptyState, Loading, Notice, PageHeading, SectionTitle} from '../ui/shared';

const REASONS = Object.keys(failureReasonLabel) as FailureReason[];

function startOfLocalDay(value: string) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day).toISOString();
}

export function SecurityView() {
  const [reason, setReason] = useState('');
  const [sourceIp, setSourceIp] = useState('');
  const [tenantId, setTenantId] = useState('');
  const [from, setFrom] = useState('');
  const ip = useDebounced(sourceIp.trim());
  const tenant = useDebounced(tenantId.trim());
  const {data, error, loading, reload} = useLoad(
    () => portal<{items: Failure[]}>('failures', {query: {reason, source_ip: ip, tenant_id: tenant, from: from ? startOfLocalDay(from) : ''}}),
    [reason, ip, tenant, from],
  );
  const items = data?.items || [];

  return <>
    <PageHeading eyebrow="OVERSIGHT" title="Security" actions={<button type="button" className="button secondary" onClick={() => void reload()}><RefreshCw size={15}/>Refresh</button>}>
      Failed and throttled key verification attempts. Repeated failures from one source IP are blocked automatically.
    </PageHeading>
    <section className="panel">
      <SectionTitle title="Failed and throttled attempts"/>
      <div className="filter-bar">
        <label className="field">Reason<select value={reason} onChange={event => setReason(event.target.value)}><option value="">All reasons</option>{REASONS.map(value => <option key={value} value={value}>{failureReasonLabel[value]}</option>)}</select></label>
        <label className="field">Source IP<input type="text" value={sourceIp} onChange={event => setSourceIp(event.target.value)} placeholder="203.0.113.10"/></label>
        <label className="field grow">Workspace ID<input type="text" value={tenantId} onChange={event => setTenantId(event.target.value)} placeholder="00000000-0000-0000-0000-000000000000"/></label>
        <label className="field">From<input type="date" value={from} onChange={event => setFrom(event.target.value)}/></label>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {loading && !data ? <Loading label="Loading attempts…"/> : !items.length ? (!error && <EmptyState icon={ShieldCheck} title="No failed attempts">No failed or throttled attempts match these filters.</EmptyState>) :
        <div className="summary-table-scroll"><table className="summary-table">
          <thead><tr><th>Time</th><th>Source IP</th><th>Reason</th><th>Key ID</th><th>Workspace</th><th>Caller</th><th className="number">Attempts</th></tr></thead>
          <tbody>{items.map((failure, index) => <tr key={`${failure.minute}-${failure.source_ip}-${failure.key_id}-${failure.reason}-${index}`}>
            <td>{formatDateTime(failure.minute)}</td>
            <td><code>{failure.source_ip}</code></td>
            <td><span className={`state-badge ${failure.reason === 'throttled' ? 'suspended' : 'deleted'}`}>{failureReasonLabel[failure.reason] || failure.reason}</span></td>
            <td>{failure.key_id ? <code>{failure.key_id}</code> : <span className="muted">—</span>}</td>
            <td>{failure.tenant_id ? <Link className="text-link" href={`/workspaces/${encodeURIComponent(failure.tenant_id)}`}><code>{failure.tenant_id}</code></Link> : <span className="muted">—</span>}</td>
            <td>{failure.caller}</td>
            <td className="number">{formatNumber(failure.count)}</td>
          </tr>)}</tbody>
        </table></div>}
    </section>
  </>;
}
