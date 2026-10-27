'use client';

import Link from 'next/link';
import type {ResourceRow} from '../lib/resources';
import {useWorkspace} from './WorkspaceProvider';
import {SectionTitle} from './ui/shared';

export function EvidenceHealth({rows, ready, error}: {rows: ResourceRow[]; ready: boolean; error: string}) {
  const {scan, canAdmin, canBill, scope, setOverlay} = useWorkspace();
  const supported = scan?.status === 'completed' && scan.data_origin !== 'legacy_synthetic';
  const status = !scan ? 'Not collected' : !supported ? 'Live inventory unavailable' : error ? 'Unavailable' : !ready ? 'Loading evidence…' : `${rows.length.toLocaleString()} resources`;
  const missing = ready ? rows.filter(row => row.evidence_coverage.observed < row.evidence_coverage.total || row.evidence_gap_codes.length > 0).length : null;
  const observed = ready ? rows.reduce((sum, row) => sum + row.evidence_coverage.observed, 0) : null;
  const total = ready ? rows.reduce((sum, row) => sum + row.evidence_coverage.total, 0) : null;
  return <section className="panel evidence-health" aria-label="Evidence health">
    <SectionTitle title="Evidence health" eyebrow="START WITH WHAT IS KNOWN">{scope.length ? 'Selected resource scopes' : 'Complete authorized snapshot'} · coverage is separate from risk.</SectionTitle>
    <div className="evidence-health-grid">
      <article><span>Resource inventory</span><strong role="status">{status}</strong><p>{scan ? `Snapshot status: ${scan.status}. Billing synchronization is independent.` : 'Connect authorized scopes and collect your first observation.'}</p>{!scan && canAdmin ? <button className="text-button" onClick={() => setOverlay('scan')}>Run first scan →</button> : <Link className="text-link" href="/resources">Inspect resources →</Link>}</article>
      <article><span>Assessment evidence</span><strong>{observed === null ? 'Not available' : total === 0 ? 'No checks recorded' : `${observed.toLocaleString()} / ${total!.toLocaleString()} checks`}</strong><p>{missing === null ? 'Coverage requires a complete supported inventory.' : `${missing.toLocaleString()} resources have evidence gaps. An observed risk still counts as evidence.`}</p><Link className="text-link" href="/settings?tab=rules">Inspect analysis rules →</Link></article>
      <article><span>Financial evidence</span><strong>Separate billing window</strong><p>Resource retail estimates are not an invoice or verified savings. Review source coverage and currency before comparing costs.</p><Link className="text-link" href="/allocation">{canBill ? 'Review billing evidence' : 'View finance access requirements'} →</Link></article>
    </div>
    <div className="evidence-next-steps" aria-label="Improvement workflow">
      <Link href="/workloads">1. Understand workloads</Link><Link href="/resources">2. Review evidence</Link><Link href="/governance">3. Review risk & approvals</Link><Link href="/outcomes">4. Verify outcomes</Link>
    </div>
  </section>;
}
