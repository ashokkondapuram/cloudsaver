'use client';

import Link from 'next/link';
import {useMemo} from 'react';
import {ArrowRight, Blocks, ChevronRight, ClipboardCheck, FileCode2, Layers, ShieldCheck, Wallet} from 'lucide-react';
import {EvidenceHealth} from './EvidenceHealth';
import {scopeOf} from '../lib/finops';
import {useWorkspace} from './WorkspaceProvider';
import {sentence, useResources} from '../lib/resources';
import {EmptyState, Notice, ProviderBadge, SectionTitle} from './ui/shared';
import styles from './Overview.module.css';

export function useScopedFindings() {
  const {scan, scope} = useWorkspace();
  return useMemo(() => (scan?.findings || []).filter(f => !scope.length || scope.includes(scopeOf(f))), [scan, scope]);
}

const destinations = [
  {href:'/resources', title:'Resources', icon:Blocks, task:'Inspect the evidence', description:'See individual resources, review priorities and missing data across cost, security, reliability, performance and operations.', preview:'Resource inventory · assessment details · team decisions'},
  {href:'/workloads', title:'Workload assessments', icon:Layers, task:'Understand the application', description:'Group resources into workloads, identify owners and dependencies, and assess improvements in their business context.', preview:'Workload ownership · dependencies · improvement plans'},
  {href:'/allocation', title:'Cost allocation', icon:Wallet, task:'Understand the bill', description:'Review imported billing, source coverage and cost attribution. Billing has its own evidence window, separate from scans.', preview:'Billed costs · source freshness · allocation'},
  {href:'/governance', title:'Risk & compliance', icon:ShieldCheck, task:'Record the decision', description:'Assign findings, document business risk and review time-limited exceptions. Accepted risk remains visible.', preview:'Findings · risk owners · exceptions · evidence'},
  {href:'/automation', title:'Automation & GitOps', icon:FileCode2, task:'Prepare a reviewed change', description:'Inspect generated change packages, evaluate Terraform plans and track GitOps requests. Execution requires separate authorization.', preview:'Review packages · plan guardrails · change history'},
  {href:'/outcomes', title:'Savings & investigations', icon:ClipboardCheck, task:'Verify the result', description:'Track savings cases, investigate cost anomalies and compare financial outcomes with supporting evidence.', preview:'Savings lifecycle · anomaly investigations · unit economics'},
];

export function Overview() {
  const {scan, scope, canAdmin, setOverlay, token, busy} = useWorkspace();
  const {page, error, reload} = useResources(scan?.scan_id, token, !!scan && scan.status === 'completed' && scan.data_origin !== 'legacy_synthetic');
  const rows = (page?.items || []).filter(row => !scope.length || scope.includes(row.scope_id));
  const complete = !!page && page.total === page.items.length;
  const reviewCount = rows.filter(row => row.disposition === 'requires_review').length;
  const priorityOrder: Record<string, number> = {critical:0, high:1, medium:2, low:3, none:4};
  const priorities = rows.filter(row => row.disposition === 'requires_review')
    .sort((a, b) => (priorityOrder[a.review_priority] ?? 5) - (priorityOrder[b.review_priority] ?? 5) || a.resource_name.localeCompare(b.resource_name)).slice(0, 3);
  const headline = !scan ? 'Start with your first resource snapshot' : error ? 'Resource evidence needs attention'
    : scan.data_origin === 'legacy_synthetic' ? 'You are viewing a historical snapshot'
    : scan.status !== 'completed' ? 'Your selected scan is not complete'
    : !complete ? 'Loading your workspace summary'
    : reviewCount ? `${reviewCount.toLocaleString()} resource${reviewCount === 1 ? '' : 's'} need${reviewCount === 1 ? 's' : ''} a closer look`
    : 'Explore your resource evidence';
  return <div className={styles.overview}>
    <section className={styles.intro} aria-labelledby="overview-next-step">
      <div><span className="eyebrow">YOUR NEXT STEP</span><h2 id="overview-next-step">{headline}</h2>
        <p>{!scan ? canAdmin ? 'Collect a read-only inventory of your authorized cloud scopes. Then review resources and build a plan.' : 'Ask a workspace administrator to run the first scan. You can explore the workspace sections below.'
          : error ? 'The summary is unavailable. Retry loading the saved evidence before making a decision.'
          : scan.data_origin === 'legacy_synthetic' ? 'Inspect the saved findings in Resources. This snapshot does not provide live assessment coverage.'
          : scan.status !== 'completed' ? 'Choose a completed snapshot above, or refresh the workspace to check scan status.'
          : 'Start in Resources to understand findings and evidence gaps. The sections below explain how to move from review to verified outcomes.'}</p>
        {scope.length > 0 && <span className={styles.scopeNote}>Summary filtered to {scope.length} selected scope{scope.length === 1 ? '' : 's'}.</span>}
      </div>
      {error ? <button className="button secondary" onClick={reload}>Retry evidence</button>
        : !scan && canAdmin ? <button className="button primary" disabled={!!busy} onClick={() => setOverlay('scan')}>Run first scan<ArrowRight size={16}/></button>
        : scan ? <Link className="button primary" href="/resources">Review resources<ArrowRight size={16}/></Link>
        : <Link className="button secondary" href="/settings">View workspace setup<ArrowRight size={16}/></Link>}
    </section>

    <EvidenceHealth rows={rows} ready={complete} error={error}/>
    {error && <Notice tone="error">{error}</Notice>}
    {!complete && page && <Notice>Resource metrics require the complete authorized result set. Narrow the scan before relying on totals.</Notice>}

    {scan && <section className="panel priority-panel" aria-label="Resource review queue">
      <SectionTitle title="Review first" action={<Link className="text-link" href="/resources">View all resources<ArrowRight size={15}/></Link>}>Up to three resources from the selected snapshot, ordered by review priority. These are review candidates, not approved changes.</SectionTitle>
      {!complete ? <div className="empty-state" role="status">{error ? 'The review queue is unavailable until resource evidence can be loaded.' : scan.data_origin === 'legacy_synthetic' ? 'Open Resources to inspect this historical snapshot.' : scan.status !== 'completed' ? 'The selected scan has not completed.' : 'Loading the complete resource review queue…'}</div>
        : priorities.length ? <div className="priority-list">{priorities.map(row => <Link className="priority-row" key={row.resource_key} href={`/resources?resource=${row.resource_key}`}>
          <span className={`resource-symbol resource-${row.provider}`}><Blocks size={18}/></span>
          <span className="priority-resource"><strong>{row.resource_name}</strong><small>{row.finding_count} rule signal{row.finding_count === 1 ? '' : 's'} · {sentence(row.review_priority)} priority</small></span>
          <ProviderBadge provider={row.provider}/><ChevronRight size={15}/>
        </Link>)}</div>
        : <EmptyState icon={ShieldCheck} title="No resources require review in this view">Review evidence gaps and the rest of your inventory in Resources. This does not establish that every control passed.</EmptyState>}
    </section>}

    <section className={styles.guide} aria-labelledby="workspace-guide-title">
      <div className={styles.guideHeading}><span className="eyebrow">FIND YOUR WAY</span><h2 id="workspace-guide-title">What you can do in each section</h2><p>Choose the question you want to answer. Each section keeps its own evidence, access requirements and workflow.</p></div>
      <div className={styles.destinations}>{destinations.map(({href, title, icon:Icon, task, description, preview}, index) => <Link className={styles.destination} key={href} href={href}>
        <div className={styles.destinationTop}><span className={styles.destinationIcon}><Icon size={20}/></span><span>{String(index + 1).padStart(2, '0')}</span></div>
        <h3>{title}</h3><strong>{task}</strong><p>{description}</p><small>{preview}</small><span className={styles.openSection}>Open {title}<ArrowRight size={15}/></span>
      </Link>)}</div>
      <p className={styles.guideFootnote}>Specialist tools contains Services, Kubernetes, Optimization evidence and Agent worker. Activity & delivery shows scan history and notification status. Use Settings for cloud scopes, analysis rules, AI policy and access.</p>
    </section>
  </div>;
}
