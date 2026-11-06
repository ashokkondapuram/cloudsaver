'use client';

import Link from 'next/link';
import {useEffect, useMemo, useState} from 'react';
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
import {useWorkspace} from './WorkspaceProvider';
import {EmptyState, Loading, Notice, SectionTitle} from './ui/shared';

type OutcomesMetrics = {
  investigations: number;
  unassigned: number;
  actionable_resolved_pct: number | null;
  warning: string;
};
type GovCaps = {readable: boolean};
type AgentTask = {state: string};
type ObsSummaryItem = {id: string; status: string};
type GitOpsReview = {id: string; repository: string; branch: string; status: string; attempts: number};
type AiGovView = {
  counts: Record<string, number>;
  active_holds: unknown[];
  policy: {status: string; processors: unknown[]};
};

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

function observabilityIssueCount(items: ObsSummaryItem[]) {
  return items.filter(i => i.status && i.status !== 'healthy' && i.status !== 'ok' && i.status !== 'synced').length;
}

function gitopsOpenCount(rows: GitOpsReview[]) {
  return rows.filter(r => {
    const s = (r.status || '').toLowerCase();
    return s === 'open' || s === 'pending' || s === 'draft' || s === 'review';
  }).length;
}

function agentInFlightCount(states: [string, number][]) {
  const inflight = new Set(['pending', 'queued', 'running', 'processing', 'in_progress']);
  return states.filter(([s]) => inflight.has((s || '').toLowerCase())).reduce((n, [, c]) => n + c, 0);
}

type SwimLane = {
  id: string;
  title: string;
  hint: string;
  tone: 'urgent' | 'queue' | 'progress' | 'watch';
  items: {label: string; count?: number; href: string; note?: string}[];
};

export function ActionCenterView() {
  const {token, scan, canBill} = useWorkspace();
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [reliability, setReliability] = useState<Reliability | null>(null);
  const [governance, setGovernance] = useState<{summary: GovernanceSummary} | null>(null);
  const [governanceDenied, setGovernanceDenied] = useState(false);
  const [outcomes, setOutcomes] = useState<OutcomesMetrics | null>(null);
  const [agents, setAgents] = useState<{enabled: boolean; tasks: AgentTask[]} | null>(null);
  const [observability, setObservability] = useState<ObsSummaryItem[] | null>(null);
  const [gitops, setGitops] = useState<GitOpsReview[] | null>(null);
  const [aiGov, setAiGov] = useState<AiGovView | null>(null);

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
      ]).then(([catalog, taskList]) => {
        if (!signal.aborted) setAgents({enabled: catalog.enabled, tasks: taskList.items});
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
        api<OutcomesMetrics>('/outcomes/anomalies/metrics', token, {signal})
          .then(metrics => {
            if (!signal.aborted) setOutcomes(metrics);
          })
          .catch(() => {
            if (!signal.aborted) setOutcomes(null);
          }),
      );
    }

    if (scan?.status === 'completed') {
      /* reserved: could surface Kubernetes flagged counts later */
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
  }, [token, scan?.status, canBill]);

  const deadLetters = reliability ? deliveryDeadLetters(reliability.counts) : 0;
  const agentStates = agents ? taskStateCounts(agents.tasks) : [];
  const obsIssues = observability ? observabilityIssueCount(observability) : 0;
  const gitopsOpen = gitops ? gitopsOpenCount(gitops) : 0;
  const inFlightAgents = agentInFlightCount(agentStates);
  const policyHolds = aiGov?.active_holds?.length ?? 0;

  const swimLanes: SwimLane[] = useMemo(() => {
    const g = governance?.summary;
    const lanes: SwimLane[] = [
      {
        id: 'urgent',
        title: 'Urgent & blocked',
        hint: 'Needs attention before routine work',
        tone: 'urgent',
        items: [
          ...(deadLetters > 0
            ? [{label: 'Failed notification deliveries', count: deadLetters, href: '/activity', note: 'Dispatcher reliability'}]
            : []),
          ...(g && g.overdue_findings > 0
            ? [
                {
                  label: 'Overdue governance findings',
                  count: g.overdue_findings,
                  href: `/governance?tab=${governanceTabQuery.Findings}`,
                },
              ]
            : []),
          ...(g && g.open_material_risks > 0
            ? [
                {
                  label: 'Open material risks',
                  count: g.open_material_risks,
                  href: `/governance?tab=${governanceTabQuery['Risk register']}`,
                },
              ]
            : []),
          ...(policyHolds > 0
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
          ...(gitopsOpen > 0
            ? [{label: 'GitOps review requests', count: gitopsOpen, href: '/automation', note: 'Open or pending PRs'}]
            : []),
          ...(canBill && outcomes && outcomes.unassigned > 0
            ? [
                {
                  label: 'Unassigned cost investigations',
                  count: outcomes.unassigned,
                  href: '/outcomes',
                  note: 'Route ownership in Savings & investigations',
                },
              ]
            : []),
          ...(g && g.unknown_assessments > 0
            ? [
                {
                  label: 'Unknown assessments',
                  count: g.unknown_assessments,
                  href: `/governance?tab=${governanceTabQuery.Evidence}`,
                },
              ]
            : []),
        ],
      },
      {
        id: 'progress',
        title: 'In flight',
        hint: 'Automation and agent work underway',
        tone: 'progress',
        items: [
          ...(inFlightAgents > 0
            ? [{label: 'Agent tasks running or queued', count: inFlightAgents, href: '/agents', note: 'By task state'}]
            : []),
          ...(canBill && outcomes && outcomes.investigations > 0
            ? [
                {
                  label: 'Active cost investigations',
                  count: outcomes.investigations,
                  href: '/outcomes',
                  note: 'Includes resolved; open the page for detail',
                },
              ]
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
            ? [
                {
                  label: 'Exceptions nearing expiry',
                  count: g.expiring_exceptions,
                  href: `/governance?tab=${governanceTabQuery.Exceptions}`,
                },
              ]
            : []),
          ...(g && g.stale_evidence > 0
            ? [
                {
                  label: 'Stale governance evidence',
                  count: g.stale_evidence,
                  href: `/governance?tab=${governanceTabQuery.Evidence}`,
                },
              ]
            : []),
          ...(obsIssues > 0
            ? [{label: 'Observability connectors need attention', count: obsIssues, href: '/settings?tab=integrations'}]
            : []),
        ],
      },
    ];
    return lanes;
  }, [
    deadLetters,
    governance,
    gitopsOpen,
    canBill,
    outcomes,
    inFlightAgents,
    policyHolds,
    obsIssues,
  ]);

  const totalActionable = useMemo(() => {
    let n = 0;
    for (const lane of swimLanes) {
      for (const item of lane.items) {
        n += item.count ?? 1;
      }
    }
    return n;
  }, [swimLanes]);

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
      {error ? <Notice tone="error">{error}</Notice> : null}
      {governanceDenied ? (
        <Notice tone="info">
          Governance counts are hidden without a governance role.{' '}
          <Link className="text-link" href="/governance">
            Open Risk &amp; compliance
          </Link>{' '}
          after your administrator delegates access.
        </Notice>
      ) : null}

      <div className="allocation-metrics action-center-hero">
        <article className="metric-card metric-featured">
          <div className="metric-label">
            Action items surfaced
            <Kanban size={17} weight="regular" />
          </div>
          <strong>{totalActionable.toLocaleString()}</strong>
          <p className="metric-footnote">Counts from connected systems (not deduplicated across lanes)</p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Failed deliveries
            <Pulse size={17} weight="regular" />
          </div>
          <strong>{deadLetters.toLocaleString()}</strong>
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
          <strong>{gitops ? gitopsOpen.toLocaleString() : '—'}</strong>
          <p className="metric-footnote">Open or pending publication requests</p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Agent tasks
            <Sparkle size={17} weight="regular" />
          </div>
          <strong>{agents ? agents.tasks.length.toLocaleString() : '—'}</strong>
          <p className="metric-footnote">
            {agents?.enabled ? 'Worker enabled' : 'Catalog unavailable or disabled'}
          </p>
        </article>
      </div>

      {!agents?.enabled && (
        <Notice tone="info">
          Agent worker is optional. When disabled, automation cards may stay empty even if other work exists.
        </Notice>
      )}

      <div className="action-center-board" role="region" aria-label="Work queue by priority">
        {swimLanes.map(lane => (
          <section
            key={lane.id}
            className={`action-center-column action-center-column--${lane.tone}`}
            aria-labelledby={`action-lane-${lane.id}`}
          >
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

      {totalActionable === 0 && !error && (
        <p className="action-center-all-clear">
          No queued items matched the Action center rules. Use{' '}
          <Link className="text-link" href="/resources">
            Resources
          </Link>{' '}
          for inventory-level review.
        </p>
      )}
    </div>
  );
}
