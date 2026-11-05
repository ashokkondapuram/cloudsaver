'use client';

import type {ResourceRow} from '../lib/resources';
import {useWorkspace} from './WorkspaceProvider';
import styles from './Overview.module.css';

export function EvidenceHealth({rows, total, ready, error}: {rows: ResourceRow[]; total?: number; ready: boolean; error: string}) {
  const {scan, scope} = useWorkspace();
  const supported = scan?.status === 'completed' && scan.data_origin !== 'legacy_synthetic';
  const known = supported && ready && !error;
  const resourceTotal = total ?? rows.length;
  const status = !scan ? 'No snapshot' : !supported ? 'Unavailable' : error ? 'Unavailable' : !ready ? 'Loading…' : `${resourceTotal.toLocaleString()} resources`;
  const missing = rows.filter(row => row.evidence_coverage.observed < row.evidence_coverage.total || row.evidence_gap_codes.length > 0).length;
  return <section className={`${styles.evidence} cs-evidence-health`} aria-label="Evidence health">
    <div className={styles.metrics}>
      <article><h3>Resources in view</h3><strong role="status">{status}</strong><p>{scope.length ? 'Selected scopes' : 'Authorized snapshot'}</p></article>
      <article><h3>Need review</h3><strong>{known ? rows.filter(row => row.disposition === 'requires_review').length.toLocaleString() : '—'}</strong><p>Have findings to investigate</p></article>
      <article><h3>Evidence gaps</h3><strong>{known ? missing.toLocaleString() : '—'}</strong><p>Missing coverage, not a passing check</p></article>
    </div>
  </section>;
}
