'use client';
import {useEffect, useState} from 'react';
import Link from 'next/link';
import {RefreshCw} from 'lucide-react';
import {api} from '../../lib/api';
import {dateTime} from '../../lib/finops';
import type {EngineeringOutboxRow, PlanRecord, PlanVersionRecord} from '../../lib/control-plane';
import {notifyControlPlanePlanRevision, subscribeControlPlanePlanRevision} from '../../lib/control-plane-sync';
import {declaredWorkloadShareUrl} from '../../lib/workloads-tabs';
import {planOutboxHasSurface, planOutboxReadoutItems, planOutboxStatusCopy} from '../../lib/plan-outbox';
import {useWorkspace} from '../WorkspaceProvider';
import {EmptyState, Loading, Notice, SectionTitle} from '../ui/shared';

const REVIEW_STEPS = ['draft', 'evidence_required', 'assessed', 'review_requested', 'approved'] as const;
const EXECUTION_STEPS = ['queued', 'running', 'verification_pending', 'verified'] as const;

const NEXT_STATE: Record<string, string> = {
  draft: 'evidence_required',
  evidence_required: 'assessed',
  assessed: 'review_requested',
  review_requested: 'approved',
  approved: 'queued',
  queued: 'running',
  running: 'verification_pending',
  verification_pending: 'verified',
};

const ALT_TRANSITIONS: Record<string, {to: string; label: string}[]> = {
  assessed: [{to: 'evidence_required', label: 'Return to evidence required'}],
  review_requested: [{to: 'assessed', label: 'Return to assessed'}],
  running: [
    {to: 'failed', label: 'Record failed outcome'},
    {to: 'reconciliation_required', label: 'Require reconciliation'},
  ],
  verification_pending: [
    {to: 'failed', label: 'Record failed outcome'},
    {to: 'reconciliation_required', label: 'Require reconciliation'},
  ],
  failed: [{to: 'reconciliation_required', label: 'Advance to reconciliation required'}],
};

const CANCELLABLE = new Set(['draft', 'evidence_required', 'assessed', 'review_requested', 'approved', 'queued']);
const EXPIRABLE = new Set(['evidence_required', 'assessed', 'review_requested', 'approved', 'queued']);

function lifecycleEndTransitions(state: string): {to: string; label: string}[] {
  const actions: {to: string; label: string}[] = [];
  if (CANCELLABLE.has(state)) actions.push({to: 'cancelled', label: 'Cancel plan version'});
  if (EXPIRABLE.has(state)) actions.push({to: 'expired', label: 'Mark expired'});
  return actions;
}

function reviewStepClass(step: (typeof REVIEW_STEPS)[number], state: string) {
  const stepIdx = REVIEW_STEPS.indexOf(step);
  const stateIdx = REVIEW_STEPS.indexOf(state as (typeof REVIEW_STEPS)[number]);
  if (stateIdx >= 0) {
    if (stateIdx === stepIdx) return 'current';
    if (stateIdx > stepIdx) return 'completed';
    return '';
  }
  return 'completed';
}

function executionStepClass(step: (typeof EXECUTION_STEPS)[number], state: string) {
  if (state === 'approved') return '';
  if (state === 'failed') {
    if (step === 'running') return 'current plan-step-failed';
    return EXECUTION_STEPS.indexOf(step) < EXECUTION_STEPS.indexOf('running') ? 'completed' : '';
  }
  if (state === 'reconciliation_required') {
    if (step === 'verification_pending') return 'current plan-step-warning';
    return EXECUTION_STEPS.indexOf(step) < EXECUTION_STEPS.indexOf('verification_pending') ? 'completed' : '';
  }
  const stepIdx = EXECUTION_STEPS.indexOf(step);
  const stateIdx = EXECUTION_STEPS.indexOf(state as (typeof EXECUTION_STEPS)[number]);
  if (stateIdx >= 0) {
    if (stateIdx === stepIdx) return 'current';
    if (stateIdx > stepIdx) return 'completed';
    return '';
  }
  return '';
}

function showExecutionLadder(state: string) {
  return (
    ['approved', ...EXECUTION_STEPS, 'failed', 'reconciliation_required', 'cancelled', 'expired'] as string[]
  ).includes(state);
}

function planShareLinks(plan: PlanRecord) {
  const origin = typeof window === 'undefined' ? '' : window.location.origin;
  const governance = `${origin}/governance?tab=control-plane&plan=${encodeURIComponent(plan.id)}`;
  if (!plan.engineering_workload_id) return governance;
  const engineering = `${origin}/workloads?tab=engineering&workload=${encodeURIComponent(plan.engineering_workload_id)}&plan=${encodeURIComponent(plan.id)}`;
  const declared = declaredWorkloadShareUrl(plan.engineering_workload_id, origin);
  return `Governance: ${governance}\nEngineering: ${engineering}\nDeclared: ${declared}`;
}

export function ControlPlanePlansPanel({highlightPlanId}: {highlightPlanId?: string}) {
  const {token, canAdmin, workspace} = useWorkspace();
  const humanApprover = canAdmin && workspace?.subject_type === 'user' && !workspace.key_id;
  const [plans, setPlans] = useState<PlanRecord[]>([]);
  const [versions, setVersions] = useState<Record<string, PlanVersionRecord[]>>({});
  const [objective, setObjective] = useState('');
  const [targets, setTargets] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const [approvalAck, setApprovalAck] = useState<Record<string, boolean>>({});
  const [syncNotice, setSyncNotice] = useState('');
  const [outboxRows, setOutboxRows] = useState<Record<string, EngineeringOutboxRow[]>>({});

  useEffect(() => {
    if (!highlightPlanId || !plans.some(p => p.id === highlightPlanId)) return;
    const el = document.getElementById(`control-plane-plan-${highlightPlanId}`);
    el?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }, [highlightPlanId, plans, revision]);

  useEffect(
    () =>
      subscribeControlPlanePlanRevision(detail => {
        if (detail.source === 'governance') return;
        setSyncNotice(
          'Engineering records changed. Plan versions were refreshed to include outbox pending and published counts.',
        );
        if (detail.planId) {
          void api<{items: PlanVersionRecord[]}>(`/control-plane/plans/${detail.planId}/versions?limit=20`, token).then(res =>
            setVersions(prev => ({...prev, [detail.planId!]: res.items})),
          );
          return;
        }
        setRevision(r => r + 1);
      }),
    [token],
  );

  useEffect(() => {
    const controller = new AbortController();
    setError('');
    api<{items: PlanRecord[]}>('/control-plane/plans?limit=50', token, {signal: controller.signal})
      .then(res => {
        if (!controller.signal.aborted) setPlans(res.items);
      })
      .catch(err => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Plans could not be loaded.');
      });
    return () => controller.abort();
  }, [token, revision]);

  useEffect(() => {
    if (!plans.length) return;
    const controller = new AbortController();
    Promise.all(
      plans.map(p =>
        api<{items: PlanVersionRecord[]}>(`/control-plane/plans/${p.id}/versions?limit=20`, token, {signal: controller.signal}).then(
          r => [p.id, r.items] as const,
        ),
      ),
    )
      .then(rows => {
        if (!controller.signal.aborted) setVersions(Object.fromEntries(rows));
      })
      .catch(() => {});
    return () => controller.abort();
  }, [plans, token, revision]);

  useEffect(() => {
    if (!plans.length) return;
    const controller = new AbortController();
    const jobs = plans.flatMap(plan => {
      const latest = versions[plan.id]?.[0];
      if (!latest || !planOutboxHasSurface(latest)) return [];
      return api<{items: EngineeringOutboxRow[]}>(
        `/control-plane/plan-versions/${latest.id}/engineering-outbox?limit=20`,
        token,
        {signal: controller.signal},
      ).then(res => [latest.id, res.items] as const);
    });
    if (!jobs.length) {
      setOutboxRows({});
      return () => controller.abort();
    }
    Promise.all(jobs)
      .then(rows => {
        if (!controller.signal.aborted) setOutboxRows(Object.fromEntries(rows));
      })
      .catch(() => {});
    return () => controller.abort();
  }, [plans, versions, token, revision]);

  async function createPlan(event: React.FormEvent) {
    event.preventDefault();
    if (!canAdmin || objective.trim().length < 3) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const plan = await api<{id: string}>('/control-plane/plans', token, {method: 'POST', body: {objective: objective.trim()}});
      const targetList = targets
        .split(/[\n,]/)
        .map(t => t.trim())
        .filter(Boolean);
      if (targetList.length) {
        await api(`/control-plane/plans/${plan.id}/versions`, token, {
          method: 'POST',
          body: {expected_version: 0, targets: targetList, parameters: {}},
        });
      }
      setObjective('');
      setTargets('');
      setNotice('Control-plane plan saved. Transitions and human approval remain separate steps.');
      notifyControlPlanePlanRevision(plan.id, {source: 'governance'});
      setRevision(r => r + 1);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function transition(version: PlanVersionRecord, to: string) {
    setBusy(true);
    setError('');
    try {
      await api(`/control-plane/plan-versions/${version.id}/transitions`, token, {
        method: 'POST',
        body: {from_state: version.state, to_state: to},
      });
      setNotice(`Plan version advanced to ${to.replaceAll('_', ' ')}.`);
      notifyControlPlanePlanRevision(version.plan_id, {source: 'governance'});
      setRevision(r => r + 1);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function approveVersion(version: PlanVersionRecord) {
    if (!humanApprover || !approvalAck[version.id]) return;
    setBusy(true);
    setError('');
    try {
      const expires = new Date(Date.now() + 60 * 60 * 1000).toISOString();
      await api(`/control-plane/plan-versions/${version.id}/approvals`, token, {
        method: 'POST',
        body: {identity_digest: version.identity_digest, expires_at: expires},
      });
      await api(`/control-plane/plan-versions/${version.id}/transitions`, token, {
        method: 'POST',
        body: {from_state: version.state, to_state: 'approved'},
      });
      setNotice('Human approval recorded and plan version advanced to approved. Execution remains disabled until separate verification.');
      notifyControlPlanePlanRevision(version.plan_id, {source: 'governance'});
      setApprovalAck(prev => ({...prev, [version.id]: false}));
      setRevision(r => r + 1);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!canAdmin) {
    return (
      <EmptyState icon={RefreshCw} title="Workspace administrator required">
        Control-plane plans are visible only to workspace administrators. Human approval requires a verified human session,
        not a workspace API key.
      </EmptyState>
    );
  }

  return (
    <section className="panel">
      <SectionTitle
        title="Control-plane plans"
        action={
          <button type="button" className="button secondary small" disabled={busy} onClick={() => setRevision(r => r + 1)}>
            <RefreshCw size={14} /> Refresh plans &amp; outbox
          </button>
        }
      >
        Revision-bound plans with immutable identity digests. Automatic execution stays disabled; approvals bind to exact
        plan versions.
      </SectionTitle>
      <p className="inline-help" style={{margin: '0 0 16px'}}>
        Pair plans with{' '}
        <Link href="/workloads">declared engineering workloads</Link> and resource-level action-safety checks before any
        external change workflow.
      </p>
      {!humanApprover && (
        <Notice tone="warning">
          Read/scoped workspace key — human approval disabled. Service accounts and bearer licences cannot approve plan
          versions or release legal holds.
        </Notice>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {notice && <Notice tone="success">{notice}</Notice>}
      {syncNotice && (
        <div className="cp-sync-notice">
          <Notice tone="success">{syncNotice}</Notice>
          <button type="button" className="button secondary small" onClick={() => setSyncNotice('')}>
            Dismiss
          </button>
        </div>
      )}
      {highlightPlanId && plans.some(p => p.id === highlightPlanId) && (
        <Notice>
          Focused plan from a shared link (for example engineering workloads). Review and approval actions apply to the
          highlighted card below.
        </Notice>
      )}
      <form className="gov-form" onSubmit={createPlan}>
        <label>
          Plan objective
          <input required minLength={3} maxLength={500} value={objective} onChange={e => setObjective(e.target.value)} />
        </label>
        <label>
          Exact targets (one resource id per line)
          <textarea rows={3} value={targets} onChange={e => setTargets(e.target.value)} placeholder="Optional on create" />
        </label>
        <button type="submit" className="button primary" disabled={busy}>
          Create draft plan
        </button>
      </form>
      {!plans.length ? (
        <p className="inline-help">No control-plane plans recorded for this workspace yet.</p>
      ) : (
        <div className="gov-cards">
          {plans.map(plan => {
            const vers = versions[plan.id] || [];
            const latest = vers[0];
            return (
              <article
                key={plan.id}
                id={`control-plane-plan-${plan.id}`}
                className={`gov-risk${highlightPlanId === plan.id ? ' plan-card-highlight' : ''}`}
              >
                <h3>
                  {plan.objective}{' '}
                  {latest && (
                    <span className="state-badge plan-state-badge">{latest.state.replaceAll('_', ' ')}</span>
                  )}
                </h3>
                <p className="inline-help">
                  Created {dateTime(plan.created_at)} · {vers.length} version{vers.length === 1 ? '' : 's'}
                  {plan.engineering_workload_id && (
                    <>
                      {' '}
                      ·{' '}
                      <Link
                        href={`/workloads?tab=engineering&workload=${encodeURIComponent(plan.engineering_workload_id)}&plan=${encodeURIComponent(plan.id)}`}
                      >
                        Open linked engineering workload
                        {plan.engineering_workload_name ? ` (${plan.engineering_workload_name})` : ''}
                      </Link>
                      {' · '}
                      <Link href={`/workloads?tab=declared&workload=${encodeURIComponent(plan.engineering_workload_id)}`}>
                        View declared record
                        {plan.engineering_workload_name ? ` (${plan.engineering_workload_name})` : ''}
                      </Link>
                    </>
                  )}
                </p>
                {latest && (
                  <>
                    <p className="plan-ladder-label">Review & approval</p>
                    <div className="plan-stepper">
                      {REVIEW_STEPS.map(step => (
                        <span key={step} className={`plan-step ${reviewStepClass(step, latest.state)}`}>
                          {step.replaceAll('_', ' ')}
                        </span>
                      ))}
                    </div>
                    {showExecutionLadder(latest.state) && (
                      <>
                        <p className="plan-ladder-label">Execution tracking (no automatic cloud mutations)</p>
                        <div className="plan-stepper plan-execution-stepper">
                          {EXECUTION_STEPS.map(step => (
                            <span key={step} className={`plan-step ${executionStepClass(step, latest.state)}`}>
                              {step.replaceAll('_', ' ')}
                            </span>
                          ))}
                        </div>
                        {['queued', 'running', 'verification_pending'].includes(latest.state) && (
                          <p className="inline-help plan-outbox-status">{planOutboxStatusCopy(latest)}</p>
                        )}
                      </>
                    )}
                    <dl className="settings-key-values">
                      <div>
                        <dt>Latest version</dt>
                        <dd>
                          v{latest.version} · {latest.state.replaceAll('_', ' ')}
                        </dd>
                      </div>
                      <div>
                        <dt>Identity digest</dt>
                        <dd>
                          <code>{latest.identity_digest.slice(0, 16)}…</code>
                        </dd>
                      </div>
                      {(latest.engineering_outbox_pending_count ?? 0) > 0 ||
                      (latest.engineering_outbox_published_count ?? 0) > 0 ? (
                        <div>
                          <dt>Engineering outbox</dt>
                          <dd>
                            {latest.engineering_outbox_pending_count ?? 0} pending ·{' '}
                            {latest.engineering_outbox_published_count ?? 0} published
                            {latest.engineering_outbox_state ? ` · latest ${latest.engineering_outbox_state}` : ''}
                          </dd>
                        </div>
                      ) : (
                        latest.engineering_outbox_state && (
                          <div>
                            <dt>Engineering outbox</dt>
                            <dd>{latest.engineering_outbox_state}</dd>
                          </div>
                        )
                      )}
                    </dl>
                    {planOutboxHasSurface(latest) && (
                      <details className="plan-outbox-readout">
                        <summary>Engineering outbox readout (audit-only)</summary>
                        <ul>
                          {planOutboxReadoutItems(latest).map(line => (
                            <li key={line}>{line}</li>
                          ))}
                        </ul>
                        {outboxRows[latest.id]?.length ? (
                          <div className="summary-table-scroll">
                            <table className="summary-table plan-outbox-table">
                              <thead>
                                <tr>
                                  <th>Event id</th>
                                  <th>Kind</th>
                                  <th>Outbox state</th>
                                  <th>Recorded</th>
                                </tr>
                              </thead>
                              <tbody>
                                {outboxRows[latest.id].map(row => (
                                  <tr key={row.event_id}>
                                    <td>
                                      <code>{row.event_id.slice(0, 8)}…</code>
                                    </td>
                                    <td>{row.kind.replaceAll('.', ' ')}</td>
                                    <td>{row.state}</td>
                                    <td>{dateTime(row.created_at)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <p className="inline-help">No per-event outbox rows are returned for this plan version yet.</p>
                        )}
                        <p className="inline-help plan-outbox-dispatch-note">
                          Worker dispatch runs outside this dashboard. Outbox states are read-only here.
                        </p>
                        {plan.engineering_workload_id && (
                          <p className="inline-help">
                            <Link
                              href={`/workloads?tab=engineering&workload=${encodeURIComponent(plan.engineering_workload_id)}&plan=${encodeURIComponent(plan.id)}`}
                            >
                              Open linked engineering workload
                              {plan.engineering_workload_name ? ` (${plan.engineering_workload_name})` : ''}
                            </Link>
                            {' · '}
                            <Link href={`/workloads?tab=declared&workload=${encodeURIComponent(plan.engineering_workload_id)}`}>
                              View declared record
                            </Link>
                          </p>
                        )}
                      </details>
                    )}
                    <div className="button-row">
                      {canAdmin && NEXT_STATE[latest.state] && (
                        <button
                          type="button"
                          className="button secondary small"
                          disabled={busy || (latest.state === 'review_requested' && humanApprover)}
                          onClick={() => transition(latest, NEXT_STATE[latest.state])}
                        >
                          Advance to {NEXT_STATE[latest.state].replaceAll('_', ' ')}
                        </button>
                      )}
                      {canAdmin &&
                        (ALT_TRANSITIONS[latest.state] ?? []).map(alt => (
                          <button
                            key={alt.to}
                            type="button"
                            className="button secondary small"
                            disabled={busy}
                            onClick={() => transition(latest, alt.to)}
                          >
                            {alt.label}
                          </button>
                        ))}
                      {canAdmin &&
                        lifecycleEndTransitions(latest.state).map(end => (
                          <button
                            key={end.to}
                            type="button"
                            className="button danger small"
                            disabled={busy}
                            onClick={() => transition(latest, end.to)}
                          >
                            {end.label}
                          </button>
                        ))}
                      <button
                        type="button"
                        className="button secondary small"
                        onClick={() => {
                          void navigator.clipboard.writeText(planShareLinks(plan)).then(() =>
                            setNotice(
                              plan.engineering_workload_id
                                ? 'Governance, engineering, and declared workload deep links copied to clipboard.'
                                : 'Plan deep link copied to clipboard.',
                            ),
                          );
                        }}
                      >
                        Copy plan link{plan.engineering_workload_id ? 's' : ''}
                      </button>
                    </div>
                    {latest.state === 'approved' && (
                      <Notice tone="success">
                        This plan version is approved with a bound human attestation. Queueing and execution still require
                        separate control-plane checks.
                      </Notice>
                    )}
                    {['queued', 'running', 'verification_pending'].includes(latest.state) && (
                      <Notice tone="info">
                        Execution states are recorded for audit and coordination only. Transitions do not invoke cloud
                        provider APIs or agent workers.
                      </Notice>
                    )}
                    {latest.state === 'verified' && (
                      <Notice tone="success">Verification completed for this plan version. Outcomes remain separate from compliance attestation.</Notice>
                    )}
                    {(latest.state === 'cancelled' || latest.state === 'expired') && (
                      <Notice tone="warning">
                        This plan version is {latest.state}. It cannot advance further; create a new version to continue review or
                        execution tracking.
                      </Notice>
                    )}
                    {(latest.state === 'failed' || latest.state === 'reconciliation_required') && (
                      <Notice tone="error">
                        Plan version is in {latest.state.replaceAll('_', ' ')}.
                        {latest.state === 'failed'
                          ? ' Record reconciliation after evidence review or open a new plan version.'
                          : ' Reconcile external evidence before creating a new version; no further execution transitions apply.'}
                      </Notice>
                    )}
                    {latest.state === 'review_requested' && humanApprover && (
                      <div className="plan-approval-box">
                        <Notice tone="warning">
                          Bind approval to identity digest <code>{latest.identity_digest.slice(0, 16)}…</code>. A different
                          approver identity is required server-side; self-approval is rejected.
                        </Notice>
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={!!approvalAck[latest.id]}
                            onChange={e => setApprovalAck(prev => ({...prev, [latest.id]: e.target.checked}))}
                          />
                          I reviewed the exact targets, parameters and identity digest for this plan version.
                        </label>
                        <button
                          type="button"
                          className="button primary small"
                          disabled={busy || !approvalAck[latest.id]}
                          onClick={() => approveVersion(latest)}
                        >
                          Record human approval
                        </button>
                      </div>
                    )}
                    {latest.state === 'review_requested' && !humanApprover && (
                      <p className="inline-help">Awaiting a verified human session to record approval.</p>
                    )}
                  </>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
