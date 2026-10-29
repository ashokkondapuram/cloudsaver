'use client';

import type {ResourceRow} from '../lib/resources';
import {useWorkspace} from './WorkspaceProvider';
import styles from './Overview.module.css';

export function EvidenceHealth({rows, ready, error}: {rows: ResourceRow[]; ready: boolean; error: string}) {
  const {scan, scope} = useWorkspace();
  const supported = scan?.status === 'completed' && scan.data_origin !== 'legacy_synthetic';
  const known = supported && ready && !error;
  const status = !scan ? 'No snapshot' : !supported ? 'Unavailable' : error ? 'Unavailable' : !ready ? 'Loading…' : `${rows.length.toLocaleString()} resources`;
  const missing = rows.filter(row => row.evidence_coverage.observed < row.evidence_coverage.total || row.evidence_gap_codes.length > 0).length;
  const observed = rows.reduce((sum, row) => sum + row.evidence_coverage.observed, 0);
  const total = rows.reduce((sum, row) => sum + row.evidence_coverage.total, 0);
  return <section className={styles.evidence} aria-label="Evidence health">
    <div className={styles.metrics}>
      <article><h3>Resources in view</h3><strong role="status">{status}</strong><p>{scope.length ? 'Within your selected scopes' : 'Within the selected authorized snapshot'}</p></article>
      <article><h3>Need review</h3><strong>{known ? rows.filter(row => row.disposition === 'requires_review').length.toLocaleString() : '—'}</strong><p>Resources with findings to investigate</p></article>
      <article><h3>Evidence gaps</h3><strong>{known ? missing.toLocaleString() : '—'}</strong><p>{known ? `${missing.toLocaleString()} resources have evidence gaps` : 'Coverage is not yet available'}</p></article>
    </div>
    <p className={styles.evidenceNote}>{known ? total ? `${observed.toLocaleString()} / ${total.toLocaleString()} checks have observed evidence. ` : 'No assessment checks recorded. ' : 'A complete supported inventory is required to summarize coverage. '}Missing evidence is not a passing check. Resource estimates are not verified savings.</p>
  </section>;
}
