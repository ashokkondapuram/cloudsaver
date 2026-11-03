'use client';
import {useEffect, useState} from 'react';
import Link from 'next/link';
import {RefreshCw} from 'lucide-react';
import {api} from '../../lib/api';
import {dateTime} from '../../lib/finops';
import type {PlanRecord, PlanVersionRecord} from '../../lib/control-plane';
import {notifyControlPlanePlanRevision} from '../../lib/control-plane-sync';
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

  useEffect(() => {
    if (!highlightPlanId || !plans.some(p => p.id === highlightPlanId)) return;
    const el = document.getElementById(`control-plane-plan-${highlightPlanId}`);
    el?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }, [highlightPlanId, plans, revision]);

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
      notifyControlPlanePlanRevision(plan.id);
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
      notifyControlPlanePlanRevision(version.plan_id);
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
      notifyControlPlanePlanRevision(version.plan_id);
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
            <RefreshCw size={14} /> Refresh
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
                    </dl>
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
                          const url = `${window.location.origin}/governance?tab=control-plane&plan=${encodeURIComponent(plan.id)}`;
                          void navigator.clipboard.writeText(url).then(() => setNotice('Plan deep link copied to clipboard.'));
                        }}
                      >
                        Copy plan link
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
