'use client';

import {useState} from 'react';
import {BookOpen, Loader2, Plus, RefreshCw} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import {formatDateTime} from '../../lib/format';
import type {KnowledgePublication, Page, PublicationStatus} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {useSession} from '../SessionProvider';
import {EmptyState, Loading, Notice, PageHeading, SectionTitle} from '../ui/shared';

const STATUSES: PublicationStatus[] = ['draft', 'published', 'deprecated', 'rejected'];

export function KnowledgeView() {
  const {canWrite, session} = useSession();
  const [status, setStatus] = useState('');
  const [message, setMessage] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [draft, setDraft] = useState({title: '', summary: '', body: '', source_kind: 'synthetic', source_url: ''});
  const [creating, setCreating] = useState(false);
  const {data, setData, error, loading, reload} = useLoad(
    () => portal<Page<KnowledgePublication>>('knowledge/publications', {query: {status}}), [status]);
  const items = data?.items || [];
  const canReview = session?.roles.some(role => ['KnowledgeReviewer', 'PrivacyReviewer'].includes(role));
  const {data: metrics, error: metricsError, reload: reloadMetrics} = useLoad(() => portal<{
    active_published: number; fresh_published: number; status_counts: Record<string, number>;
    as_of: string; truncated: boolean; message: string}>('knowledge/metrics'), []);

  async function review(publication: KnowledgePublication, kind: 'technical' | 'privacy') {
    setBusyId(publication.id); setMessage('');
    try {await portal(`knowledge/publications/${publication.id}/review`, {method: 'POST', body: {version: publication.version, review: kind}}); await reload();}
    catch (cause) {setMessage(errorMessage(cause));} finally {setBusyId(null);}
  }

  async function create() {
    setCreating(true); setMessage('');
    try {
      const created = await portal<KnowledgePublication>('knowledge/publications', {method: 'POST', body: draft});
      setData(current => current ? {...current, items: [created, ...current.items]} : {items: [created], next_cursor: null});
      setDraft({title: '', summary: '', body: '', source_kind: 'synthetic', source_url: ''});
      void reloadMetrics();
    } catch (cause) {
      setMessage(errorMessage(cause));
    } finally {
      setCreating(false);
    }
  }

  async function setPublicationStatus(publication: KnowledgePublication, next: PublicationStatus) {
    setBusyId(publication.id); setMessage('');
    try {
      const updated = await portal<KnowledgePublication>(`knowledge/publications/${publication.id}`, {
        method: 'PATCH', body: {version: publication.version, status: next},
      });
      setData(current => current ? {...current, items: current.items.map(item => item.id === updated.id ? updated : item)} : current);
      void reloadMetrics();
    } catch (cause) {
      setMessage(errorMessage(cause));
    } finally {
      setBusyId(null);
    }
  }

  return <>
    <PageHeading eyebrow="PLATFORM" title="Knowledge" actions={<button type="button" className="button secondary" onClick={() => void reload()}><RefreshCw size={15}/>Refresh</button>}>
      Reviewed advisory patterns shared across tenants. No tenant-identifying content belongs here; reject a candidate rather than publish it under uncertainty.
    </PageHeading>
    {error && <Notice tone="error">{error}</Notice>}
    {message && <Notice tone="error">{message}</Notice>}
    {metricsError && <Notice tone="warning">Knowledge metrics unavailable: {metricsError}</Notice>}
    {metrics && <section className="panel"><SectionTitle title="Knowledge learned so far">Published content, separate from client records and inference volume.</SectionTitle>
      <dl className="detail-list"><div><dt>Active published articles</dt><dd>{metrics.active_published}</dd></div><div><dt>Fresh published articles</dt><dd>{metrics.fresh_published}</dd></div>
        <div><dt>Awaiting review</dt><dd>{metrics.status_counts.draft || 0}</dd></div><div><dt>Deprecated</dt><dd>{metrics.status_counts.deprecated || 0}</dd></div>
        <div><dt>Rejected</dt><dd>{metrics.status_counts.rejected || 0}</dd></div><div><dt>Citation and correctness rates</dt><dd>Not yet measured</dd></div></dl>
      <p className="muted">{metrics.message} Updated {formatDateTime(metrics.as_of)}.{metrics.truncated ? ' Counts are bounded and incomplete.' : ''}</p></section>}
    {canWrite && <section className="panel">
      <SectionTitle title="New candidate"/>
      <Notice>Only independently created synthetic guidance or approved public documentation is eligible. Client names, IDs, telemetry, advisories, feedback, and embeddings must never be entered here. Technical and privacy approvals require two different reviewers, neither the author.</Notice>
      <label className="field-label">Source type<select value={draft.source_kind} onChange={event => setDraft({...draft, source_kind: event.target.value})}><option value="synthetic">Independent synthetic guidance</option><option value="public_documentation">Approved public documentation</option></select></label>
      {draft.source_kind === 'public_documentation' && <label className="field-label">Public source URL<input type="url" value={draft.source_url} onChange={event => setDraft({...draft, source_url: event.target.value})}/></label>}
      <label className="field-label">Title</label>
      <input className="input" value={draft.title} onChange={event => setDraft({...draft, title: event.target.value})} disabled={creating}/>
      <label className="field-label">Summary</label>
      <input className="input" value={draft.summary} onChange={event => setDraft({...draft, summary: event.target.value})} disabled={creating}/>
      <label className="field-label">Body</label>
      <textarea className="input" rows={3} value={draft.body} onChange={event => setDraft({...draft, body: event.target.value})} disabled={creating}/>
      <div className="panel-footer">
        <button type="button" className="button primary small" disabled={creating || !draft.title || !draft.summary || !draft.body} onClick={() => void create()}>
          {creating ? <Loader2 className="spin" size={14}/> : <Plus size={14}/>}Add draft
        </button>
      </div>
    </section>}
    <section className="panel">
      <SectionTitle title="Publications" action={
        <select value={status} onChange={event => setStatus(event.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map(value => <option key={value} value={value}>{value}</option>)}
        </select>}/>
      {loading && !data ? <Loading label="Loading publications…"/> : !items.length ?
        (!error && <EmptyState icon={BookOpen} title="No publications">No knowledge candidates match this filter.</EmptyState>) :
        <div className="summary-table-scroll"><table className="summary-table">
          <thead><tr><th>Title</th><th>Status</th><th>Quality</th><th>Updated</th><th/></tr></thead>
          <tbody>{items.map(item => <tr key={item.id}>
            <td>{item.title}<div className="muted">{item.summary}</div>
              <details><summary>Read candidate and sources</summary>
                <p style={{whiteSpace: 'pre-wrap', overflowWrap: 'anywhere'}}>{item.body}</p>
                <p className="muted">Version {item.version} · Author {item.created_by} · {item.source_kind === 'synthetic' ? 'Independent synthetic guidance' : 'Public documentation'}</p>
                {item.source_url && <a href={item.source_url} target="_blank" rel="noopener noreferrer">Open approved public source</a>}
                <p className="muted">Technical reviewer: {item.reviews?.technical?.actor || 'pending'} · Privacy reviewer: {item.reviews?.privacy?.actor || 'pending'}</p>
              </details>
            </td>
            <td><span className={`state-badge ${item.status === 'published' ? 'active' : item.status === 'rejected' ? 'deleted' : 'suspended'}`}>{item.status}</span></td>
            <td>{item.quality_score ?? <span className="muted">—</span>}</td>
            <td>{formatDateTime(item.updated_at)}</td>
            <td>{(canWrite || canReview) && (busyId === item.id ? <Loader2 className="spin" size={14}/> : <div className="row-actions">
              {item.status === 'draft' && <>
                {session?.roles.includes('KnowledgeReviewer') && <button type="button" className="button secondary small" onClick={() => void review(item, 'technical')}>Technical review</button>}
                {session?.roles.includes('PrivacyReviewer') && <button type="button" className="button secondary small" onClick={() => void review(item, 'privacy')}>Privacy review</button>}
                {canWrite && <button type="button" className="button secondary small" disabled={!item.reviews?.technical || !item.reviews?.privacy} onClick={() => void setPublicationStatus(item, 'published')}>Publish reviewed draft</button>}
                <small>Technical: {item.reviews?.technical ? 'approved' : 'pending'} · Privacy: {item.reviews?.privacy ? 'approved' : 'pending'}</small>
              </>}
              {canWrite && item.status !== 'rejected' && item.status !== 'deprecated' && <button type="button" className="button secondary small" onClick={() => void setPublicationStatus(item, 'rejected')}>Reject</button>}
              {canWrite && item.status === 'published' && <button type="button" className="button secondary small" onClick={() => void setPublicationStatus(item, 'deprecated')}>Deprecate</button>}
            </div>)}</td>
          </tr>)}</tbody>
        </table></div>}
    </section>
  </>;
}
