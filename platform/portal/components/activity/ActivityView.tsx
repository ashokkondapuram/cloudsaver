'use client';

import {useState} from 'react';
import {AUDIT_ACTIONS, actionLabel} from '../../lib/labels';
import {useDebounced} from '../customers/CustomerList';
import {PageHeading} from '../ui/shared';
import {AuditList} from './AuditList';

export function ActivityView() {
  const [action, setAction] = useState('');
  const [actor, setActor] = useState('');
  const [tenantId, setTenantId] = useState('');
  const filters = {action, actor: useDebounced(actor.trim()), tenant_id: useDebounced(tenantId.trim())};
  return <>
    <PageHeading eyebrow="OVERSIGHT" title="Activity">Every change to customers, workspaces, keys, billing and platform settings.</PageHeading>
    <section className="panel">
      <div className="filter-bar" style={{paddingTop: 22}}>
        <label className="field">Action<select value={action} onChange={event => setAction(event.target.value)}><option value="">All actions</option>{AUDIT_ACTIONS.map(value => <option key={value} value={value}>{actionLabel(value)}</option>)}</select></label>
        <label className="field">Actor<input type="text" value={actor} onChange={event => setActor(event.target.value)} placeholder="Name or email"/></label>
        <label className="field grow">Workspace ID<input type="text" value={tenantId} onChange={event => setTenantId(event.target.value)} placeholder="00000000-0000-0000-0000-000000000000"/></label>
      </div>
      <AuditList filters={filters} title="All activity" showWorkspace/>
    </section>
  </>;
}
