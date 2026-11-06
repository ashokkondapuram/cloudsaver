'use client';
import {useState} from 'react';
import {ShieldWarning} from '@phosphor-icons/react';
import {api} from '../../lib/api';
import {findingsToChecks, type ActionAssessmentResponse, type GateCheckStatus} from '../../lib/control-plane';
import {Notice, SectionTitle} from '../ui/shared';

const GATE_LABELS: Record<string, string> = {
  'AG-COST-01': 'Commitment-Aware Avoidable Spend',
  'AG-ID-01': 'Identity & Network Dependency Protection',
  'AG-HA-01': 'Availability Floor & Quorum Preservation',
  'AG-DR-01': 'Standby & Replication Protection',
  'AG-RET-01': 'Retention, Legal Hold & Preservation',
  'AG-REC-01': 'Disk Recovery Feasibility',
  'AG-PERF-01': 'Rightsizing Capacity & SLO Outcomes',
  'AG-OPS-01': 'Ownership & Change Recovery Readiness',
};

function badgeClass(status: GateCheckStatus): string {
  if (status === 'pass') return 'state-badge active';
  if (status === 'fail') return 'state-badge expired';
  if (status === 'unknown') return 'state-badge legacy';
  return 'state-badge';
}

export function ActionSafetyPanel({
  token,
  actionId,
  supported,
  evidence,
  canAdmin,
}: {
  token: string;
  actionId: string;
  supported: boolean;
  evidence: Record<string, unknown>;
  canAdmin: boolean;
}) {
  const [result, setResult] = useState<ActionAssessmentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function evaluateGate() {
    setLoading(true);
    setError('');
    try {
      const idempotencyKey = crypto.randomUUID();
      const response = await api<ActionAssessmentResponse>('/control-plane/action-assessments', token, {
        method: 'POST',
        idempotencyKey,
        body: {
          idempotency_key: idempotencyKey,
          action_id: actionId,
          supported,
          evidence,
        },
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Safety evaluation could not be completed.');
    } finally {
      setLoading(false);
    }
  }

  const checks = result ? findingsToChecks(result.findings) : [];

  return (
    <section className="panel panel-bleed" aria-label="Action safety firewall evaluation">
      <SectionTitle
        title="Deterministic action-safety firewall"
        action={
          canAdmin ? (
            <button type="button" className="button primary small" disabled={loading} onClick={evaluateGate}>
              {loading ? 'Evaluating gates…' : 'Evaluate action safety'}
            </button>
          ) : undefined
        }
      >
        Separates five-pillar resource findings from disruptive execution eligibility. Unknown mandatory evidence blocks
        execution; AI cannot override a failed gate.
      </SectionTitle>
      {error && <Notice tone="error">{error}</Notice>}
      {!result ? (
        <div className="empty-state">
          <div className="empty-icon">
            <ShieldWarning size={20} weight="regular" />
          </div>
          <p>
            Run a deterministic safety evaluation to inspect all eight enterprise firewall gates (AG-COST-01 through
            AG-OPS-01) and bind an immutable evidence digest.
          </p>
        </div>
      ) : (
        <>
          <dl className="settings-key-values">
            <div>
              <dt>Eligibility decision</dt>
              <dd>
                <span
                  className={
                    result.decision === 'eligible_for_review'
                      ? 'state-badge active'
                      : result.decision === 'blocked'
                        ? 'state-badge expired'
                        : 'state-badge expiring_soon'
                  }
                >
                  {result.decision.replaceAll('_', ' ')}
                </span>
              </dd>
            </div>
            <div>
              <dt>Rule version</dt>
              <dd>
                <code>v{result.rule_version}</code> · policy {result.policy_digest.slice(0, 12)}…
              </dd>
            </div>
            <div>
              <dt>Evidence digest</dt>
              <dd>
                <code>{result.evidence_digest.slice(0, 16)}…</code>
              </dd>
            </div>
            <div>
              <dt>Execution boundary</dt>
              <dd>Review only · automatic execution disabled</dd>
            </div>
          </dl>
          <div className="summary-table-scroll safety-firewall-grid">
            <table className="summary-table">
              <thead>
                <tr>
                  <th>Gate code</th>
                  <th>Control domain</th>
                  <th>Outcome</th>
                </tr>
              </thead>
              <tbody>
                {checks.map(check => (
                  <tr key={check.code}>
                    <td>
                      <code>{check.code}</code>
                    </td>
                    <td>{GATE_LABELS[check.code] || check.code}</td>
                    <td>
                      <span className={badgeClass(check.status)}>{check.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
