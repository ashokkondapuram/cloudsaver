'use client';

import {useCallback, useEffect, useState} from 'react';
import {api, ApiError} from '../../lib/api';
import {useUnsavedPolicy} from '../../lib/useUnsavedPolicy';
import {providerNames} from '../../lib/finops';
import {sentence} from '../../lib/resources';
import {useWorkspace} from '../WorkspaceProvider';
import {Loading, Notice, SectionTitle} from '../ui/shared';
import {Dialog} from '../ui/dialog';

type Rule = {id: string; name: string; description: string; provider: string; resource_type: string;
  service_category?: string; pillar?: string; catalog_version?: number; override_version?: number | null;
  enabled: boolean; status: string; parameters: Record<string, number>;
  allowed_override_bounds: Record<string, {minimum: number; maximum: number}>; unavailable_reason: string | null};
type Policy = {version: number; items: Rule[]};
type Change = {rule_id: string; enabled: boolean; parameters: Record<string, number>};
type Preview = {version: number; resources_changed: number | null; scan_id: string | null; message: string};
const effectiveState = (rule: Rule) => rule.unavailable_reason ? 'Unavailable' : rule.status !== 'published' ? sentence(rule.status) : rule.enabled ? 'Enabled' : 'Disabled';
const differs = (rule: Rule, change: Change) => rule.enabled !== change.enabled || Object.keys({...rule.parameters, ...change.parameters}).some(key => rule.parameters[key] !== change.parameters[key]);

export function CustomerRuleSettings() {
  const {token, workspace} = useWorkspace();
  return <RuleSettings key={`${workspace?.tenant_id}:${token}`}/>;
}

function RuleSettings() {
  const {token, canAdmin, workspace} = useWorkspace();
  const [data, setData] = useState<Policy | null>(null), [error, setError] = useState('');
  const [draft, setDraft] = useState<Record<string, Change>>({}), [provider, setProvider] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null), [busy, setBusy] = useState(false);
  const [service, setService] = useState(''), [search, setSearch] = useState(''), [state, setState] = useState(''), [pillar, setPillar] = useState('');
  const [needsReload, setNeedsReload] = useState(false), [notice, setNotice] = useState('');
  const load = useCallback(async (signal?: AbortSignal, preserveDraft = false) => {
    try {
      const policy = await api<Policy>('/rules/effective', token, {signal});
      if (signal?.aborted) return;
      setData(policy); setPreview(null); setError(''); setNeedsReload(false);
      setDraft(current => preserveDraft ? Object.fromEntries(Object.entries(current).filter(([id, change]) => {
        const rule = policy.items.find(item => item.id === id);
        return rule && rule.status === 'published' && !rule.unavailable_reason && differs(rule, change);
      })) : {});
      if (preserveDraft) setNotice('Current policy loaded. Review retained changes and parameter bounds, then request a new preview. Changes to unavailable or retired rules were removed.');
    } catch (cause) {if (!signal?.aborted) setError((cause as Error).message);}
  }, [token]);
  useEffect(() => {const controller = new AbortController(); void load(controller.signal); return () => controller.abort();}, [load]);
  const restricted = !!workspace?.scope_restrictions;
  const canEdit = canAdmin && !restricted;
  const rows = data ? data.items.filter(rule => (!provider || rule.provider === provider) && (!service || rule.service_category === service) && (!pillar || rule.pillar === pillar) && (!state || effectiveState(rule) === state) && (!search || [rule.id, rule.name, rule.resource_type, rule.description].join(' ').toLowerCase().includes(search.toLowerCase()))) : [];
  const changes = Object.values(draft);
  useUnsavedPolicy(changes.length > 0);
  const invalid = changes.some(change => {
    const rule = data?.items.find(item => item.id === change.rule_id);
    return !rule || Object.entries(change.parameters).some(([key, value]) => {
      const bounds = rule.allowed_override_bounds[key];
      return !Number.isSafeInteger(value) || (!bounds && value !== rule.parameters[key]) || (bounds && (value < bounds.minimum || value > bounds.maximum));
    });
  });
  function edit(rule: Rule, patch: Partial<Change>) {
    setPreview(null); setNotice('');
    setDraft(current => {
      const next = {...(current[rule.id] ?? {rule_id: rule.id, enabled: rule.enabled, parameters: rule.parameters}), ...patch};
      const result = {...current};
      if (differs(rule, next)) result[rule.id] = next; else delete result[rule.id];
      return result;
    });
  }
  async function reloadPolicy() {setBusy(true); try {await load(undefined, true);} finally {setBusy(false);}}
  async function submit(apply: boolean) {
    if (!data || !canEdit || busy || needsReload || invalid || !changes.length || changes.length > 100 || apply && preview?.version !== data.version) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const body = {version: data.version, rules: changes};
      if (apply) {
        const saved = await api<Policy>('/rules/overrides', token, {method: 'PUT', body});
        setData(saved); setDraft({}); setPreview(null); setNotice(`Rule policy version ${saved.version} saved. Historical snapshots are unchanged.`);
      } else {
        const result = await api<Preview>('/rules/preview', token, {body});
        if (result.version !== data.version) {setNeedsReload(true); throw new Error('Policy changed during preview. Reload the current policy before reviewing again.');}
        setPreview(result);
      }
    } catch (cause) {
      setError((cause as Error).message); setPreview(null);
      if (cause instanceof ApiError && (cause.status === 409 || cause.uncertain)) setNeedsReload(true);
    } finally {setBusy(false);}
  }
  return <>
    <section className="panel"><SectionTitle title="Analysis rules" action={data ? <span className="mini-badge">Policy version {data.version}</span> : undefined}>Review effective rules by provider, service and pillar. Editing a rule does not approve a cloud change.</SectionTitle>
      {error && <Notice tone="error">{error}</Notice>}{notice && <div role="status"><Notice>{notice}</Notice></div>}
      {restricted && <Notice>Your key is scope-limited. Workspace-wide rule changes require an unrestricted authorized administrator.</Notice>}
      {!canAdmin && <Notice>Read-only rule policy. A workspace administrator can request changes.</Notice>}
      {needsReload && <Notice tone="warning">The current policy must be checked before another write. Your draft is retained in this session. <button className="button secondary" disabled={busy} onClick={() => void reloadPolicy()}>Reload current policy</button></Notice>}
      {!data ? error ? <button className="button secondary" disabled={busy} onClick={() => void reloadPolicy()}>Retry loading rules</button> : <Loading label="Loading published rules…"/> : <>
        <div className="rule-catalog-filters">
          <label>Provider<select value={provider} onChange={event => setProvider(event.target.value)}><option value="">All providers</option>{[...new Set(data.items.map(rule => rule.provider))].sort().map(value => <option key={value} value={value}>{providerNames[value] ?? value}</option>)}</select></label>
          <label>Service category<select value={service} onChange={event => setService(event.target.value)}><option value="">All services</option>{[...new Set(data.items.map(rule => rule.service_category).filter(Boolean))].sort().map(value => <option key={value} value={value}>{sentence(value!)}</option>)}</select></label>
          <label>Pillar<select value={pillar} onChange={event => setPillar(event.target.value)}><option value="">All pillars</option>{[...new Set(data.items.map(rule => rule.pillar).filter(Boolean))].sort().map(value => <option key={value} value={value}>{sentence(value!)}</option>)}</select></label>
          <label>Effective state<select aria-label="Effective state" value={state} onChange={event => setState(event.target.value)}><option value="">All states</option>{[...new Set(data.items.map(effectiveState))].sort().map(value => <option key={value}>{value}</option>)}</select></label>
          <label>Find a resource rule<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Name, ID or resource type"/></label>
          <button className="button secondary" onClick={() => {setProvider(''); setService(''); setPillar(''); setState(''); setSearch('');}}>Reset rule filters</button>
        </div>
        <p className="rule-catalog-caption" role="status">{rows.length} of {data.items.length} rules · filters use saved effective policy; drafts apply after review.</p>
        <div className="summary-table-scroll" tabIndex={0} aria-label="Analysis rule catalog"><table className="summary-table"><thead><tr><th>Rule and service</th><th>Effective state</th><th>Delegated parameters</th></tr></thead><tbody>
          {rows.map(rule => {
            const pending = draft[rule.id];
            const blocked = !canEdit || busy || needsReload || rule.status !== 'published' || !!rule.unavailable_reason;
            return <tr key={rule.id}>
              <td><strong>{rule.name}</strong><p>{providerNames[rule.provider] ?? rule.provider} · {rule.resource_type}</p><small>{rule.description}</small>
                <details className="rule-details"><summary>Rule details: {rule.name}</summary><dl>
                  <div><dt>Identifier</dt><dd><code>{rule.id}</code></dd></div><div><dt>Catalog version</dt><dd>{rule.catalog_version ?? 'Not supplied'}</dd></div>
                  <div><dt>Pillar</dt><dd>{rule.pillar ? sentence(rule.pillar) : 'Not supplied'}</dd></div><div><dt>Workspace override</dt><dd>{rule.override_version == null ? 'Not reported' : `Version ${rule.override_version}`}</dd></div>
                  <div><dt>Availability</dt><dd>{rule.unavailable_reason || sentence(rule.status)}</dd></div>
                </dl><p>Required telemetry and verification are shown with the saved resource evaluation. Enabling a rule does not prove it passed; missing evidence remains unknown.</p><p>Mandatory protection controls cannot be removed by disabling an assessment rule.</p></details>
              </td>
              <td><label><input type="checkbox" aria-label={`Enable ${rule.name}`} checked={pending?.enabled ?? rule.enabled} disabled={blocked} onChange={event => edit(rule, {enabled: event.target.checked})}/>{pending ? `Draft: ${pending.enabled ? 'Enabled' : 'Disabled'}` : effectiveState(rule)}</label>{pending && <small>Saved: {effectiveState(rule)}</small>}</td>
              <td>{Object.entries(rule.allowed_override_bounds).length ? Object.entries(rule.allowed_override_bounds).map(([key, bounds]) => <label key={key} className="field-label">{sentence(key)}
                <input type="number" min={bounds.minimum} max={bounds.maximum} step={1} disabled={blocked} value={Number.isFinite((pending?.parameters ?? rule.parameters)[key]) ? (pending?.parameters ?? rule.parameters)[key] : ''} onChange={event => edit(rule, {parameters: {...(pending?.parameters ?? rule.parameters), [key]: event.target.value === '' ? NaN : Number(event.target.value)}})}/>
                <small>{bounds.minimum}–{bounds.maximum}</small></label>) : <span>No delegated parameters</span>}</td>
            </tr>;
          })}{!rows.length && <tr><td colSpan={3}>{data.items.length ? 'No rules match your filters.' : 'No published catalog is available.'}</td></tr>}</tbody></table></div>
        <p className="rule-catalog-caption">Disabling a rule preserves historical findings and mandatory protection controls. Parameter units are defined by the published rule; bounds alone do not establish units.</p>
        {invalid && <Notice tone="warning">Enter whole-number parameter values within the current delegated bounds before previewing.</Notice>}
        {changes.length > 100 && <Notice tone="warning">Review at most 100 rule changes in one request.</Notice>}
        {canEdit && <div className="rule-draft-actions"><button className="button primary" disabled={busy || needsReload || invalid || !changes.length || changes.length > 100} onClick={() => void submit(false)}>{busy ? 'Preparing…' : `Preview ${changes.length} rule changes`}</button><button className="button secondary" disabled={busy || !changes.length} onClick={() => {setDraft({}); setPreview(null);}}>Discard draft</button><span>Draft changes include rules outside the current filters.</span></div>}
      </>}
    </section>
    <Dialog open={!!preview} onClose={() => !busy && setPreview(null)} title="Review rule policy changes">
      <div className="dialog-content"><p>{preview?.message}</p><p>{preview?.resources_changed === null ? 'No saved scan is available to estimate impact.' : `${preview?.resources_changed} resources change their evaluation state in the saved snapshot.`}</p>
        <p>Workspace: <strong>{workspace?.name}</strong> · Policy version {data?.version}</p>
        <ul className="rule-change-list">{changes.map(change => {const rule = data?.items.find(item => item.id === change.rule_id); return <li key={change.rule_id}><strong>{rule?.name || change.rule_id}</strong><p>{rule?.enabled ? 'Enabled' : 'Disabled'} → {change.enabled ? 'Enabled' : 'Disabled'}</p>{Object.entries(change.parameters).filter(([key, value]) => value !== rule?.parameters[key]).map(([key, value]) => <p key={key}>{sentence(key)}: {rule?.parameters[key] ?? 'Not supplied'} → {value}</p>)}</li>;})}</ul>
        <p>Historical snapshots retain the original policy. New settings apply to the next scan. This preview is not execution approval.</p></div>
      <div className="dialog-actions"><button className="button secondary" disabled={busy} onClick={() => setPreview(null)}>Cancel</button><button className="button primary" disabled={busy || needsReload || invalid} onClick={() => void submit(true)}>Apply changes</button></div>
    </Dialog>
  </>;
}
