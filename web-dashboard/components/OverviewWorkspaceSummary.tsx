'use client';

import {useEffect, useMemo, useState} from 'react';
import {
  ClipboardText,
  FileCode,
  Pulse,
  Robot,
  SealCheck,
  Sparkle,
  SquaresFour,
  Warning,
  Wallet,
} from '@phosphor-icons/react';
import {api} from '../lib/api';
import {overviewWorkspaceTabs} from '../lib/workspace-tab-leads';
import {sentence} from '../lib/resources';
import type {Reliability} from '../lib/types';
import type {Summary as GovernanceSummary} from './governance/types';
import {useWorkspace} from './WorkspaceProvider';
import {TabWorkspaceShell} from './ui/TabWorkspaceShell';
import {EmptyState, Loading, Notice, SectionTitle} from './ui/shared';
import styles from './Overview.module.css';

type OutcomesSummary = {
  implemented_cases: number;
  validated_cases: number;
  validated_outcome_pct: number | null;
  unsupported_financial_claims: number;
  warning: string;
};
type OutcomesMetrics = {
  investigations: number;
  unassigned: number;
  actionable_resolved_pct: number | null;
  warning: string;
};
type GovCaps = {readable: boolean};
type AgentTask = {state: string};
type ObsSummaryItem = {id: string; status: string};
type GitOpsReview = {status: string};
type AiGovView = {
  counts: {[key: string]: number};
  active_holds: unknown[];
  policy: {status: string; processors: unknown[]};
};
type K8sView = {
  clusters: unknown[];
  resources: {evaluations: {outcome: string}[]}[];
};

function formatPercent0to100(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${Number(value).toFixed(0)}%`;
}

function deliveryDeadLetters(counts: Reliability['counts']) {
  return counts.filter(c => c.status === 'dead_letter').reduce((s, c) => s + c.count, 0);
}

function taskStateCounts(items: AgentTask[]) {
  const map = new Map<string, number>();
  for (const t of items) {
    const k = t.state || 'unknown';
    map.set(k, (map.get(k) ?? 0) + 1);
  }
  return [...map.entries()].sort((a, b) => b[1] - a[1]);
}

function observabilityStatusCounts(items: ObsSummaryItem[]) {
  const map = new Map<string, number>();
  for (const i of items) {
    const k = i.status || 'unknown';
    map.set(k, (map.get(k) ?? 0) + 1);
  }
  return [...map.entries()].sort((a, b) => b[1] - a[1]);
}

export function OverviewWorkspaceSummary() {
  const {token, scan, canBill} = useWorkspace();
  const [tab, setTab] = useState(overviewWorkspaceTabs[0].id);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [reliability, setReliability] = useState<Reliability | null>(null);
  const [governance, setGovernance] = useState<{summary: GovernanceSummary} | null>(null);
  const [governanceDenied, setGovernanceDenied] = useState(false);
  const [outcomes, setOutcomes] = useState<{summary: OutcomesSummary; metrics: OutcomesMetrics} | null>(null);
  const [agents, setAgents] = useState<{enabled: boolean; tasks: AgentTask[]} | null>(null);
  const [observability, setObservability] = useState<ObsSummaryItem[] | null>(null);
  const [gitops, setGitops] = useState<GitOpsReview[] | null>(null);
  const [aiGov, setAiGov] = useState<AiGovView | null>(null);
  const [k8s, setK8s] = useState<K8sView | null>(null);

  useEffect(() => {
    const request = new AbortController();
    const {signal} = request;
    setBusy(true);
    setError('');
    setReliability(null);
    setGovernance(null);
    setGovernanceDenied(false);
    setOutcomes(null);
    setAgents(null);
    setObservability(null);
    setGitops(null);
    setAiGov(null);
    setK8s(null);

    const runs: Promise<unknown>[] = [];

    runs.push(
      api<Reliability>('/operations/reliability', token, {signal}).then(r => {
        if (!signal.aborted) setReliability(r);
      }),
    );

    runs.push(
      api<GovCaps>('/governance/capabilities', token, {signal})
        .then(async caps => {
          if (signal.aborted) return;
          if (!caps.readable) {
            setGovernanceDenied(true);
            return;
          }
          const summary = await api<GovernanceSummary>('/governance/summary', token, {signal});
          if (!signal.aborted) setGovernance({summary});
        })
        .catch(() => {
          if (!signal.aborted) setGovernanceDenied(true);
        }),
    );

    runs.push(
      api<{items: ObsSummaryItem[]}>('/observability/summary', token, {signal})
        .then(r => {
          if (!signal.aborted) setObservability(r.items);
        })
        .catch(() => {
          if (!signal.aborted) setObservability([]);
        }),
    );

    runs.push(
      Promise.all([
        api<{enabled: boolean}>('/agents/catalog', token, {signal}).catch(() => ({enabled: false})),
        api<{items: AgentTask[]}>('/agents/tasks', token, {signal}).catch(() => ({items: [] as AgentTask[]})),
      ]).then(([catalog, tasks]) => {
        if (!signal.aborted) setAgents({enabled: catalog.enabled, tasks: tasks.items});
      }),
    );

    runs.push(
      api<GitOpsReview[]>('/gitops/requests', token, {signal})
        .then(rows => {
          if (!signal.aborted) setGitops(rows);
        })
        .catch(() => {
          if (!signal.aborted) setGitops([]);
        }),
    );

    runs.push(
      api<AiGovView>('/ai/governance', token, {signal})
        .then(v => {
          if (!signal.aborted) setAiGov(v);
        })
        .catch(() => {
          if (!signal.aborted) setAiGov(null);
        }),
    );

    if (canBill) {
      runs.push(
        Promise.all([
          api<OutcomesSummary>('/outcomes/summary', token, {signal}),
          api<OutcomesMetrics>('/outcomes/anomalies/metrics', token, {signal}),
        ])
          .then(([summary, metrics]) => {
            if (!signal.aborted) setOutcomes({summary, metrics});
          })
          .catch(() => {
            if (!signal.aborted) setOutcomes(null);
          }),
      );
    }

    if (scan?.status === 'completed') {
      runs.push(
        api<K8sView>(`/scans/${scan.scan_id}/kubernetes`, token, {signal})
          .then(v => {
            if (!signal.aborted) setK8s(v);
          })
          .catch(() => {
            if (!signal.aborted) setK8s(null);
          }),
      );
    }

    Promise.allSettled(runs)
      .then(() => {
        if (!signal.aborted) setBusy(false);
      })
      .catch(cause => {
        if (!signal.aborted) {
          setBusy(false);
          setError((cause as Error).message);
        }
      });

    return () => request.abort();
  }, [token, scan?.scan_id, scan?.status, canBill]);

  const deadLetters = reliability ? deliveryDeadLetters(reliability.counts) : 0;
  const assessmentEntries = useMemo(() => {
    const raw = governance?.summary.assessment_results;
    if (!raw) return [];
    return Object.entries(raw)
      .filter(([, n]) => typeof n === 'number' && n > 0)
      .sort((a, b) => b[1] - a[1]);
  }, [governance]);
  const assessmentMax = assessmentEntries.length ? Math.max(...assessmentEntries.map(([, n]) => n)) : 0;

  const k8sStats = useMemo(() => {
    if (!k8s) return null;
    const flagged = k8s.resources.filter(r => r.evaluations?.some(e => e.outcome === 'condition_detected')).length;
    return {clusters: k8s.clusters.length, resources: k8s.resources.length, flagged};
  }, [k8s]);

  const gitopsByStatus = useMemo(() => {
    if (!gitops) return [];
    const map = new Map<string, number>();
    for (const r of gitops) {
      const k = r.status || 'unknown';
      map.set(k, (map.get(k) ?? 0) + 1);
    }
    return [...map.entries()].sort((a, b) => b[1] - a[1]);
  }, [gitops]);

  if (busy) {
    return (
      <section className={`panel ${styles.workspaceSummary}`} aria-label="Workspace summary" data-atlas-rollout="overview-workspace-summary">
        <SectionTitle title="Across the workspace" eyebrow="SNAPSHOT" />
        <Loading label="Loading workspace signals…" />
      </section>
    );
  }

  return (
    <section className={`panel ${styles.workspaceSummary}`} aria-label="Workspace summary" data-atlas-rollout="overview-workspace-summary">
      <SectionTitle title="Across the workspace" eyebrow="SNAPSHOT" />
      {error ? <Notice tone="error">{error}</Notice> : null}

      <TabWorkspaceShell
        id="overview-summary"
        label="Workspace overview sections"
        tabs={overviewWorkspaceTabs}
        value={tab}
        onChange={setTab}
        className="overview-workspace-tab-shell"
      >
        {tab === 'operations' && (
          <>
            <section className="panel">
              <SectionTitle title="Notifications &amp; delivery" />
              {reliability ? (
                <div className="allocation-metrics">
                  <article className="metric-card">
                    <div className="metric-label">
                      Failed deliveries
                      <Pulse size={17} weight="regular" />
                    </div>
                    <strong>{deadLetters.toLocaleString()}</strong>
                    <p className="metric-footnote">
                      <span className="small-dot" aria-hidden />
                      Dispatcher {reliability.dispatcher_enabled ? 'enabled' : 'disabled'}
                    </p>
                  </article>
                  <article className="metric-card">
                    <div className="metric-label">
                      Queue kinds
                      <Pulse size={17} weight="regular" />
                    </div>
                    <strong>{reliability.counts.length ? reliability.counts.length.toLocaleString() : '—'}</strong>
                    <p className="metric-footnote">Tracked notification categories</p>
                  </article>
                </div>
              ) : (
                <EmptyState icon={Pulse} title="Delivery metrics unavailable" />
              )}
            </section>
            <section className="panel">
              <SectionTitle title="Observability connectors" />
              {observability ? (
                <>
                  <div className="allocation-metrics">
                    <article className="metric-card metric-featured">
                      <div className="metric-label">
                        Connector summaries
                        <Pulse size={17} weight="regular" />
                      </div>
                      <strong>{observability.length.toLocaleString()}</strong>
                      <p className="metric-footnote">From Settings → Integrations</p>
                    </article>
                  </div>
                  {observabilityStatusCounts(observability).length > 0 && (
                    <ul className={styles.workspacePillList} aria-label="Observability sync status">
                      {observabilityStatusCounts(observability).map(([status, count]) => (
                        <li key={status}>
                          <span>{sentence(status)}</span>
                          <span>{count.toLocaleString()}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              ) : (
                <EmptyState icon={Pulse} title="Observability summary unavailable" />
              )}
            </section>
          </>
        )}

        {tab === 'finance' &&
          (canBill && outcomes ? (
            <section className="panel">
              <SectionTitle title="Savings &amp; investigations" />
              <div className="allocation-metrics">
                <article className="metric-card">
                  <div className="metric-label">
                    Implemented cases
                    <ClipboardText size={17} weight="regular" />
                  </div>
                  <strong>{outcomes.summary.implemented_cases.toLocaleString()}</strong>
                </article>
                <article className="metric-card metric-featured">
                  <div className="metric-label">
                    Validated cases
                    <SealCheck size={17} weight="regular" />
                  </div>
                  <strong>{outcomes.summary.validated_cases.toLocaleString()}</strong>
                  <p className="metric-footnote">{formatPercent0to100(outcomes.summary.validated_outcome_pct)} outcome rate</p>
                </article>
                <article className="metric-card">
                  <div className="metric-label">
                    Cost investigations
                    <ClipboardText size={17} weight="regular" />
                  </div>
                  <strong>{outcomes.metrics.investigations.toLocaleString()}</strong>
                  <p className="metric-footnote">
                    {outcomes.metrics.unassigned.toLocaleString()} unassigned ·{' '}
                    {formatPercent0to100(outcomes.metrics.actionable_resolved_pct)} actionable resolved
                  </p>
                </article>
              </div>
              {(outcomes.summary.warning || outcomes.metrics.warning) && (
                <Notice tone="warning">{outcomes.summary.warning || outcomes.metrics.warning}</Notice>
              )}
            </section>
          ) : (
            <EmptyState icon={Wallet} title="Finance workspace not in this view">
              Savings and investigation metrics need finance access on your workspace role.
            </EmptyState>
          ))}

        {tab === 'governance' && (
          <section className="panel">
            <SectionTitle title="Risk &amp; compliance" />
            {governance ? (
              <>
                <div className="allocation-metrics">
                  <article className="metric-card">
                    <div className="metric-label">
                      Open material risks
                      <Warning size={17} weight="regular" />
                    </div>
                    <strong>{governance.summary.open_material_risks.toLocaleString()}</strong>
                  </article>
                  <article className="metric-card">
                    <div className="metric-label">
                      Overdue findings
                      <SealCheck size={17} weight="regular" />
                    </div>
                    <strong>{governance.summary.overdue_findings.toLocaleString()}</strong>
                  </article>
                  <article className="metric-card">
                    <div className="metric-label">
                      Expiring exceptions
                      <SealCheck size={17} weight="regular" />
                    </div>
                    <strong>{governance.summary.expiring_exceptions.toLocaleString()}</strong>
                  </article>
                  <article className="metric-card">
                    <div className="metric-label">
                      Stale evidence
                      <Warning size={17} weight="regular" />
                    </div>
                    <strong>{governance.summary.stale_evidence.toLocaleString()}</strong>
                  </article>
                </div>
                {assessmentEntries.length > 0 && (
                  <div className={styles.workspaceBarChart} aria-label="Governance assessments by result">
                    <div className={styles.workspaceBarChartTitle}>Assessments by result</div>
                    <ul className={styles.workspaceBarList}>
                      {assessmentEntries.slice(0, 6).map(([label, count]) => (
                        <li key={label}>
                          <span className={styles.workspaceBarLabel}>{sentence(label)}</span>
                          <div className={styles.workspaceBarTrack} aria-hidden>
                            <span
                              className={styles.workspaceBarFill}
                              style={{width: `${assessmentMax ? (100 * count) / assessmentMax : 0}%`}}
                            />
                          </div>
                          <span className={styles.workspaceBarValue}>{count.toLocaleString()}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {governance.summary.warning ? <Notice tone="warning">{governance.summary.warning}</Notice> : null}
              </>
            ) : governanceDenied ? (
              <EmptyState icon={SealCheck} title="Governance access required">
                Ask your workspace administrator to delegate a governance role to see this summary.
              </EmptyState>
            ) : (
              <EmptyState icon={SealCheck} title="Governance summary unavailable" />
            )}
          </section>
        )}

        {tab === 'change' && (
          <>
            <section className="panel">
              <SectionTitle title="Automation &amp; GitOps" />
              {gitops ? (
                <>
                  <div className="allocation-metrics">
                    <article className="metric-card metric-featured">
                      <div className="metric-label">
                        Review requests
                        <FileCode size={17} weight="regular" />
                      </div>
                      <strong>{gitops.length.toLocaleString()}</strong>
                      <p className="metric-footnote">Publication history for this workspace</p>
                    </article>
                  </div>
                  {gitopsByStatus.length > 0 && (
                    <ul className={styles.workspacePillList} aria-label="GitOps requests by status">
                      {gitopsByStatus.map(([status, count]) => (
                        <li key={status}>
                          <span className="state-badge">{sentence(status)}</span>
                          <span>{count.toLocaleString()}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              ) : (
                <EmptyState icon={FileCode} title="GitOps history could not be loaded" />
              )}
            </section>
            <section className="panel">
              <SectionTitle title="Agent worker" />
              {agents ? (
                <>
                  <div className="allocation-metrics">
                    <article className="metric-card">
                      <div className="metric-label">
                        Catalog
                        <Robot size={17} weight="regular" />
                      </div>
                      <strong className={agents.enabled ? '' : 'metric-unknown'}>{agents.enabled ? 'Enabled' : 'Disabled'}</strong>
                    </article>
                    <article className="metric-card">
                      <div className="metric-label">
                        Tasks
                        <Robot size={17} weight="regular" />
                      </div>
                      <strong>{agents.tasks.length.toLocaleString()}</strong>
                    </article>
                  </div>
                  {taskStateCounts(agents.tasks).length > 0 && (
                    <ul className={styles.workspacePillList} aria-label="Agent tasks by state">
                      {taskStateCounts(agents.tasks)
                        .slice(0, 5)
                        .map(([state, count]) => (
                          <li key={state}>
                            <span>{sentence(state)}</span>
                            <span>{count.toLocaleString()}</span>
                          </li>
                        ))}
                    </ul>
                  )}
                </>
              ) : (
                <EmptyState icon={Robot} title="Agent workspace unavailable" />
              )}
            </section>
            <section className="panel">
              <SectionTitle title="Kubernetes" />
              {scan?.status !== 'completed' ? (
                <p className="inline-help">Statistics appear when the selected snapshot completes.</p>
              ) : k8sStats ? (
                k8sStats.clusters || k8sStats.resources ? (
                  <div className="allocation-metrics">
                    <article className="metric-card">
                      <div className="metric-label">
                        Clusters
                        <SquaresFour size={17} weight="regular" />
                      </div>
                      <strong>{k8sStats.clusters.toLocaleString()}</strong>
                    </article>
                    <article className="metric-card">
                      <div className="metric-label">
                        Resources
                        <SquaresFour size={17} weight="regular" />
                      </div>
                      <strong>{k8sStats.resources.toLocaleString()}</strong>
                    </article>
                    <article className="metric-card">
                      <div className="metric-label">
                        Flagged for review
                        <Warning size={17} weight="regular" />
                      </div>
                      <strong>{k8sStats.flagged.toLocaleString()}</strong>
                      <p className="metric-footnote">Condition detected on rules</p>
                    </article>
                  </div>
                ) : (
                  <EmptyState icon={SquaresFour} title="No Kubernetes inventory in this snapshot" />
                )
              ) : (
                <EmptyState icon={SquaresFour} title="Kubernetes evidence unavailable" />
              )}
            </section>
          </>
        )}

        {tab === 'ai' && (
          <section className="panel">
            <SectionTitle title="AI data governance" />
            {aiGov ? (
              <div className="allocation-metrics">
                <article className="metric-card">
                  <div className="metric-label">
                    Policy
                    <Sparkle size={17} weight="regular" />
                  </div>
                  <strong className="metric-unknown">{sentence(aiGov.policy.status)}</strong>
                </article>
                <article className="metric-card">
                  <div className="metric-label">
                    Approved processors
                    <Sparkle size={17} weight="regular" />
                  </div>
                  <strong>{aiGov.policy.processors.length.toLocaleString()}</strong>
                </article>
                <article className="metric-card metric-featured">
                  <div className="metric-label">
                    Allowed / blocked
                    <Sparkle size={17} weight="regular" />
                  </div>
                  <strong>
                    {(aiGov.counts.allowed ?? 0).toLocaleString()} / {(aiGov.counts.blocked ?? 0).toLocaleString()}
                  </strong>
                  <p className="metric-footnote">Active legal holds: {aiGov.active_holds.length}</p>
                </article>
              </div>
            ) : (
              <EmptyState icon={Sparkle} title="AI data governance could not be loaded" />
            )}
          </section>
        )}
      </TabWorkspaceShell>
    </section>
  );
}
