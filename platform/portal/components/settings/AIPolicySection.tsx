'use client';

import {useEffect, useState} from 'react';
import {portal, errorMessage} from '../../lib/api';
import {useLoad} from '../../lib/useLoad';
import {useSession} from '../SessionProvider';
import {Loading, Notice, SectionTitle} from '../ui/shared';
import {DataGovernancePolicyEditor,defaultDataPolicy,type DataPolicy} from './DataGovernancePolicyEditor';

type Provider = 'azure' | 'aws' | 'gcp';
type Policy = {enabled: boolean; allowed_providers: Provider[]; disabled_providers: Provider[];
  allowed_models: Record<Provider, string[]>; allowed_regions: Record<Provider, string[]>;
  allow_cross_provider: boolean; max_input_tokens_per_request: number; max_output_tokens_per_request: number;
  hourly_attempt_ceiling: number; monthly_token_ceiling: number;data_governance?:DataPolicy};
type View = {version: number; policy: Policy; updated_at: string; updated_by: string};

export function AIPolicySection() {
  const {canWrite} = useSession();
  const {data, setData, error, loading} = useLoad(() => portal<View>('ai-policy'), []);
  const [draft, setDraft] = useState<Policy | null>(null), [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  useEffect(() => {if (data) setDraft(data.policy);}, [data]);
  const dirty = !!data && JSON.stringify(draft) !== JSON.stringify(data.policy);
  async function save() {
    if (!data || !draft) return;
    setBusy(true); setMessage('');
    try {
      const cleaned = {...draft, allowed_models: Object.fromEntries(Object.entries(draft.allowed_models).map(([key, items]) => [key, items.map(item => item.trim()).filter(Boolean)])),
        allowed_regions: Object.fromEntries(Object.entries(draft.allowed_regions).map(([key, items]) => [key, items.map(item => item.trim()).filter(Boolean)]))};
      setData(await portal<View>('ai-policy', {method: 'PUT', body: {version: data.version, policy: cleaned}}));
    }
    catch (cause) {setMessage(errorMessage(cause));} finally {setBusy(false);}
  }
  return <section className="panel">
    <SectionTitle title="AI platform guardrails">Workspace settings can narrow these bounds. Current policy is checked before each new inference.</SectionTitle>
    {(error || message) && <Notice tone="error">{error || message}</Notice>}
    {loading && !data ? <Loading label="Loading AI policy…"/> : draft && <>
      <fieldset disabled={!canWrite || busy}><legend>Platform inference control</legend>
        <label className="checkbox-row"><input type="checkbox" checked={draft.enabled} onChange={event => setDraft({...draft, enabled: event.target.checked})}/>Permit new AI inference across workspaces</label>
        <p className="muted">Turning this off blocks new claims. It cannot cancel a provider request already in progress. Empty allowlists permit no model or region.</p>
        {(['azure', 'aws', 'gcp'] as Provider[]).map(provider => <div className="settings-fieldset" key={provider}><h3>{provider.toUpperCase()}</h3>
          <label className="checkbox-row"><input type="checkbox" checked={draft.allowed_providers.includes(provider)} onChange={event => setDraft({...draft, allowed_providers: event.target.checked ? [...draft.allowed_providers, provider] : draft.allowed_providers.filter(item => item !== provider)})}/>Allow provider</label>
          <label className="checkbox-row"><input type="checkbox" checked={draft.disabled_providers.includes(provider)} onChange={event => setDraft({...draft, disabled_providers: event.target.checked ? [...draft.disabled_providers, provider] : draft.disabled_providers.filter(item => item !== provider)})}/>Emergency provider kill switch</label>
          <label className="field-label">Approved models / inference profiles<textarea aria-label={`${provider} approved models`} rows={3} value={draft.allowed_models[provider].join('\n')} onChange={event => setDraft({...draft, allowed_models: {...draft.allowed_models, [provider]: event.target.value.split('\n')}})}/></label>
          <label className="field-label">Approved regions<input aria-label={`${provider} approved regions`} value={draft.allowed_regions[provider].join(', ')} onChange={event => setDraft({...draft, allowed_regions: {...draft.allowed_regions, [provider]: event.target.value.split(',').map(item => item.trim())}})}/></label>
        </div>)}
        {([
          ['max_input_tokens_per_request', 'Maximum input-token allowance', 256, 16000],
          ['max_output_tokens_per_request', 'Maximum output tokens', 256, 4096],
          ['hourly_attempt_ceiling', 'Hourly attempt ceiling', 1, 100],
          ['monthly_token_ceiling', 'Monthly token ceiling', 512, 1000000000],
        ] as const).map(([key, label, min, max]) => <label key={key} className="field-label">{label}<input type="number" min={min} max={max} value={draft[key]} onChange={event => setDraft({...draft, [key]: Number(event.target.value)})}/></label>)}
        <p className="muted">The client-contribution pipeline and cross-provider routing remain disabled. Human step-up is required before source-cloud restrictions can be relaxed.</p>
        <DataGovernancePolicyEditor value={draft.data_governance||defaultDataPolicy} onChange={data_governance=>setDraft({...draft,data_governance})}/>
      </fieldset>
      {canWrite && <button type="button" className="button primary" disabled={!dirty || busy} onClick={() => void save()}>{busy ? 'Saving…' : 'Save AI policy'}</button>}
      <p className="muted">Revision {data?.version} · Last changed by {data?.updated_by}</p>
    </>}
  </section>;
}
