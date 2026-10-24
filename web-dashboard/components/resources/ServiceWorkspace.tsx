'use client';

import Link from 'next/link';
import {useEffect, useState} from 'react';
import {api} from '../../lib/api';
import {useWorkspace} from '../WorkspaceProvider';
import {Loading, Notice, SectionTitle} from '../ui/shared';

const labels: Record<string, string> = {disks: 'Managed disks', 'public-ips': 'Public IP addresses',
  'virtual-machines': 'Virtual machines', 'app-service-plans': 'App Service plans'};
type Snapshot = {scan_id: string; observed_at: string; coverage: Record<string, number | string | unknown[]>;
  rule_matrix: {rule_id: string; name: string; outcomes: Record<string, number>}[]};
type View = {latest: Snapshot | null; history: Snapshot[]; resources: {resource_id: string; resource_name: string; subscription_id: string}[]};
type Comparison = {message: string; items: {resource_id: string; state: string}[]};

export function ServiceWorkspace({service = 'disks'}: {service?: string}) {
  const {token, workspace} = useWorkspace();
  const [data, setData] = useState<View | null>(null), [error, setError] = useState('');
  const [before, setBefore] = useState(''), [after, setAfter] = useState(''), [comparison, setComparison] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const c = new AbortController(); setData(null); setComparison(null); setError('');
    api<View>(`/services/${service}`, token, {signal: c.signal}).then(value => {if (!c.signal.aborted) {
      setData(value); setAfter(value.history[0]?.scan_id || ''); setBefore(value.history[1]?.scan_id || '');
    }}).catch(cause => {if (!c.signal.aborted) setError((cause as Error).message);});
    return () => c.abort();
  }, [token, service, workspace?.tenant_id]);
  async function compare() {
    setBusy(true); setError('');
    try {setComparison(await api<Comparison>(`/services/${service}/comparison?before=${before}&after=${after}`, token));}
    catch (cause) {setError((cause as Error).message);} finally {setBusy(false);}
  }
  return <>
    <div className="page-heading"><div><div className="eyebrow">SERVICE ANALYSIS</div><h1>{labels[service] || 'Service not found'}</h1><p>Saved inventory and evidence contracts. Unknown evidence remains unknown.</p></div></div>
    <nav aria-label="Azure service analysis" className="page-tabs">{Object.entries(labels).map(([key, label]) => <Link className="button secondary" aria-current={service === key ? 'page' : undefined} key={key} href={`/services/${key}`}>{label}</Link>)}<Link className="button secondary" href="/settings/rules">Manage analysis rules</Link></nav>
    {error && <Notice tone="error">{error}</Notice>}
    {!data ? !error && <Loading label="Loading service observations…"/> : !data.latest ? <Notice>No completed observation is available for this workspace.</Notice> : <>
      <section className="panel"><SectionTitle title="Coverage">Observed {new Date(data.latest.observed_at).toLocaleString()} · Counts may overlap across different rules.</SectionTitle>
        <dl className="settings-key-values">{['discovered_count', 'in_scope_count', 'evaluated_count', 'insufficient_evidence_count', 'excluded_count', 'unsupported_count'].map(key => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{String(data.latest!.coverage[key])}</dd></div>)}</dl>
        <p className="inline-help">Coverage describes collector-visible supported types. It does not certify every resource in the cloud account. Missing telemetry requires collector/access investigation.</p>
      </section>
      <section className="panel"><SectionTitle title="Rule outcomes">Original frozen policy and evidence from the selected observation.</SectionTitle>
        <table className="summary-table"><thead><tr><th>Rule</th><th>Outcome distribution</th></tr></thead><tbody>{data.latest.rule_matrix.map(rule => <tr key={rule.rule_id}><td>{rule.name}</td><td>{Object.entries(rule.outcomes).map(([key, count]) => `${key.replaceAll('_', ' ')}: ${count}`).join(' · ') || 'Not evaluated in this snapshot'}</td></tr>)}</tbody></table>
      </section>
      <section className="panel"><SectionTitle title="Observation history">Financial amounts remain unknown until attributable cost evidence is available.</SectionTitle>
        <table className="summary-table"><thead><tr><th>Observed</th><th>Resources</th><th>Evidence gaps</th></tr></thead><tbody>{data.history.map(row => <tr key={row.scan_id}><td>{new Date(row.observed_at).toLocaleString()}</td><td>{String(row.coverage.in_scope_count)}</td><td>{String(row.coverage.insufficient_evidence_count)}</td></tr>)}</tbody></table>
        <label className="field-label">Earlier snapshot<select value={before} onChange={e => {setBefore(e.target.value); setComparison(null);}}><option value="">Select snapshot</option>{data.history.map(row => <option key={row.scan_id} value={row.scan_id}>{new Date(row.observed_at).toLocaleString()}</option>)}</select></label>
        <label className="field-label">Later snapshot<select value={after} onChange={e => {setAfter(e.target.value); setComparison(null);}}><option value="">Select snapshot</option>{data.history.map(row => <option key={row.scan_id} value={row.scan_id}>{new Date(row.observed_at).toLocaleString()}</option>)}</select></label>
        <button className="button secondary" disabled={busy || !before || !after || before === after} onClick={() => void compare()}>Compare observations</button>
        {comparison && <><Notice>{comparison.message}</Notice><ul>{comparison.items.slice(0, 100).map(row => <li key={row.resource_id}>{row.resource_id}: {row.state.replaceAll('_', ' ')}</li>)}</ul><p>Showing up to 100 of {comparison.items.length} resources.</p></>}
      </section>
    </>}
  </>;
}
