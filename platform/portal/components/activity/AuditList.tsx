'use client';

import Link from 'next/link';
import {useState} from 'react';
import {Activity, Loader2} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import {formatAttribution} from '../../lib/format';
import {actionLabel, auditActor, auditSubject, billingStateLabel} from '../../lib/labels';
import type {AuditEvent, BillingState} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {EmptyState, Loading, Notice, SectionTitle} from '../ui/shared';

type Filters = {customer_id?: string; tenant_id?: string; key_id?: string; actor?: string; action?: string};
type AuditPage = {items: AuditEvent[]; next_before: string | null};

function detailText(event: AuditEvent) {
  const details = event.details || {};
  const parts: string[] = [];
  const state = details.billing_state ?? details.to;
  if (event.action === 'billing_state_changed' && typeof state === 'string' && state in billingStateLabel) {
    parts.push(`New status: ${billingStateLabel[state as BillingState]}`);
  }
  if (event.actor_type === 'provider' && typeof details.event_id === 'string') parts.push(`Event ${details.event_id}`);
  const reason = details.reason;
  if (typeof reason === 'string' && reason.trim()) parts.push(`Reason: ${reason.trim()}`);
  return parts.join(' · ');
}

export function AuditList({filters, title, description, showWorkspace = false}: {filters: Filters; title: string; description?: string; showWorkspace?: boolean}) {
  const [more, setMore] = useState(false);
  const [moreError, setMoreError] = useState('');
  const key = JSON.stringify(filters);
  const {data, setData, error, loading} = useLoad(() => portal<AuditPage>('audit', {query: {...filters, limit: 50}}), [key]);

  async function loadMore() {
    if (!data?.next_before) return;
    setMore(true); setMoreError('');
    try {
      const page = await portal<AuditPage>('audit', {query: {...filters, limit: 50, before: data.next_before}});
      setData({items: [...data.items, ...page.items], next_before: page.next_before});
    } catch (cause) {setMoreError(errorMessage(cause));} finally {setMore(false);}
  }

  return <>
    <SectionTitle title={title}>{description}</SectionTitle>
    {error && <Notice tone="error">{error}</Notice>}
    {loading && !data ? <Loading label="Loading activity…"/> : !data?.items.length ? (!error && <EmptyState icon={Activity} title="No activity yet">Changes appear here as operators and services make them.</EmptyState>) : <>
      <ol className="audit-list">{data.items.map(event => {
        const subject = auditSubject(event);
        const extra = detailText(event);
        return <li key={event.id}>
          <span className="timeline-dot" aria-hidden="true"/>
          <div>
            <p><strong>{actionLabel(event.action)}</strong>{subject && ` ${subject}`} · {formatAttribution(event.occurred_at, auditActor(event))}</p>
            {(extra || (showWorkspace && event.tenant_id)) && <small>
              {showWorkspace && event.tenant_id && <>Workspace <Link className="text-link" href={`/workspaces/${encodeURIComponent(event.tenant_id)}`}><code>{event.tenant_id}</code></Link>{extra ? ' · ' : ''}</>}
              {extra}
            </small>}
          </div>
        </li>;
      })}</ol>
      {moreError && <Notice tone="error">{moreError}</Notice>}
      {data.next_before && <div className="load-more"><button type="button" className="button secondary" disabled={more} onClick={() => void loadMore()}>{more && <Loader2 className="spin" size={15}/>}Load more</button></div>}
    </>}
  </>;
}
