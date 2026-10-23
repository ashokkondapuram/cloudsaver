'use client';

import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {formatDate, formatDateTime, formatNumber} from '../../lib/format';
import {planName} from '../../lib/labels';
import type {Workspace} from '../../lib/types';
import {ProviderList, StatusBadge} from '../ui/shared';

export function workspaceHref(tenantId: string) {
  return `/workspaces/${encodeURIComponent(tenantId)}`;
}

export function WorkspaceTable({workspaces, showCustomer = true}: {workspaces: Workspace[]; showCustomer?: boolean}) {
  const router = useRouter();
  return <div className="summary-table-scroll"><table className="summary-table">
    <thead><tr>
      <th>Workspace</th>{showCustomer && <th>Customer</th>}<th>Workspace ID</th><th>Plan</th><th>Providers</th><th>Status</th>
      <th className="number">Active keys</th><th>Last used</th><th>Next expiry</th>
    </tr></thead>
    <tbody>{workspaces.map(workspace => <tr key={workspace.tenant_id} className="clickable" onClick={() => router.push(workspaceHref(workspace.tenant_id))}>
      <td><Link className="table-link" href={workspaceHref(workspace.tenant_id)} onClick={event => event.stopPropagation()}>{workspace.name}</Link></td>
      {showCustomer && <td><Link className="text-link" href={`/customers/${encodeURIComponent(workspace.customer_id)}`} onClick={event => event.stopPropagation()}>{workspace.customer_name}</Link></td>}
      <td><code>{workspace.tenant_id}</code></td>
      <td>{planName(workspace.plan_tier, workspace.plan_name)}</td>
      <td><ProviderList providers={workspace.providers}/></td>
      <td><StatusBadge status={workspace.status}/></td>
      <td className="number">{formatNumber(workspace.active_keys)}</td>
      <td>{workspace.last_used_at ? formatDateTime(workspace.last_used_at) : <span className="muted">Never</span>}</td>
      <td>{workspace.next_expiry ? formatDate(workspace.next_expiry) : <span className="muted">—</span>}</td>
    </tr>)}</tbody>
  </table></div>;
}
