'use client';
import {useCallback, useEffect, useState} from 'react';
import {Activity, Plus, RefreshCw} from 'lucide-react';
import {api} from '../../lib/api';
import {dateTime} from '../../lib/finops';
import {sentence} from '../../lib/resources';
import {useWorkspace} from '../WorkspaceProvider';
import {EmptyState, Loading, Notice, SectionTitle} from '../ui/shared';

type Kind = 'prometheus' | 'rest_metrics' | 'tempo' | 'jaeger';
type Connector = {id: string; name: string; kind: Kind; base_url: string; auth_kind: string; secret_ref: string | null; header_name: string | null;
  aws_account_id: string | null; gcp_project_id: string | null; queries: unknown[]; services: string[]; schedule: string; trace_window_hours: number;
  mappings: {resource_label?: string; service_resources?: Record<string, string>}; thresholds: {latency_p95_ms: number; error_rate_pct: number};
  enabled: boolean; version: number; updated_at: string};
type SummaryItem = {id: string; status: string; observed_at: string | null; error?: string; warnings?: string[];
  mapping_coverage?: {series: number; labeled: number; services: number; mapped_services: number}};
type Probe = {ok: boolean; message: string; warnings?: string[]};

const kinds: {id: Kind; label: string}[] = [{id: 'prometheus', label: 'Prometheus'}, {id: 'rest_metrics', label: 'REST metrics'}, {id: 'tempo', label: 'Grafana Tempo'}, {id: 'jaeger', label: 'Jaeger'}];
const auths = [['none', 'None'], ['bearer_env', 'Bearer token (secret reference)'], ['basic_env', 'Basic authentication (secret reference)'], ['header_env', 'Custom header (secret reference)'],
  ['azure_managed', 'Azure managed identity'], ['aws_sigv4', 'AWS SigV4 (workspace account)'], ['gcp_managed', 'Google Cloud managed identity']] as const;
const templates: Record<'prometheus' | 'rest_metrics', unknown[]> = {
  prometheus: [{id: 'cpu', metric: 'cpu_percent', unit: '%', promql: '100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])))'},
    {id: 'requests', metric: 'requests_per_second', unit: 'req/s', promql: 'sum by (instance) (rate(http_requests_total[5m]))'}],
  rest_metrics: [{id: 'cpu', metric: 'cpu_percent', unit: '%', path: 'v1/metrics/cpu', params: {from: '{start_epoch}', to: '{end_epoch}', step: '{step_seconds}'},
    series_path: 'data', resource_field: 'resource_id', points_path: 'points', timestamp_field: 'timestamp', value_field: 'value'}],
};
const kindLabel = (kind: string) => kinds.find(k => k.id === kind)?.label || sentence(kind);
const blank = () => ({id: '', version: 0, name: '', kind: 'prometheus' as Kind, base_url: '', auth_kind: 'bearer_env', secret_ref: 'CLOUDSAVER_OBSERVABILITY_SECRET_PRIMARY',
  header_name: '', aws_account_id: '', gcp_project_id: '', schedule: 'hourly', trace_window_hours: 1, resource_label: 'instance',
  queries: JSON.stringify(templates.prometheus, null, 2), services: '', latency: 500, errors: 1});
type Draft = ReturnType<typeof blank>;

function toDraft(c: Connector): Draft {
  const mapping = c.mappings.service_resources || {};
  return {id: c.id, version: c.version, name: c.name, kind: c.kind, base_url: c.base_url, auth_kind: c.auth_kind, secret_ref: c.secret_ref || '', header_name: c.header_name || '',
    aws_account_id: c.aws_account_id || '', gcp_project_id: c.gcp_project_id || '', schedule: c.schedule, trace_window_hours: c.trace_window_hours,
    resource_label: c.mappings.resource_label || '', queries: JSON.stringify(c.queries, null, 2),
    services: c.services.map(s => mapping[s] ? `${s} = ${mapping[s]}` : s).join('\n'), latency: c.thresholds.latency_p95_ms, errors: c.thresholds.error_rate_pct};
}

function toConnector(d: Draft) {
  const metrics = d.kind === 'prometheus' || d.kind === 'rest_metrics';
  let queries: unknown[] = [];
  if (metrics) {
    try {queries = JSON.parse(d.queries);} catch {throw new Error('Queries must be valid JSON. Start from the template for this connector type.');}
  }
  const lines = d.services.split('\n').map(l => l.trim()).filter(Boolean);
  const services = lines.map(l => l.split('=')[0].trim());
  const service_resources = Object.fromEntries(lines.filter(l => l.includes('=')).map(l => [l.split('=')[0].trim(), l.slice(l.indexOf('=') + 1).trim()]));
  return {name: d.name, kind: d.kind, base_url: d.base_url, auth_kind: d.auth_kind, schedule: d.schedule,
    ...(['bearer_env', 'basic_env', 'header_env'].includes(d.auth_kind) ? {secret_ref: d.secret_ref} : {}),
    ...(d.auth_kind === 'header_env' ? {header_name: d.header_name} : {}),
    ...(d.auth_kind === 'aws_sigv4' ? {aws_account_id: d.aws_account_id} : {}),
    ...(d.auth_kind === 'gcp_managed' ? {gcp_project_id: d.gcp_project_id} : {}),
    ...(metrics ? {queries} : {services, trace_window_hours: Number(d.trace_window_hours)}),
    mappings: {...(d.resource_label ? {resource_label: d.resource_label} : {}), ...(Object.keys(service_resources).length ? {service_resources} : {})},
    thresholds: {latency_p95_ms: Number(d.latency), error_rate_pct: Number(d.errors)}};
}

export function ObservabilitySettings() {
  const {token, canAdmin, canBill} = useWorkspace();
  const [items, setItems] = useState<Connector[] | null>(null), [summary, setSummary] = useState<Record<string, SummaryItem>>({});
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null), [probe, setProbe] = useState<Probe | null>(null);
  const load = useCallback(async (signal?: AbortSignal) => {
    setError('');
    try {
      const [list, status] = await Promise.all([
        canAdmin || canBill ? api<{items: Connector[]}>('/observability/connectors', token, {signal}) : Promise.resolve({items: [] as Connector[]}),
        api<{items: SummaryItem[]}>('/observability/summary', token, {signal})]);
      if (!signal?.aborted) {setItems(list.items); setSummary(Object.fromEntries(status.items.map(i => [i.id, i])));}
    } catch (cause) {if (!signal?.aborted) setError((cause as Error).message);}
  }, [token, canAdmin, canBill]);
  useEffect(() => {const request = new AbortController(); setItems(null); setDraft(null); load(request.signal); return () => request.abort();}, [load]);

  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try {await action();} catch (cause) {setError((cause as Error).message);} finally {setBusy(false);}
  }
  const test = () => run(async () => {
    if (!draft) return;
    setProbe(await api<Probe>('/observability/connectors/test', token, {body: toConnector(draft)}));
  });
  const save = () => run(async () => {
    if (!draft) return;
    const connector = toConnector(draft);
    if (draft.id) await api(`/observability/connectors/${draft.id}`, token, {body: {connector, version: draft.version}});
    else await api('/observability/connectors', token, {body: connector});
    setNotice(draft.id ? 'Connector updated.' : 'Connector created. It collects on its next scheduled run, or you can sync now.');
    setDraft(null); setProbe(null); await load();
  });
  const toggle = (c: Connector) => run(async () => {
    await api(`/observability/connectors/${c.id}/${c.enabled ? 'disable' : 'enable'}`, token, {body: {}});
    setNotice(c.enabled ? `${c.name} disabled. Its saved summaries are kept.` : `${c.name} enabled.`); await load();
  });
  const testSaved = (c: Connector) => run(async () => {
    const result = await api<Probe>(`/observability/connectors/${c.id}/test`, token, {body: {}});
    if (result.ok) setNotice(`${c.name}: ${result.message}`); else setError(`${c.name}: ${result.message}`);
  });
  const sync = () => run(async () => {
    await api('/observability/sync', token, {body: {idempotency_key: crypto.randomUUID()}});
    setNotice('Collection queued. Summaries update as each connector finishes.');
  });

  const metrics = draft && (draft.kind === 'prometheus' || draft.kind === 'rest_metrics');
  const secret = draft && ['bearer_env', 'basic_env', 'header_env'].includes(draft.auth_kind);
  return <section className="panel">
    <SectionTitle title="Observability connectors" eyebrow="METRICS · TRACES · CORRELATION" action={canAdmin && !draft ? <div className="button-row">
      <button className="button secondary" disabled={busy || !items?.some(i => i.enabled)} onClick={sync}><RefreshCw size={15}/>Sync now</button>
      <button className="button primary" disabled={busy} onClick={() => {setDraft(blank()); setProbe(null);}}><Plus size={15}/>Add connector</button></div> : undefined}>
      Read-only metrics and traces, linked to resources through mappings you define
    </SectionTitle>
    <p className="inline-help">Connectors only read data. Secrets are never stored in CloudSaver: enter the name of an environment variable that your operator sets, such as <code>CLOUDSAVER_OBSERVABILITY_SECRET_PRIMARY</code>.</p>
    {error && <Notice tone="error">{error}</Notice>}{notice && <Notice tone="success">{notice}</Notice>}
    {draft && <form className="drawer-section" onSubmit={event => {event.preventDefault(); save();}}>
      <h3>{draft.id ? `Edit ${draft.name}` : 'Add connector'}</h3>
      <div className="enterprise-filters">
        <label>Connector type<select value={draft.kind} onChange={e => {const kind = e.target.value as Kind; setDraft({...draft, kind, queries: kind === 'prometheus' || kind === 'rest_metrics' ? JSON.stringify(templates[kind], null, 2) : draft.queries});}}>{kinds.map(k => <option key={k.id} value={k.id}>{k.label}</option>)}</select></label>
        <label>Name<input required maxLength={80} value={draft.name} onChange={e => setDraft({...draft, name: e.target.value})}/></label>
        <label>Base URL<input required type="url" placeholder="https://prometheus.example.com" value={draft.base_url} onChange={e => setDraft({...draft, base_url: e.target.value})}/></label>
        <label>Authentication<select value={draft.auth_kind} onChange={e => setDraft({...draft, auth_kind: e.target.value})}>{auths.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        {secret && <label>Secret reference<input required pattern="CLOUDSAVER_OBSERVABILITY_SECRET_[A-Z0-9_]{1,80}" value={draft.secret_ref} onChange={e => setDraft({...draft, secret_ref: e.target.value.toUpperCase()})}/></label>}
        {draft.auth_kind === 'header_env' && <label>Header name<input required value={draft.header_name} placeholder="X-API-Key" onChange={e => setDraft({...draft, header_name: e.target.value})}/></label>}
        {draft.auth_kind === 'aws_sigv4' && <label>AWS account ID<input required pattern="\d{12}" value={draft.aws_account_id} onChange={e => setDraft({...draft, aws_account_id: e.target.value})}/></label>}
        {draft.auth_kind === 'gcp_managed' && <label>Google Cloud project ID<input required value={draft.gcp_project_id} onChange={e => setDraft({...draft, gcp_project_id: e.target.value})}/></label>}
        <label>Schedule<select value={draft.schedule} onChange={e => setDraft({...draft, schedule: e.target.value})}><option value="hourly">Hourly (last 7 days, 5-minute steps)</option><option value="daily">Daily (last 30 days, 1-hour steps)</option><option value="manual">Manual only</option></select></label>
        {metrics ? <label>Resource label<input required value={draft.resource_label} placeholder="instance or azure_resource_id" onChange={e => setDraft({...draft, resource_label: e.target.value})}/></label>
          : <label>Trace window (hours)<input type="number" min={1} max={24} value={draft.trace_window_hours} onChange={e => setDraft({...draft, trace_window_hours: Number(e.target.value)})}/></label>}
        <label>Latency threshold (P95, ms)<input type="number" min={1} value={draft.latency} onChange={e => setDraft({...draft, latency: Number(e.target.value)})}/></label>
        <label>Error rate threshold (%)<input type="number" min={0.01} step={0.01} max={100} value={draft.errors} onChange={e => setDraft({...draft, errors: Number(e.target.value)})}/></label>
      </div>
      {metrics ? <label className="stacked-field">Queries (JSON, up to 20)<textarea rows={8} spellCheck={false} value={draft.queries} onChange={e => setDraft({...draft, queries: e.target.value})}/>
        <span className="inline-help">The resource label value must match the resource ID exactly, for example the full Azure resource ID. Metric types: cpu_percent, memory_percent, requests_per_second, error_rate_pct, latency_p95_ms or custom.</span></label>
        : <label className="stacked-field">Services (one per line, optionally <code>service = resource ID</code>)<textarea rows={5} spellCheck={false} value={draft.services} placeholder="checkout = /subscriptions/…/providers/Microsoft.Web/sites/checkout" onChange={e => setDraft({...draft, services: e.target.value})}/>
        <span className="inline-help">Only services linked to a resource ID appear on that resource. Up to 50 services.</span></label>}
      {probe && <Notice tone={probe.ok ? 'success' : 'error'}>{probe.message}{probe.warnings?.length ? ` ${probe.warnings.join(' ')}` : ''}</Notice>}
      <div className="button-row"><button type="button" className="button secondary" disabled={busy} onClick={test}>{busy ? 'Testing connection…' : 'Test connection'}</button>
        <button type="submit" className="button primary" disabled={busy}>{draft.id ? 'Save changes' : 'Create connector'}</button>
        <button type="button" className="button secondary" disabled={busy} onClick={() => {setDraft(null); setProbe(null);}}>Cancel</button></div>
    </form>}
    {!items && !error ? <Loading label="Loading observability connectors…"/> : items && (items.length ? <div className="summary-table-scroll" tabIndex={0} aria-label="Observability connectors"><table className="summary-table">
      <caption className="sr-only">Observability connectors and their latest collection</caption>
      <thead><tr><th>Name</th><th>Type</th><th>Schedule</th><th>Last collection</th><th>Linked data</th>{canAdmin && <th>Actions</th>}</tr></thead>
      <tbody>{items.map(c => {const s = summary[c.id]; const coverage = s?.mapping_coverage; return <tr key={c.id}>
        <td>{c.name}{!c.enabled && <small> · Disabled</small>}</td><td>{kindLabel(c.kind)}</td><td>{sentence(c.schedule)}</td>
        <td>{!s || s.status === 'not_collected' ? 'Not collected yet' : s.status === 'completed' ? (s.observed_at ? dateTime(s.observed_at) : 'Completed') : <span title={s.error}>Failed{s.observed_at ? ` · ${dateTime(s.observed_at)}` : ''}</span>}{s?.error && <small className="inline-help"> {s.error}</small>}</td>
        <td>{coverage ? (c.kind === 'prometheus' || c.kind === 'rest_metrics' ? `${coverage.labeled.toLocaleString('en-US')} of ${coverage.series.toLocaleString('en-US')} series labeled` : `${coverage.mapped_services.toLocaleString('en-US')} of ${coverage.services.toLocaleString('en-US')} services linked`) : '—'}</td>
        {canAdmin && <td><div className="button-row"><button className="button secondary small" disabled={busy} onClick={() => {setDraft(toDraft(c)); setProbe(null);}}>Edit</button><button className="button secondary small" disabled={busy} onClick={() => testSaved(c)}>Test</button><button className="button secondary small" disabled={busy} onClick={() => toggle(c)}>{c.enabled ? 'Disable' : 'Enable'}</button></div></td>}
      </tr>;})}</tbody></table></div>
      : <EmptyState icon={Activity} title="No observability connectors">{canAdmin ? 'Add a Prometheus, REST metrics, Tempo or Jaeger connector to link metrics and traces to your resources.' : 'Ask a workspace admin to add a Prometheus, REST metrics, Tempo or Jaeger connector.'}</EmptyState>)}
  </section>;
}
