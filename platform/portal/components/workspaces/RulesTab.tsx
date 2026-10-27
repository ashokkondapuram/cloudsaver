'use client';

import {useState} from 'react';
import {ShieldQuestion} from 'lucide-react';
import {ApiError, errorMessage, portal} from '../../lib/api';
import type {AnalysisRule, Workspace, WorkspaceAnalysisRules} from '../../lib/types';
import {useLoad} from '../../lib/useLoad';
import {useUnsavedPolicy} from '../../lib/useUnsavedPolicy';
import {useSession} from '../SessionProvider';
import {Dialog} from '../ui/Dialog';
import {EmptyState, Loading, Notice, SectionTitle, Switch} from '../ui/shared';

const stateOf = (rule: AnalysisRule) => rule.unavailable_reason ? 'Unavailable' : rule.status !== 'published' ? rule.status : rule.enabled ? 'Enabled' : 'Disabled';

export function RulesTab({workspace}: {workspace: Workspace}) {
  return <WorkspaceRules key={workspace.tenant_id} workspace={workspace}/>;
}

function WorkspaceRules({workspace}: {workspace: Workspace}) {
  const {canWrite} = useSession();
  const path = `workspaces/${encodeURIComponent(workspace.tenant_id)}/analysis-rules`;
  const {data, setData, error, loading, reload} = useLoad(() => portal<WorkspaceAnalysisRules>(path), [path]);
  const [draft, setDraft] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false), [review, setReview] = useState(false), [needsReload, setNeedsReload] = useState(false);
  const [message, setMessage] = useState(''), [saved, setSaved] = useState('');
  const [query, setQuery] = useState(''), [provider, setProvider] = useState(''), [service, setService] = useState(''), [pillar, setPillar] = useState(''), [state, setState] = useState('');
  const items = data?.items || [];
  const editable = canWrite && workspace.status !== 'deleted';
  const changes = items.filter(rule => rule.status === 'published' && !rule.unavailable_reason && draft[rule.id] !== undefined && draft[rule.id] !== rule.enabled);
  useUnsavedPolicy(changes.length > 0);
  const rows = items.filter(rule => (!provider || rule.provider === provider) && (!service || rule.service_category === service) && (!pillar || rule.pillar === pillar) && (!state || stateOf(rule) === state) && (!query || [rule.id, rule.name, rule.description, rule.resource_type].join(' ').toLowerCase().includes(query.toLowerCase())));

  async function apply() {
    if (!data || !editable || busy || needsReload || changes.length === 0 || changes.length > 100) return;
    setBusy(true); setMessage(''); setSaved('');
    try {
      const updated = await portal<WorkspaceAnalysisRules>(path, {method: 'PUT', body: {version: data.version, rules: changes.map(rule => ({rule_id: rule.id, enabled: draft[rule.id]}))}});
      setData(updated); setDraft({}); setReview(false); setSaved(`Policy version ${updated.version} saved. Historical findings and mandatory protections are unchanged.`);
    } catch (cause) {
      setMessage(errorMessage(cause)); setReview(false);
      if (cause instanceof ApiError && (cause.status === 409 || cause.uncertain)) setNeedsReload(true);
    } finally {setBusy(false);}
  }
  async function reloadPolicy() {setBusy(true); try {await reload(); setNeedsReload(false); setMessage('');} finally {setBusy(false);}}

  return <>
    {error && <Notice tone="error">{error}</Notice>}{message && <Notice tone="error">{message}</Notice>}{saved && <Notice tone="success">{saved}</Notice>}
    {needsReload && <Notice tone="warning">Check the current policy before another write. Your draft remains in this session. <button className="button secondary" disabled={busy} onClick={() => void reloadPolicy()}>Reload current policy</button></Notice>}
    <section className="panel">
      <SectionTitle title="Published rules" eyebrow={data ? `POLICY VERSION ${data.version}` : 'WORKSPACE RULE POLICY'}/>
      <p className="rule-catalog-caption">Customer: <strong>{workspace.customer_name}</strong> · Workspace: <strong>{workspace.name}</strong>. Rule enablement does not authorize resource changes.</p>
      {!editable && <Notice>Read-only policy. Changes require a platform operator and a workspace that has not been deleted.</Notice>}
      {loading ? <Loading label="Loading rules…"/> : !data ? <button className="button secondary" onClick={() => void reloadPolicy()} disabled={busy}>Retry loading rules</button> : <>
        <div className="rule-catalog-filters">
          <label>Provider<select value={provider} onChange={event => setProvider(event.target.value)}><option value="">All providers</option>{[...new Set(items.map(rule => rule.provider))].sort().map(value => <option key={value}>{value}</option>)}</select></label>
          <label>Service<select value={service} onChange={event => setService(event.target.value)}><option value="">All services</option>{[...new Set(items.map(rule => rule.service_category))].sort().map(value => <option key={value}>{value}</option>)}</select></label>
          <label>Pillar<select value={pillar} onChange={event => setPillar(event.target.value)}><option value="">All pillars</option>{[...new Set(items.map(rule => rule.pillar))].sort().map(value => <option key={value}>{value}</option>)}</select></label>
          <label>Effective state<select aria-label="Effective state" value={state} onChange={event => setState(event.target.value)}><option value="">All states</option>{[...new Set(items.map(stateOf))].sort().map(value => <option key={value}>{value}</option>)}</select></label>
          <label>Search rules<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Rule name, ID or resource type"/></label>
          <button className="button secondary" onClick={() => {setQuery(''); setProvider(''); setService(''); setPillar(''); setState('');}}>Reset rule filters</button>
        </div>
        <p className="rule-catalog-caption" role="status">{rows.length} of {items.length} rules · filters describe saved policy, not unsaved drafts.</p>
        {!items.length ? <EmptyState icon={ShieldQuestion} title="No published rules">The rule catalog is empty.</EmptyState> : <div className="summary-table-scroll" tabIndex={0} aria-label="Workspace rule catalog"><table className="summary-table">
          <thead><tr><th>Rule</th><th>Provider / service</th><th>Pillar</th><th>Saved state</th><th>Draft state</th></tr></thead>
          <tbody>{rows.map(rule => <tr key={rule.id}>
            <td><strong>{rule.name}</strong><details className="rule-details"><summary>Rule details: {rule.name}</summary><p>{rule.description || 'No description supplied.'}</p><dl><div><dt>Rule ID</dt><dd><code>{rule.id}</code></dd></div><div><dt>Resource type</dt><dd>{rule.resource_type}</dd></div><div><dt>Catalog version</dt><dd>{rule.catalog_version}</dd></div><div><dt>Workspace override</dt><dd>{rule.override_version == null ? 'No workspace override' : `Version ${rule.override_version}`}</dd></div></dl><p>{rule.unavailable_reason || 'Required evidence and verification are shown in saved resource evaluations. Enabled does not mean passed.'}</p></details></td>
            <td>{rule.provider}<div className="muted">{rule.service_category}</div></td><td>{rule.pillar}</td><td>{stateOf(rule)}</td>
            <td>{editable && rule.status === 'published' && !rule.unavailable_reason ? <Switch checked={draft[rule.id] ?? rule.enabled} disabled={busy || needsReload} onChange={() => {setReview(false); setSaved(''); setDraft(current => ({...current, [rule.id]: !(current[rule.id] ?? rule.enabled)}));}} label={`Toggle ${rule.name}`}/> : <span>Read only</span>}{draft[rule.id] !== undefined && draft[rule.id] !== rule.enabled && <small>Unsaved: {draft[rule.id] ? 'Enabled' : 'Disabled'}</small>}</td>
          </tr>)}{!rows.length && <tr><td colSpan={5}>No rules match your filters.</td></tr>}</tbody>
        </table></div>}
        {changes.length > 100 && <Notice tone="warning">Review at most 100 rule changes in one request.</Notice>}
        {editable && <div className="rule-draft-actions"><button className="button primary" disabled={busy || needsReload || changes.length === 0 || changes.length > 100} onClick={() => setReview(true)}>Review {changes.length} rule changes</button><button className="button secondary" disabled={busy || !Object.keys(draft).length} onClick={() => {setDraft({}); setReview(false);}}>Discard draft</button><span>Review includes changed rules hidden by filters.</span></div>}
      </>}
    </section>
    <Dialog open={review && !!data} onClose={() => !busy && setReview(false)} dismissible={!busy} title="Review workspace rule changes">
      <div className="dialog-content"><p>Customer: <strong>{workspace.customer_name}</strong></p><p>Workspace: <strong>{workspace.name}</strong> · <code>{workspace.tenant_id}</code></p><p>Expected policy version: {data?.version}. This is a configuration review, not a simulation of resource impact.</p><ul className="rule-change-list">{changes.map(rule => <li key={rule.id}><strong>{rule.name}</strong><p>{rule.enabled ? 'Enabled' : 'Disabled'} → {draft[rule.id] ? 'Enabled' : 'Disabled'}</p></li>)}</ul><Notice>Historical evaluations and mandatory protections remain unchanged. New settings apply to future scans.</Notice></div>
      <div className="dialog-actions"><button className="button secondary" disabled={busy} onClick={() => setReview(false)}>Cancel</button><button className="button primary" disabled={busy || needsReload || !editable || !changes.length} onClick={() => void apply()}>{busy ? 'Saving…' : 'Apply rule changes'}</button></div>
    </Dialog>
  </>;
}
