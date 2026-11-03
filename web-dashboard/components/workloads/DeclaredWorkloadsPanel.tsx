'use client';
import {useEffect, useState} from 'react';
import {Layers, RefreshCw} from 'lucide-react';
import {api} from '../../lib/api';
import type {DeclaredWorkload} from '../../lib/control-plane';
import {EmptyState, Loading, Notice, SectionTitle} from '../ui/shared';

export function DeclaredWorkloadsPanel({token}: {token: string; canEdit: boolean}) {
  const [items, setItems] = useState<DeclaredWorkload[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    api<{items: DeclaredWorkload[]; next_cursor: string | null}>('/engineering/workloads?limit=50', token, {
      signal: controller.signal,
    })
      .then(res => {
        if (!controller.signal.aborted) setItems(res.items);
      })
      .catch(err => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Declared workloads could not be loaded.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [token, revision]);

  return (
    <section className="panel" aria-label="Declared engineering workloads">
      <SectionTitle
        title="Declared engineering workloads"
        action={
          <button type="button" className="button secondary small" disabled={loading} onClick={() => setRevision(r => r + 1)}>
            <RefreshCw size={14} /> Refresh
          </button>
        }
      >
        Persisted workload boundaries, SLO and recovery references, and version-fenced readiness declarations. Declarations
        provide context and never fabricate measured telemetry.
      </SectionTitle>
      {loading && <Loading label="Loading declared engineering workloads…" />}
      {error && <Notice tone="error">{error}</Notice>}
      {!loading && !error && items.length === 0 && (
        <EmptyState icon={Layers} title="No declared workloads in this workspace">
          Use Engineering plans below to declare application workloads with owner, environment, and recovery references for
          action-safety checks (AG-HA-01, AG-DR-01, AG-OPS-01).
        </EmptyState>
      )}
      {items.length > 0 && (
        <div className="summary-table-scroll">
          <table className="summary-table">
            <thead>
              <tr>
                <th>Workload / environment</th>
                <th>Provider & scope</th>
                <th>Owner & team</th>
                <th>SLO / peak / recovery refs</th>
                <th className="number">Version (If-Match)</th>
              </tr>
            </thead>
            <tbody>
              {items.map(w => (
                <tr key={w.id}>
                  <td>
                    <strong>{w.name}</strong>
                    <small className="cell-sub">{w.environment}</small>
                  </td>
                  <td>
                    <span className={`provider-badge provider-${w.provider}`}>
                      <span /> {w.provider}
                    </span>
                    <small className="cell-sub">
                      <code>{w.scope_id}</code>
                    </small>
                  </td>
                  <td>
                    {w.owner}
                    <small className="cell-sub">{w.team}</small>
                  </td>
                  <td>
                    {Object.values(w.requirements || {}).some(Boolean) ? (
                      <div className="badge-row">
                        {Object.entries(w.requirements).map(([k, v]) =>
                          v ? (
                            <span key={k} className="state-badge active">
                              {k.replace('_reference', '')}
                            </span>
                          ) : null,
                        )}
                      </div>
                    ) : (
                      <span className="state-badge legacy">Missing references</span>
                    )}
                  </td>
                  <td className="number">
                    <code>v{w.version}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
