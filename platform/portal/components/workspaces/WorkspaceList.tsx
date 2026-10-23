'use client';

import {useRouter} from 'next/navigation';
import {useState} from 'react';
import {LayoutGrid, Loader2, Plus, RefreshCw, Search} from 'lucide-react';
import {errorMessage, portal} from '../../lib/api';
import {STATUSES, statusLabel} from '../../lib/labels';
import type {Page, Workspace} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {useDebounced} from '../customers/CustomerList';
import {useSession} from '../SessionProvider';
import {EmptyState, Loading, Notice, PageHeading} from '../ui/shared';
import {CreateWorkspaceDialog} from './CreateWorkspaceDialog';
import {WorkspaceTable, workspaceHref} from './WorkspaceTable';

export function WorkspaceList() {
  const router = useRouter();
  const {canWrite} = useSession();
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [creating, setCreating] = useState(false);
  const [more, setMore] = useState(false);
  const [moreError, setMoreError] = useState('');
  const q = useDebounced(query.trim());
  const {data, setData, error, loading, reload} = useLoad(() => portal<Page<Workspace>>('workspaces', {query: {q, status, limit: 50}}), [q, status]);

  async function loadMore() {
    if (!data?.next_cursor) return;
    setMore(true); setMoreError('');
    try {
      const page = await portal<Page<Workspace>>('workspaces', {query: {q, status, limit: 50, cursor: data.next_cursor}});
      setData({items: [...data.items, ...page.items], next_cursor: page.next_cursor});
    } catch (cause) {setMoreError(errorMessage(cause));} finally {setMore(false);}
  }

  return <>
    <PageHeading eyebrow="DIRECTORY" title="Workspaces" actions={<>
      <button type="button" className="button secondary" onClick={() => void reload()}><RefreshCw size={15}/>Refresh</button>
      {canWrite && <button type="button" className="button primary" onClick={() => setCreating(true)}><Plus size={15}/>Create workspace</button>}
    </>}>A workspace groups one customer’s cloud accounts and keys across Azure, AWS, Google Cloud, and Kubernetes.</PageHeading>
    <section className="panel">
      <div className="section-title"><div><h2>All workspaces</h2></div></div>
      <div className="filter-bar">
        <label className="field grow">Search<span className="search-input"><Search size={15}/><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search by name, customer, or workspace ID"/></span></label>
        <label className="field">Status<select value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option>{STATUSES.map(value => <option key={value} value={value}>{statusLabel[value]}</option>)}</select></label>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {loading && !data ? <Loading label="Loading workspaces…"/> : !data?.items.length ? (
        !error && <EmptyState icon={LayoutGrid} title={q || status ? 'No matching workspaces' : 'No workspaces yet'}>
          {q || status ? 'Try a different search or status.' : 'Create a workspace to connect a customer’s cloud accounts.'}
        </EmptyState>
      ) : <>
        <WorkspaceTable workspaces={data.items}/>
        {moreError && <Notice tone="error">{moreError}</Notice>}
        {data.next_cursor && <div className="load-more"><button type="button" className="button secondary" disabled={more} onClick={() => void loadMore()}>{more && <Loader2 className="spin" size={15}/>}Load more</button></div>}
      </>}
    </section>
    <CreateWorkspaceDialog open={creating} onClose={() => setCreating(false)} onCreated={workspace => {setCreating(false); router.push(workspaceHref(workspace.tenant_id));}}/>
  </>;
}
