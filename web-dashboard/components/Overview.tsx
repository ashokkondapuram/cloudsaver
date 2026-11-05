'use client';

import Link from 'next/link';
import {useMemo} from 'react';
import {ArrowRight, Blocks, ChevronRight, ShieldCheck} from 'lucide-react';
import {EvidenceHealth} from './EvidenceHealth';
import {scopeOf} from '../lib/finops';
import {useWorkspace} from './WorkspaceProvider';
import {sentence, isLiveSnapshot, useResources, type Summary} from '../lib/resources';
import {EmptyState, Notice, ProviderBadge, SectionTitle} from './ui/shared';
import styles from './Overview.module.css';
import {OverviewFinOpsMiniChart} from './OverviewFinOpsMiniChart';

export function useScopedFindings() {
  const {scan, scope} = useWorkspace();
  return useMemo(() => (scan?.findings || []).filter(f => !scope.length || scope.includes(scopeOf(f))), [scan, scope]);
}

function reviewTotal(summary: Summary | undefined, scopedRows: {disposition: string}[]) {
  if (summary?.review_priority) {
    const counts = summary.review_priority;
    return (counts.critical ?? 0) + (counts.high ?? 0) + (counts.evidence_required ?? 0);
  }
  return scopedRows.filter(row => row.disposition === 'requires_review').length;
}

export function Overview() {
  const {scan, scope, canAdmin, setOverlay, token, busy, scanActivity, liveScanEpoch} = useWorkspace();
  const live = isLiveSnapshot(scan);
  const inProgress = scan?.status === 'running';
  const {page, error, reload} = useResources(scan?.scan_id, token, live, inProgress ? liveScanEpoch : 0, {running: inProgress, overview: !inProgress});
  const rows = (page?.items || []).filter(row => !scope.length || scope.includes(row.scope_id));
  const complete = !!page && (inProgress || page.total === page.items.length || (live && !inProgress));
  const reviewCount = reviewTotal(page?.summary, rows);
  const priorityOrder: Record<string, number> = {critical:0, high:1, medium:2, low:3, none:4};
  const priorities = rows.filter(row => row.disposition === 'requires_review')
    .sort((a, b) => (priorityOrder[a.review_priority] ?? 5) - (priorityOrder[b.review_priority] ?? 5) || a.resource_name.localeCompare(b.resource_name)).slice(0, 3);
  const headline = !scan ? 'Start with your first resource snapshot' : error ? 'Resource evidence needs attention'
    : scan.data_origin === 'legacy_synthetic' ? 'Viewing a historical snapshot'
    : inProgress ? 'Scan in progress — evidence updates as resources are collected'
    : scan.status !== 'completed' ? 'Your selected scan is not complete'
    : !complete ? 'Loading your workspace summary'
    : reviewCount ? `${reviewCount.toLocaleString()} resource${reviewCount === 1 ? '' : 's'} need${reviewCount === 1 ? 's' : ''} a closer look`
    : 'Explore your resource evidence';
  return <div className={styles.overview} data-atlas-rollout="overview">
    <section className={styles.intro} aria-labelledby="overview-next-step">
      <div><h2 id="overview-next-step">{headline}</h2>{scope.length > 0 && <span className={styles.scopeNote}>Filtered to {scope.length} selected scope{scope.length === 1 ? '' : 's'}</span>}</div>
      {error ? <button className="button secondary" onClick={reload}>Retry evidence</button>
        : !scan && canAdmin ? <button className="button primary" disabled={!!scanActivity} onClick={() => setOverlay('scan')}>Run first scan<ArrowRight size={16}/></button>
        : scan ? <Link className="button primary" href="/resources">Review resources<ArrowRight size={16}/></Link>
        : <Link className="button secondary" href="/settings">View workspace setup<ArrowRight size={16}/></Link>}
    </section>

    <EvidenceHealth rows={rows} total={page?.total} ready={complete} error={error}/>
    {error && <Notice tone="error">{error}</Notice>}

    <OverviewFinOpsMiniChart/>

    {scan && <section className="panel priority-panel" aria-label="Resource review queue">
      <SectionTitle title="Review first" action={<Link className="text-link" href="/resources">View all<ArrowRight size={15}/></Link>}/>
      {!complete ? <div className="empty-state" role="status">{error ? 'Unavailable until evidence loads.' : inProgress && !rows.length ? 'Resources will appear here as they are collected.' : 'Loading…'}</div>
        : priorities.length ? <div className="priority-list">{priorities.map(row => <Link className="priority-row" key={row.resource_key} href={`/resources?resource=${row.resource_key}`}>
          <span className={`resource-symbol resource-${row.provider}`}><Blocks size={18}/></span>
          <span className="priority-resource"><strong>{row.resource_name}</strong><small>{row.finding_count} signal{row.finding_count === 1 ? '' : 's'} · {sentence(row.review_priority)}</small></span>
          <ProviderBadge provider={row.provider}/><ChevronRight size={15}/>
        </Link>)}</div>
        : <EmptyState icon={ShieldCheck} title="Nothing needs review right now"/>}
    </section>}
  </div>;
}
