'use client';

import Link from 'next/link';
import {useCallback, useEffect, useMemo, useState} from 'react';
import {
  ClipboardText,
  FileCode,
  Kanban,
  Pulse,
  SealCheck,
  Sparkle,
  Wallet,
} from '@phosphor-icons/react';
import {api} from '../lib/api';
import type {Reliability} from '../lib/types';
import type {Summary as GovernanceSummary} from './governance/types';
import {governanceTabQuery} from '../lib/governance-tabs';
import {
  agentInFlightCount,
  gitopsOpenCount,
  observabilityIssueCount,
  taskStateCounts,
  type AgentTask,
  type GitOpsReview,
  type ObsSummaryItem,
} from '../lib/action-center-metrics';
import {
  classifySourceError,
  partialSourceFailures,
  successState,
  unavailableState,
  type SourceState,
} from '../lib/source-state';
import {useWorkspace} from './WorkspaceProvider';
import {Loading, Notice, SectionTitle} from './ui/shared';

type OutcomesMetrics = {
  investigations: number;
  open_investigations?: number;
  unassigned: number;
  actionable_resolved_pct: number | null;
  warning: string;
};
type GovCaps = {readable: boolean};
type AiGovView = {
  counts: Record<string, number>;
  active_holds: unknown[];
  policy: {status: string; processors: unknown[]};
};
type AgentBundle = {enabled: boolean; tasks: AgentTask[]};

function deliveryDeadLetters(counts: Reliability['counts']) {
  return counts.filter(c => c.status === 'dead_letter').reduce((s, c) => s + c.count, 0);
}

type SwimLane = {
  id: string;
  title: string;
  hint: string;
  tone: 'urgent' | 'queue' | 'progress' | 'watch';
  items: {label: string; count?: number; href: string; note?: string}[];
};

const REFRESH_MS = 120_000;

export function ActionCenterView() {
  const {token, scan, canBill} = useWorkspace();
  const [revision, setRevision] = useState(0);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [reliability, setReliability] = useState<SourceState<Reliability>>({status: 'loading'});
  const [governance, setGovernance] = useState<SourceState<{summary: GovernanceSummary}>>({status: 'loading'});
  const [outcomes, setOutcomes] = useState<SourceState<OutcomesMetrics>>({status: 'loading'});
  const [agents, setAgents] = useState<SourceState<AgentBundle>>({status: 'loading'});
  const [observability, setObservability] = useState<SourceState<ObsSummaryItem[]>>({status: 'loading'});
  const [gitops, setGitops] = useState<SourceState<GitOpsReview[]>>({status: 'loading'});
  const [aiGov, setAiGov] = useState<SourceState<AiGovView>>({status: 'loading'});

  const retry = useCallback(() => setRevision(v => v + 1), []);

  useEffect(() => {
    const onFocus = () => {
      if (document.visibilityState === 'visible') setRevision(v => v + 1);
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
    };
  }, []);

  useEffect(() => {
    if (!token) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') setRevision(v => v + 1);
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    const request = new AbortController();
    const {signal} = request;
    setStale(false);
    setReliability({status: 'loading'});
    setGovernance({status: 'loading'});
    setOutcomes({status: 'loading'});
    setAgents({status: 'loading'});
    setObservability({status: 'loading'});
    setGitops({status: 'loading'});
    setAiGov({status: 'loading'});

    const capture = async <T,>(loader: () => Promise<T>): Promise<SourceState<T>> => {
      try {
        const data = await loader();
        if (signal.aborted) return {status: 'loading'};
        return successState(data);
      } catch (error) {
        if (signal.aborted || classifySourceError(error) === 'aborted') return {status: 'loading'};
        const kind = classifySourceError(error);
        if (kind === 'forbidden') return {status: 'forbidden'};
        return unavailableState(error);
      }
    };

    const runs: Promise<void>[] = [
      capture(() => api<Reliability>('/operations/reliability', token, {signal})).then(state => {
        if (!signal.aborted) setReliability(state);
      }),
      (async () => {
        try {
          const caps = await api<GovCaps>('/governance/capabilities', token, {signal});
          if (signal.aborted) return;
          if (!caps.readable) {
            setGovernance({status: 'forbidden'});
            return;
          }
          const summary = await api<GovernanceSummary>('/governance/summary', token, {signal});
          if (!signal.aborted) setGovernance(successState({summary}));
        } catch (error) {
          if (signal.aborted || classifySourceError(error) === 'aborted') return;
          const kind = classifySourceError(error);
          if (kind === 'forbidden') setGovernance({status: 'forbidden'});
          else setGovernance(unavailableState(error));
        }
      })(),
      capture(() => api<{items: ObsSummaryItem[]}>('/observability/summary', token, {signal}).then(r => r.items)).then(state => {
        if (!signal.aborted) setObservability(state);
      }),
      (async () => {
        try {
          const catalog = await api<{enabled: boolean}>('/agents/catalog', token, {signal});
          const taskList = await api<{items: AgentTask[]}>('/agents/tasks', token, {signal});
          if (!signal.aborted) setAgents(successState({enabled: catalog.enabled, tasks: taskList.items}));
        } catch (error) {
          if (signal.aborted || classifySourceError(error) === 'aborted') return;
          setAgents(unavailableState(error));
        }
      })(),
      capture(() => api<GitOpsReview[]>('/gitops/requests', token, {signal})).then(state => {
        if (!signal.aborted) setGitops(state);
      }),
      capture(() => api<AiGovView>('/ai/governance', token, {signal})).then(state => {
        if (!signal.aborted) setAiGov(state);
      }),
    ];

    if (canBill) {
      runs.push(
        capture(() => api<OutcomesMetrics>('/outcomes/anomalies/metrics', token, {signal})).then(state => {
          if (!signal.aborted) setOutcomes(state);
        }),
      );
    } else {
      setOutcomes({status: 'forbidden'});
    }

    Promise.allSettled(runs).then(results => {
      if (signal.aborted) return;
      const failed = results.filter(r => r.status === 'rejected');
      if (failed.length) setStale(true);
      setLastRefresh(new Date().toISOString());
    });

    return () => request.abort();
  }, [token, scan?.status, canBill, revision]);

  const busy = [reliability, governance, outcomes, agents, observability, gitops, aiGov].every(
    s => s.status === 'loading',
  );
  const partial = partialSourceFailures([reliability, governance, outcomes, agents, observability, gitops, aiGov]);

  const deadLetters = reliability.status === 'success' ? deliveryDeadLetters(reliability.data.counts) : undefined;
  const agentStates = agents.status === 'success' ? taskStateCounts(agents.data.tasks) : [];
  const obsIssues = observability.status === 'success' ? observabilityIssueCount(observability.data) : undefined;
  const gitopsOpen = gitops.status === 'success' ? gitopsOpenCount(gitops.data) : undefined;
  const inFlightAgents = agents.status === 'success' ? agentInFlightCount(agentStates) : undefined;
  const policyHolds = aiGov.status === 'success' ? aiGov.data.active_holds?.length ?? 0 : undefined;
  const openInvestigations =
    outcomes.status === 'success'
      ? outcomes.data.open_investigations ?? outcomes.data.investigations
      : undefined;

  const swimLanes: SwimLane[] = useMemo(() => {
    const g = governance.status === 'success' ? governance.data.summary : null;
    const lanes: SwimLane[] = [
      {
        id: 'urgent',
        title: 'Urgent & blocked',
        hint: 'Needs attention before routine work',
        tone: 'urgent',
        items: [
          ...(deadLetters != null && deadLetters > 0
            ? [{label: 'Failed notification deliveries', count: deadLetters, href: '/activity', note: 'Dispatcher reliability'}]
            : []),
          ...(g && g.overdue_findings > 0
            ? [{label: 'Overdue governance findings', count: g.overdue_findings, href: `/governance?tab=${governanceTabQuery.Findings}`}]
            : []),
          ...(g && g.open_material_risks > 0
            ? [{label: 'Open material risks', count: g.open_material_risks, href: `/governance?tab=${governanceTabQuery['Risk register']}`}]
            : []),
          ...(policyHolds != null && policyHolds > 0
            ? [{label: 'AI data-policy holds', count: policyHolds, href: '/settings?tab=ai', note: 'Approvals or blocks'}]
            : []),
        ],
      },
      {
        id: 'queue',
        title: 'Queued for review',
        hint: 'Work waiting on a person or approval',
        tone: 'queue',
        items: [
          ...(gitopsOpen != null && gitopsOpen > 0
            ? [{label: 'GitOps review requests', count: gitopsOpen, href: '/automation', note: 'Open or pending PRs'}]
            : []),
          ...(canBill && outcomes.status === 'success' && outcomes.data.unassigned > 0
            ? [{label: 'Unassigned cost investigations', count: outcomes.data.unassigned, href: '/outcomes', note: 'Route ownership in Savings & investigations'}]
            : []),
          ...(g && g.unknown_assessments > 0
            ? [{label: 'Unknown assessments', count: g.unknown_assessments, href: `/governance?tab=${governanceTabQuery.Evidence}`}]
            : []),
        ],
      },
      {
        id: 'progress',
        title: 'In flight',
        hint: 'Automation and agent work underway',
        tone: 'progress',
        items: [
          ...(inFlightAgents != null && inFlightAgents > 0
            ? [{label: 'Agent tasks running or queued', count: inFlightAgents, href: '/agents', note: 'By task state'}]
            : []),
          ...(canBill && openInvestigations != null && openInvestigations > 0
            ? [{label: 'Open cost investigations', count: openInvestigations, href: '/outcomes', note: 'Excludes resolved and suppressed'}]
            : []),
        ],
      },
      {
        id: 'watch',
        title: 'Watch & renew',
        hint: 'Time-bound risk and connector hygiene',
        tone: 'watch',
        items: [
          ...(g && g.expiring_exceptions > 0
            ? [{label: 'Exceptions nearing expiry', count: g.expiring_exceptions, href: `/governance?tab=${governanceTabQuery.Exceptions}`}]
            : []),
          ...(g && g.stale_evidence > 0
            ? [{label: 'Stale governance evidence', count: g.stale_evidence, href: `/governance?tab=${governanceTabQuery.Evidence}`}]
            : []),
          ...(obsIssues != null && obsIssues > 0
            ? [{label: 'Observability connectors need attention', count: obsIssues, href: '/settings?tab=integrations'}]
            : []),
        ],
      },
    ];
    return lanes;
  }, [deadLetters, governance, gitopsOpen, canBill, outcomes, inFlightAgents, policyHolds, obsIssues, openInvestigations]);

  const totalActionable = useMemo(() => {
    let n = 0;
    for (const lane of swimLanes) {
      for (const item of lane.items) n += item.count ?? 1;
    }
    return n;
  }, [swimLanes]);

  const allClear =
    !partial &&
    !busy &&
    totalActionable === 0 &&
    [reliability, observability, gitops, agents, aiGov].every(s => s.status === 'success' || s.status === 'forbidden') &&
    (governance.status === 'success' || governance.status === 'forbidden');

  function SourceNotice({label, state}: {label: string; state: SourceState<unknown>}) {
    if (state.status === 'unavailable') {
      return (
        <Notice tone="warning">
          {label} is temporarily unavailable ({state.errorCode}).{' '}
          <button type="button" className="text-link" onClick={retry}>
            Retry
          </button>
        </Notice>
      );
    }
    if (state.status === 'forbidden') {
      return <Notice tone="info">{label} is not available with your current role.</Notice>;
    }
    return null;
  }

  if (busy) {
    return (
      <div data-atlas-rollout="action-center">
        <SectionTitle title="Action center" eyebrow="WORK QUEUE">
          One place for deliveries, governance queues, finance routing, and agent work
        </SectionTitle>
        <Loading label="Loading workspace actions…" />
      </div>
    );
  }

  return (
    <div data-atlas-rollout="action-center">
      <SectionTitle title="Action center" eyebrow="WORK QUEUE">
        One place for deliveries, governance queues, finance routing, and agent work
      </SectionTitle>
      {partial ? (
        <Notice tone="warning">
          Some action sources could not be loaded. Counts below may be incomplete.{' '}
          <button type="button" className="text-link" onClick={retry}>
            Retry all
          </button>
        </Notice>
      ) : null}
      {stale && lastRefresh ? (
        <Notice tone="info">Last refresh {new Date(lastRefresh).toLocaleString()}. Showing the best available snapshot.</Notice>
      ) : null}
      <SourceNotice label="Reliability" state={reliability} />
      {governance.status === 'forbidden' ? (
        <Notice tone="info">
          Governance counts are hidden without a governance role.{' '}
          <Link className="text-link" href="/governance">
            Open Risk &amp; compliance
          </Link>{' '}
          after your administrator delegates access.
        </Notice>
      ) : (
        <SourceNotice label="Governance" state={governance} />
      )}

      <div className="allocation-metrics action-center-hero">
        <article className="metric-card metric-featured">
          <div className="metric-label">
            Action items surfaced
            <Kanban size={17} weight="regular" />
          </div>
          <strong>{partial ? `${totalActionable.toLocaleString()}*` : totalActionable.toLocaleString()}</strong>
          <p className="metric-footnote">
            {partial ? '*Partial — some sources unavailable. ' : ''}Counts from connected systems (not deduplicated across lanes)
          </p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Failed deliveries
            <Pulse size={17} weight="regular" />
          </div>
          <strong>{deadLetters != null ? deadLetters.toLocaleString() : '—'}</strong>
          <p className="metric-footnote">
            <Link className="text-link" href="/activity">
              Open activity &amp; delivery
            </Link>
          </p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            GitOps reviews
            <FileCode size={17} weight="regular" />
          </div>
          <strong>{gitopsOpen != null ? gitopsOpen.toLocaleString() : '—'}</strong>
          <p className="metric-footnote">{gitops.status === 'unavailable' ? 'Unavailable' : 'Open or pending publication requests'}</p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Agent tasks
            <Sparkle size={17} weight="regular" />
          </div>
          <strong>{agents.status === 'success' ? agents.data.tasks.length.toLocaleString() : '—'}</strong>
          <p className="metric-footnote">
            {agents.status === 'success'
              ? agents.data.enabled
                ? 'Worker enabled'
                : 'Worker disabled in catalog'
              : agents.status === 'unavailable'
                ? 'Catalog unavailable'
                : '—'}
          </p>
        </article>
      </div>

      <SourceNotice label="Observability" state={observability} />
      <SourceNotice label="GitOps" state={gitops} />
      <SourceNotice label="Agents" state={agents} />
      <SourceNotice label="AI governance" state={aiGov} />

      <div className="action-center-board" role="region" aria-label="Work queue by priority">
        {swimLanes.map(lane => (
          <section key={lane.id} className={`action-center-column action-center-column--${lane.tone}`} aria-labelledby={`action-lane-${lane.id}`}>
            <header className="action-center-column-head">
              <h2 id={`action-lane-${lane.id}`}>{lane.title}</h2>
              <p>{lane.hint}</p>
            </header>
            {lane.items.length === 0 ? (
              <div className="action-center-empty">Nothing queued in this lane right now.</div>
            ) : (
              <ul className="action-center-cards">
                {lane.items.map(item => (
                  <li key={`${lane.id}:${item.label}`}>
                    <Link href={item.href} className="action-center-card">
                      <span className="action-center-card-title">{item.label}</span>
                      {item.count != null && <span className="action-center-card-count">{item.count.toLocaleString()}</span>}
                      {item.note && <span className="action-center-card-note">{item.note}</span>}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>

      <section className="panel action-center-footnotes">
        <SectionTitle title="Where these signals come from" />
        <ul className="action-center-source-list">
          <li>
            <Pulse size={16} weight="regular" />
            <span>
              <strong>Activity &amp; delivery</strong> — notification reliability (
              <code>/operations/reliability</code>).
            </span>
          </li>
          <li>
            <SealCheck size={16} weight="regular" />
            <span>
              <strong>Risk &amp; compliance</strong> — finding due dates, risks, and evidence freshness.
            </span>
          </li>
          <li>
            <Wallet size={16} weight="regular" />
            <span>
              <strong>Savings &amp; investigations</strong> — billing anomaly routing (finance role).
            </span>
          </li>
          <li>
            <FileCode size={16} weight="regular" />
            <span>
              <strong>Automation &amp; GitOps</strong> — Terraform review and publish queue.
            </span>
          </li>
          <li>
            <Sparkle size={16} weight="regular" />
            <span>
              <strong>Agent worker</strong> — task states from <code>/agents/tasks</code>.
            </span>
          </li>
          <li>
            <ClipboardText size={16} weight="regular" />
            <span>
              <strong>AI governance</strong> — data-use holds and policy status in Settings → AI.
            </span>
          </li>
        </ul>
      </section>

      {allClear ? (
        <p className="action-center-all-clear">
          No queued items matched the Action center rules. Use{' '}
          <Link className="text-link" href="/resources">
            Resources
          </Link>{' '}
          for inventory-level review.
        </p>
      ) : null}
    </div>
  );
}
