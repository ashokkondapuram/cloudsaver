'use client';

import {useCallback, useEffect, useState} from 'react';
import {api} from '../../lib/api';
import {useWorkspace} from '../WorkspaceProvider';
import {Loading, Notice, SectionTitle} from '../ui/shared';
import {Dialog} from '../ui/dialog';

type Rule = {id: string; name: string; description: string; provider: string; resource_type: string;
  enabled: boolean; status: string; parameters: Record<string, number>;
  allowed_override_bounds: Record<string, {minimum: number; maximum: number}>; unavailable_reason: string | null};
type Policy = {version: number; items: Rule[]};
type Change = {rule_id: string; enabled: boolean; parameters: Record<string, number>};
type Preview = {version: number; resources_changed: number | null; scan_id: string | null; message: string};

export function CustomerRuleSettings() {
  const {token, canAdmin, workspace} = useWorkspace();
  const [data, setData] = useState<Policy | null>(null), [error, setError] = useState('');
  const [draft, setDraft] = useState<Record<string, Change>>({}), [provider, setProvider] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null), [busy, setBusy] = useState(false);
  const load = useCallback(async (signal?: AbortSignal) => {
    try {setData(await api<Policy>('/rules/effective', token, {signal})); setDraft({}); setError('');}
    catch (cause) {if (!signal?.aborted) setError((cause as Error).message);}
  }, [token]);
  useEffect(() => {setData(null); setDraft({}); setPreview(null); const c = new AbortController(); void load(c.signal); return () => c.abort();}, [load, workspace?.tenant_id]);
  const restricted = !!workspace?.scope_restrictions;
  const canEdit = canAdmin && !restricted;
  function edit(rule: Rule, changes: Partial<Change>) {
    setPreview(null);
    setDraft(current => {
      const previous = current[rule.id] ?? {rule_id: rule.id, enabled: rule.enabled, parameters: rule.parameters};
      return {...current, [rule.id]: {...previous, ...changes}};
    });
  }
  async function submit(apply: boolean) {
    if (!data) return;
    setBusy(true); setError('');
    try {
      const body = {version: data.version, rules: Object.values(draft)};
      if (apply) {const saved = await api<Policy>('/rules/overrides', token, {method: 'PUT', body}); setData(saved); setDraft({}); setPreview(null);}
      else setPreview(await api<Preview>('/rules/preview', token, {body}));
    } catch (cause) {setError((cause as Error).message); setPreview(null);} finally {setBusy(false);}
  }
  return <>
    <section className="panel"><SectionTitle title="Analysis rules">Published provider and service rules with effective workspace parameters.</SectionTitle>
      {error && <Notice tone="error">{error}</Notice>}
      {restricted && <Notice>Your key is scope-limited. Workspace-wide rule changes require an unrestricted authorized administrator.</Notice>}
      {!canAdmin && <Notice>Read-only rule policy. A workspace administrator can request changes.</Notice>}
      {!data ? <Loading label="Loading published rules…"/> : <>
        <label className="field-label">Provider<select value={provider} onChange={e => setProvider(e.target.value)}>
          <option value="">All providers</option>{[...new Set(data.items.map(r => r.provider))].sort().map(p => <option key={p}>{p}</option>)}</select></label>
        <div className="summary-table-scroll"><table className="summary-table"><thead><tr><th>Rule and service</th><th>Effective state</th><th>Delegated parameters</th></tr></thead><tbody>
          {data.items.filter(r => !provider || r.provider === provider).map(rule => <tr key={rule.id}>
            <td><strong>{rule.name}</strong><p>{rule.provider} · {rule.resource_type}</p><small>{rule.description}</small></td>
            <td><label><input type="checkbox" aria-label={`Enable ${rule.name}`} checked={draft[rule.id]?.enabled ?? rule.enabled}
              disabled={!canEdit || busy || rule.status !== 'published' || !!rule.unavailable_reason} onChange={e => edit(rule, {enabled: e.target.checked})}/>
              {rule.unavailable_reason || (rule.status !== 'published' ? 'Retired' : 'Enabled for evaluation')}</label></td>
            <td>{Object.entries(rule.allowed_override_bounds).map(([key, bounds]) => <label key={key} className="field-label">{key.replaceAll('_', ' ')}
              <input type="number" min={bounds.minimum} max={bounds.maximum} step={1} disabled={!canEdit || busy}
                value={(draft[rule.id]?.parameters ?? rule.parameters)[key]}
                onChange={e => edit(rule, {parameters: {...(draft[rule.id]?.parameters ?? rule.parameters), [key]: Number(e.target.value)}})}/>
              <small>{bounds.minimum}–{bounds.maximum}</small></label>)}</td>
          </tr>)}</tbody></table></div>
        <p className="inline-help">Enabled rules can still have insufficient evidence. Disabling a rule does not remove historical findings or change mandatory protection controls.</p>
        {canEdit && <button className="button primary" disabled={busy || !Object.keys(draft).length} onClick={() => void submit(false)}>{busy ? 'Preparing…' : `Preview ${Object.keys(draft).length} rule changes`}</button>}
      </>}
    </section>
    <Dialog open={!!preview} onClose={() => !busy && setPreview(null)} title="Review rule policy changes">
      <div className="dialog-content"><p>{preview?.message}</p><p>{preview?.resources_changed === null ? 'No saved scan is available to estimate impact.' : `${preview?.resources_changed} resources change their evaluation state in the saved snapshot.`}</p>
        <p>Historical snapshots retain the original policy. New settings apply to the next scan.</p></div>
      <div className="dialog-actions"><button className="button secondary" disabled={busy} onClick={() => setPreview(null)}>Cancel</button>
        <button className="button primary" disabled={busy} onClick={() => void submit(true)}>Apply reviewed changes</button></div>
    </Dialog>
  </>;
}
