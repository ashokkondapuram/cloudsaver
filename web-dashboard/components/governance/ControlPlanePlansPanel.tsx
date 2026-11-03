'use client';
import {useEffect, useState} from 'react';
import {RefreshCw} from 'lucide-react';
import {api} from '../../lib/api';
import {dateTime} from '../../lib/finops';
import type {PlanRecord, PlanVersionRecord} from '../../lib/control-plane';
import {useWorkspace} from '../WorkspaceProvider';
import {EmptyState, Loading, Notice, SectionTitle} from '../ui/shared';

const STEPS = ['draft', 'evidence_required', 'assessed', 'review_requested', 'approved'] as const;

export function ControlPlanePlansPanel() {
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
      {!humanApprover && (
        <Notice tone="warning">
          Read/scoped workspace key — human approval disabled. Service accounts and bearer licences cannot approve plan
          versions or release legal holds.
        </Notice>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {notice && <Notice tone="success">{notice}</Notice>}
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
              <article key={plan.id} className="gov-risk">
                <h3>{plan.objective}</h3>
                <p className="inline-help">
                  Created {dateTime(plan.created_at)} · {vers.length} version{vers.length === 1 ? '' : 's'}
                </p>
                {latest && (
                  <>
                    <div className="plan-stepper">
                      {STEPS.map(step => (
                        <span
                          key={step}
                          className={`plan-step ${latest.state === step ? 'current' : STEPS.indexOf(step as typeof STEPS[number]) < STEPS.indexOf(latest.state as typeof STEPS[number]) ? 'completed' : ''}`}
                        >
                          {step.replaceAll('_', ' ')}
                        </span>
                      ))}
                    </div>
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
                    {canAdmin && latest.state === 'draft' && (
                      <button type="button" className="button secondary small" disabled={busy} onClick={() => transition(latest, 'evidence_required')}>
                        Mark evidence required
                      </button>
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
