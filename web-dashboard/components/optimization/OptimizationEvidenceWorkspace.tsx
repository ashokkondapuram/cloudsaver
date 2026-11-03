'use client';

import {useEffect, useMemo, useState} from 'react';
import {api} from '../../lib/api';
import {sentence} from '../../lib/resources';
import {useWorkspace} from '../WorkspaceProvider';
import {Loading, Notice, SectionTitle} from '../ui/shared';

type Edge = {from_resource_id: string; to_resource_id: string; relationship?: string; verification_state?: string};
type TopologyItem = {resource_id: string; dependencies: Edge[]; inventory_complete?: boolean};
type SloItem = {resource_id: string; burn_rate?: number; cpu_latency_pearson?: number; blocked_by_latency_sensitivity?: boolean};
type Engine = {status: string; items?: unknown[]; warning?: string; blast_radius_verified?: boolean; change_authorized?: boolean; savings_usd?: null};
type Scenario = {
  warning: string;
  automatic_execution: boolean;
  purchase_authorized: boolean;
  engines: Record<string, Engine>;
};

function edgeClass(state?: string) {
  if (state === 'verified' || state === 'observed') return 'edge-verified';
  if (state === 'stale' || state === 'unavailable') return 'edge-stale';
  return '';
}

export function OptimizationEvidenceWorkspace() {
  const {token, scan} = useWorkspace();
  const [data, setData] = useState<Scenario | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState('');

  useEffect(() => {
    const c = new AbortController();
    setData(null);
    setError('');
    setSelected('');
    if (scan) {
      api<Scenario>('/optimization/scans/' + scan.scan_id + '/auto-scenarios', token, {signal: c.signal})
        .then(r => {
          if (!c.signal.aborted) setData(r);
        })
        .catch(e => {
          if (!c.signal.aborted) setError((e as Error).message);
        });
    }
    return () => c.abort();
  }, [token, scan?.scan_id]);

  const topology = (data?.engines.topology?.items || []) as TopologyItem[];
  const sloItems = (data?.engines.slo?.items || []) as SloItem[];
  const blockedSlo = sloItems.find(i => i.blocked_by_latency_sensitivity || (i.cpu_latency_pearson != null && i.cpu_latency_pearson > 0.6));
  const active = useMemo(() => topology.find(t => t.resource_id === selected) || topology[0], [topology, selected]);

  useEffect(() => {
    if (topology.length && !selected) setSelected(topology[0].resource_id);
  }, [topology, selected]);

  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">MODEL & ATTRIBUTE</div>
          <h1>Optimization evidence</h1>
          <p>Counterfactual simulators use saved scan and billing inputs only. Automatic execution and purchases stay disabled.</p>
        </div>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {!scan ? (
        <Notice>Select a completed live scan to inspect planning inputs.</Notice>
      ) : !data ? (
        <Loading label="Loading planning evidence…" />
      ) : (
        <>
          <Notice>
            {data.warning} · automatic execution: {String(data.automatic_execution)} · purchase authorized:{' '}
            {String(data.purchase_authorized)}
          </Notice>
          {blockedSlo && (
            <div className="slo-correlation-banner blocked-latency" role="status">
              <div>
                <strong>BLOCKED_BY_LATENCY_SENSITIVITY</strong>
                <p className="inline-help">
                  CPU utilization and latency appear correlated on {blockedSlo.resource_id.slice(-24)}. Downsizing requires
                  independent SLO and tail-latency review.
                </p>
              </div>
              <span className="pearson-readout">{blockedSlo.cpu_latency_pearson?.toFixed(2) ?? '> 0.60'} r</span>
            </div>
          )}
          <section className="panel">
            <SectionTitle title="Causal topology simulator">Verified dependency edges from the active scan</SectionTitle>
            <span className="state-badge">{sentence(data.engines.topology?.status || 'unknown')}</span>
            {topology.length === 0 ? (
              <p className="inline-help">No verified in-scan dependency edges. Unverified prerequisites block cascading scenarios.</p>
            ) : (
              <div className="topology-split-view">
                <div className="topology-dag-list" role="list">
                  {topology.map(node => (
                    <button
                      type="button"
                      key={node.resource_id}
                      className={`topology-node-card ${selected === node.resource_id ? 'node-selected' : ''}`}
                      onClick={() => setSelected(node.resource_id)}
                    >
                      <code>{node.resource_id.split('/').slice(-2).join('/')}</code>
                      <span className={`edge-badge ${node.dependencies.length ? 'verified' : 'unavailable'}`}>
                        {node.dependencies.length} edges
                      </span>
                    </button>
                  ))}
                </div>
                <div>
                  <h3>Selected workload edges</h3>
                  {!active?.dependencies.length ? (
                    <Notice tone="warning">No dependency evidence for this node.</Notice>
                  ) : (
                    active.dependencies.map((edge, i) => (
                      <article key={i} className={`topology-node-card node-child ${edgeClass(edge.verification_state)}`}>
                        <span className={`edge-badge ${edgeClass(edge.verification_state) || 'inferred'}`}>
                          {sentence(edge.verification_state || 'inferred')}
                        </span>
                        <p>
                          <code>{edge.from_resource_id.split('/').slice(-1)[0]}</code> →{' '}
                          <code>{edge.to_resource_id.split('/').slice(-1)[0]}</code>
                        </p>
                        <small>{sentence(edge.relationship || 'depends_on')}</small>
                      </article>
                    ))
                  )}
                </div>
              </div>
            )}
          </section>
          {(['slo', 'network', 'commitment'] as const).map(name => {
            const engine = data.engines[name];
            if (!engine) return null;
            return (
              <section className="panel" key={name}>
                <SectionTitle title={sentence(name)}>Observed planning inputs and evidence gaps</SectionTitle>
                <span className="state-badge">{sentence(engine.status)}</span>
                <p>
                  {engine.status === 'insufficient_evidence'
                    ? 'Additional verified observations are required before modeling a change.'
                    : `${engine.items?.length ?? 0} saved observations available for independent review.`}
                </p>
                {engine.warning && <p className="inline-help">{engine.warning}</p>}
              </section>
            );
          })}
        </>
      )}
    </>
  );
}
