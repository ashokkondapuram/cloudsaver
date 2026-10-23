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
  const {canWrite} = useSession();
  const [status, setStatus] = useState('');
  const [message, setMessage] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [draft, setDraft] = useState({title: '', summary: '', body: ''});
  const [creating, setCreating] = useState(false);
  const {data, setData, error, loading, reload} = useLoad(
    () => portal<Page<KnowledgePublication>>('knowledge/publications', {query: {status}}), [status]);
  const items = data?.items || [];

  async function create() {
    setCreating(true); setMessage('');
    try {
      const created = await portal<KnowledgePublication>('knowledge/publications', {method: 'POST', body: draft});
      setData(current => current ? {...current, items: [created, ...current.items]} : {items: [created], next_cursor: null});
      setDraft({title: '', summary: '', body: ''});
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
    {canWrite && <section className="panel">
      <SectionTitle title="New candidate"/>
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
            <td>{item.title}<div className="muted">{item.summary}</div></td>
            <td><span className={`state-badge ${item.status === 'published' ? 'active' : item.status === 'rejected' ? 'deleted' : 'suspended'}`}>{item.status}</span></td>
            <td>{item.quality_score ?? <span className="muted">—</span>}</td>
            <td>{formatDateTime(item.updated_at)}</td>
            <td>{canWrite && (busyId === item.id ? <Loader2 className="spin" size={14}/> : <div className="row-actions">
              {item.status !== 'published' && <button type="button" className="button secondary small" onClick={() => void setPublicationStatus(item, 'published')}>Publish</button>}
              {item.status !== 'rejected' && item.status !== 'deprecated' && <button type="button" className="button secondary small" onClick={() => void setPublicationStatus(item, 'rejected')}>Reject</button>}
              {item.status === 'published' && <button type="button" className="button secondary small" onClick={() => void setPublicationStatus(item, 'deprecated')}>Deprecate</button>}
            </div>)}</td>
          </tr>)}</tbody>
        </table></div>}
    </section>
  </>;
}
