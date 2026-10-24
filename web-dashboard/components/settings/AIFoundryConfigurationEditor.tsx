'use client';

import {useCallback, useEffect, useState} from 'react';
import {BrainCircuit, Save, ShieldCheck} from 'lucide-react';
import {api} from '../../lib/api';
import {useWorkspace} from '../WorkspaceProvider';
import {Loading, Notice, SectionTitle} from '../ui/shared';

type Provider = 'azure' | 'aws' | 'gcp';
type Binding = {enabled: boolean; target_id: string | null; [key: string]: string | boolean | null};
type Policy = {advisory_enabled: boolean;
  routing_mode: string; primary_provider: Provider; max_input_tokens_per_request: number;
  max_output_tokens_per_request: number; hourly_attempt_budget: number; monthly_token_limit: number | null};
type Config = {providers: Record<Provider, Binding>; policy: Policy};
type Template = {provider: Provider; target_id: string; model: string; fields: Record<string, string | boolean | null>; auth: string; privacy_attestation: string};
type Result = {status: string; latency_ms: number; failure_category: string | null; remediation_hint: string;
  stages: {check: string; status: string; reason?: string}[]; inference_invoked: boolean};
type View = {version: number; ai_foundry: Config; editable: boolean; plan_allowed: boolean; directory_mode: string; catalog: Template[];
  platform_policy: {version: number; policy: {enabled: boolean; disabled_providers: string[];
    max_input_tokens_per_request: number; max_output_tokens_per_request: number; hourly_attempt_ceiling: number; monthly_token_ceiling: number}};
  usage: {attempts_last_30d: number; known_input_tokens: number; known_output_tokens: number; unmetered_attempts: number;
    monthly_tokens_used_or_reserved: number; monthly_unbounded_legacy_attempts: number; attempts_current_hour: number; monthly_period: string} | null;
  diagnostics: {id: string; provider: Provider; created_at: string; result: Result}[]; message: string; knowledge_retrieval: string};

const names: Record<Provider, string> = {azure: 'Azure AI Foundry', aws: 'Amazon Bedrock', gcp: 'Google Vertex AI'};
const labels: Record<string, string> = {endpoint_url: 'Foundry endpoint URL', deployment_name: 'Deployment name', api_version: 'API version',
  region: 'Destination region', deployment_sku: 'Deployment capacity', role_arn: 'Federated IAM role ARN', external_id: 'Workspace external ID',
  model_id: 'Model / inference profile', guardrail_id: 'Bedrock guardrail ID', guardrail_version: 'Published guardrail version',
  project_id: 'Project ID', location: 'Vertex location', service_account_email: 'Workload service account'};

export function AIFoundryConfigurationEditor() {
  const {token, workspace, canAdmin, notify} = useWorkspace();
  const [view, setView] = useState<View | null>(null), [draft, setDraft] = useState<Config | null>(null);
  const [error, setError] = useState(''), [busy, setBusy] = useState(''), [ack, setAck] = useState(false);
  const [results, setResults] = useState<Partial<Record<Provider, Result>>>({});
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const value = await api<View>('/settings/ai', token, {signal});
      if (!signal?.aborted) {setView(value); setDraft(value.ai_foundry); setError('');}
    } catch (cause) {if (!signal?.aborted) setError((cause as Error).message);}
  }, [token]);
  useEffect(() => {const c = new AbortController(); setView(null); setDraft(null); setAck(false); setResults({}); void load(c.signal); return () => c.abort();}, [load, workspace?.tenant_id]);
  const editable = !!view?.editable && canAdmin && !busy;
  function policy<K extends keyof Policy>(key: K, value: Policy[K]) {
    setDraft(current => current ? {...current, policy: {...current.policy, [key]: value}} : current);
    setAck(false);
  }
  function choose(provider: Provider, targetId: string) {
    const selected = view?.catalog.find(item => item.provider === provider && item.target_id === targetId);
    setDraft(current => current ? {...current, providers: {...current.providers,
      [provider]: {...current.providers[provider], ...(selected?.fields || {}), target_id: targetId || null,
        enabled: !!targetId && current.providers[provider].enabled}}} : current);
    setAck(false); setResults(current => ({...current, [provider]: undefined}));
  }
  async function save() {
    if (!view || !draft) return;
    setBusy('save'); setError('');
    try {
      const saved = await api<{version: number; ai_foundry: Config}>('/settings/ai', token,
        {method: 'PUT', body: {version: view.version, ai_foundry: draft, acknowledge_external_processing: ack}});
      setView({...view, ...saved}); setDraft(saved.ai_foundry); setAck(false);
      notify('AI settings saved. Current platform policy is checked again before inference.');
    } catch (cause) {setError((cause as Error).message);} finally {setBusy('');}
  }
  async function test(provider: Provider) {
    const id = view?.ai_foundry.providers[provider].target_id;
    if (!id) return;
    setBusy(provider); setError('');
    try {setResults(current => ({...current, [provider]: undefined}));
      const result = await api<Result>('/settings/ai/test-connection', token, {body: {provider, target_id: id}});
      setResults(current => ({...current, [provider]: result}));
    } catch (cause) {setError((cause as Error).message);} finally {setBusy('');}
  }
  const dirty = !!view && JSON.stringify(draft) !== JSON.stringify(view.ai_foundry);
  return <section className="panel settings-form">
    <SectionTitle title="AI Foundry configuration" action={<BrainCircuit size={18}/>}>Choose approved, keyless model destinations for this workspace.</SectionTitle>
    {error && <Notice tone="error">{error}<button type="button" className="text-button" onClick={() => void load()}>Refresh AI settings</button></Notice>}
    {!view || !draft ? !error && <Loading label="Loading AI policy and bindings…"/> : <>
      {!view.editable && <Notice>{view.directory_mode === 'cutover' ? 'AI configuration is locked while the platform directory owns workspace configuration.' : 'An unrestricted workspace administrator can edit these settings.'}</Notice>}
      {!view.platform_policy.policy.enabled && <Notice tone="warning">The platform AI kill switch is off. No new inference can start.</Notice>}
      {!view.plan_allowed && <Notice tone="warning">AI advisory is not included in this workspace plan. Contact your account manager to enable it.</Notice>}
      <div className="identity-grid">{(['azure', 'aws', 'gcp'] as Provider[]).map(provider => {
        const selected = draft.providers[provider], result = results[provider];
        const candidate = view.catalog.find(item => item.provider === provider && item.target_id === selected.target_id);
        return <article key={provider}><h3>{names[provider]}</h3>
          <label className="checkbox-row"><input type="checkbox" checked={selected.enabled} disabled={!editable || !selected.target_id}
            onChange={event => {setDraft({...draft, providers: {...draft.providers, [provider]: {...selected, enabled: event.target.checked}}}); setAck(false);}}/>Enable this provider</label>
          <label className="field-label">Approved {names[provider]} binding<select aria-label={`${names[provider]} binding`} value={selected.target_id || ''} disabled={!editable}
            onChange={event => choose(provider, event.target.value)}><option value="">Not configured</option>{view.catalog.filter(item => item.provider === provider).map(item => <option key={item.target_id} value={item.target_id}>{item.target_id} · {item.model}</option>)}</select></label>
          {!view.catalog.some(item => item.provider === provider) && <p className="inline-help">Ask the operator to register a tenant-bound endpoint, identity and model for this provider.</p>}
          {candidate && <><dl className="settings-key-values">{Object.entries(candidate.fields).filter(([key, value]) => labels[key] && value !== null).map(([key, value]) => <div key={key}><dt>{labels[key]}</dt><dd><code>{String(value)}</code></dd></div>)}</dl><p className="inline-help">{candidate.privacy_attestation}</p></>}
          {canAdmin && <button type="button" className="button secondary small" disabled={!!busy || dirty || !view.ai_foundry.providers[provider].target_id}
            onClick={() => void test(provider)}>{busy === provider ? 'Checking metadata…' : `Test ${names[provider]} connection`}</button>}
          {result && <div role="status"><strong>{result.status === 'inconclusive' ? 'Readiness incomplete · inference permission unverified' : result.status} · {result.latency_ms} ms</strong>
            <p>{result.remediation_hint}</p><ul>{result.stages.map(stage => <li key={stage.check}>{stage.check.replaceAll('_', ' ')}: {stage.status.replaceAll('_', ' ')}{stage.reason ? ` · ${stage.reason}` : ''}</li>)}</ul></div>}
        </article>;
      })}</div>
      <fieldset className="settings-fieldset" disabled={!editable}><legend><ShieldCheck size={16}/>Routing, budget and consent</legend>
        <label className="checkbox-row"><input type="checkbox" checked={draft.policy.advisory_enabled} onChange={event => policy('advisory_enabled', event.target.checked)}/>Enable opt-in AI advisory</label>
        <label className="field-label">Source-provider routing<select value={draft.policy.routing_mode} onChange={event => policy('routing_mode', event.target.value)}><option value="same_cloud_only">Same cloud only</option><option value="workspace_default_provider" disabled>Workspace default provider — requires verified human step-up</option></select></label>
        <p className="inline-help">A missing matching provider blocks the request. Kubernetes inference is blocked until its hosting cloud is authoritatively verified.</p>
        <div className="settings-row">{([
          ['max_input_tokens_per_request', 'Input-token allowance', 256, view.platform_policy.policy.max_input_tokens_per_request],
          ['max_output_tokens_per_request', 'Maximum output tokens', 256, view.platform_policy.policy.max_output_tokens_per_request],
          ['hourly_attempt_budget', 'Hourly attempt budget', 1, view.platform_policy.policy.hourly_attempt_ceiling],
          ['monthly_token_limit', 'Monthly token cap', 512, view.platform_policy.policy.monthly_token_ceiling],
        ] as const).map(([key, label, min, max]) => <label key={key}><span className="field-label">{label}</span><input type="number" min={min} max={max} step={1}
          value={draft.policy[key] ?? ''} placeholder={key === 'monthly_token_limit' ? `Platform cap: ${max}` : undefined}
          onChange={event => policy(key, key === 'monthly_token_limit' && event.target.value === '' ? null : Number(event.target.value))}/><small>Platform ceiling: {max.toLocaleString()}</small></label>)}</div>
      </fieldset>
      {view.usage && <div className="drawer-section"><h3>Measured usage</h3><p>{view.usage.attempts_last_30d.toLocaleString()} attempts in 30 days · {view.usage.known_input_tokens.toLocaleString()} known input tokens · {view.usage.known_output_tokens.toLocaleString()} known output tokens · {view.usage.unmetered_attempts} unmetered attempts.</p>
        <label className="field-label">{view.usage.monthly_period}: tokens used or reserved<progress max={draft.policy.monthly_token_limit || view.platform_policy.policy.monthly_token_ceiling} value={view.usage.monthly_tokens_used_or_reserved}/></label>
        <p>{view.usage.monthly_tokens_used_or_reserved.toLocaleString()} / {(draft.policy.monthly_token_limit || view.platform_policy.policy.monthly_token_ceiling).toLocaleString()}. Unknown outcomes retain their reservation.</p>
        {!!view.usage.monthly_unbounded_legacy_attempts && <Notice tone="warning">Historical unmetered calls have no reservation. Capped inference is paused until the monthly budget can be verified.</Notice>}</div>}
      {editable && <><label className="checkbox-row ai-ack"><input type="checkbox" checked={ack} onChange={event => setAck(event.target.checked)}/>I acknowledge the selected provider, model and region, possible charges, and unverified advisory processing.</label>
        <button type="button" className="button primary" disabled={!!busy || !dirty || (draft.policy.advisory_enabled && !ack)} onClick={() => void save()}><Save size={15}/>{busy === 'save' ? 'Saving…' : 'Save AI configuration'}</button></>}
      <p className="inline-help">Policy revision {view.platform_policy.version}. {view.message}</p>
      {!!view.diagnostics.length && <details><summary>Recent connection checks ({view.diagnostics.length})</summary><ul>{view.diagnostics.map(item => <li key={item.id}>{names[item.provider]} · {new Date(item.created_at).toLocaleString()} · {item.result.status} · {item.result.latency_ms} ms</li>)}</ul></details>}
    </>}
  </section>;
}
