'use client';

import {useEffect, useState} from 'react';
import {ChartLineUp} from '@phosphor-icons/react';
import {api} from '../../lib/api';
import {useWorkspace} from '../WorkspaceProvider';
import {Loading, Notice, SectionTitle} from '../ui/shared';

type Connector = {id: string; name: string; enabled: boolean; cluster_values: string[]; mimir_datasource_uid: string};
type Item = {namespace: string; pod: string; container: string; recommendation_direction: string;
  current_cpu_request: number | null; suggested_cpu_request: number | null;
  current_memory_request: number | null; suggested_memory_request: number | null; needs_review: boolean};
type Job = {status: string; payload: {result?: {items: Item[]; policy_version: string; queried_at: string}; error?: string}};

export function GrafanaRightsizingPanel() {
  const {token, canAdmin} = useWorkspace();
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [connectorId, setConnectorId] = useState('');
  const [cluster, setCluster] = useState('');
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api<{items: Connector[]}>('/kubernetes/grafana/connectors', token).then(r => {
      setConnectors(r.items.filter(c => c.enabled));
      if (r.items[0]) {
        setConnectorId(r.items[0].id);
        setCluster(r.items[0].cluster_values?.[0] || '');
      }
    }).catch(() => setConnectors([]));
  }, [token]);

  async function run() {
    if (!connectorId) return;
    setBusy(true); setError(''); setJob(null);
    try {
      const idempotency = crypto.randomUUID();
      const created = await api<Job>('/kubernetes/grafana/rightsizing/run', token, {
        method: 'POST',
        body: {idempotency_key: idempotency, connector_id: connectorId, cluster: cluster || undefined, window_days: 14},
      });
      setJob(created);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const items = job?.payload?.result?.items || [];

  return <section className="panel">
    <SectionTitle title="Live rightsizing (Grafana)" action={<ChartLineUp size={20} weight="regular"/>}>
      Advisory CPU and memory request suggestions from Mimir metrics. Does not change your cluster.
    </SectionTitle>
    {!connectors.length
      ? <p className="inline-help">{canAdmin ? 'Add a Grafana Mimir connector under Settings → Observability (kind grafana_mimir), or use the Kubernetes Grafana API.' : 'Ask a workspace administrator to connect Grafana.'}</p>
      : <>
        <div className="enterprise-filters">
          <label>Connector<select value={connectorId} onChange={e => { setConnectorId(e.target.value); const c = connectors.find(x => x.id === e.target.value); if (c?.cluster_values?.[0]) setCluster(c.cluster_values[0]); }}>
            {connectors.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select></label>
          <label>Cluster<select value={cluster} onChange={e => setCluster(e.target.value)}>
            <option value="">All configured clusters</option>
            {(connectors.find(c => c.id === connectorId)?.cluster_values || []).map(v => <option key={v} value={v}>{v}</option>)}
          </select></label>
          {canAdmin && <button type="button" className="button secondary" disabled={busy} onClick={() => void run()}>{busy ? 'Running…' : 'Run analysis'}</button>}
        </div>
        {error && <Notice tone="error">{error}</Notice>}
        {busy && <Loading label="Querying Grafana…"/>}
        {job?.payload?.error && <Notice tone="error">{job.payload.error}</Notice>}
        {items.length > 0 && <>
          <p className="inline-help">Policy {job?.payload?.result?.policy_version} · Queried {job?.payload?.result?.queried_at}</p>
          <div className="grid-scroll"><table className="data-table"><thead><tr><th>Workload</th><th>CPU req → suggested</th><th>Memory req → suggested</th><th>Direction</th></tr></thead>
            <tbody>{items.slice(0, 50).map(row => <tr key={`${row.namespace}/${row.pod}/${row.container}`}>
              <td>{row.namespace}/{row.pod}<small>{row.container}</small></td>
              <td>{row.current_cpu_request ?? '—'} → {row.suggested_cpu_request ?? '—'}</td>
              <td>{row.current_memory_request ?? '—'} → {row.suggested_memory_request ?? '—'}</td>
              <td>{row.needs_review ? 'Needs review' : row.recommendation_direction}</td>
            </tr>)}</tbody></table></div>
        </>}
      </>}
  </section>;
}
