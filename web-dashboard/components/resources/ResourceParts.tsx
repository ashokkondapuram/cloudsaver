'use client';
import {PILLARS, aiStatusLabels, armDetailLabels, decisionLabels, label, sentence, type AIState, type Action, type ArmDetailStatus, type Decision, type PillarStatus} from '../../lib/resources';

export function PillarDots({pillars}: {pillars: Record<string, PillarStatus>}) {
  const text = PILLARS.map(p => `${p}: ${pillars[p] === 'risk' ? 'risk observed' : pillars[p] === 'observed' ? 'evidence observed' : 'evidence incomplete'}`).join(', ');
  return <span className="pillar-dots" role="img" aria-label={text} title={text}>{PILLARS.map(p => <span key={p} className={`assessment-dot ${pillars[p] || 'unknown'}`}/>)}</span>;
}

export function AIStatusBadge({ai}: {ai: AIState}) {
  return <span className={`ai-status-badge ai-${ai.status}`} title={ai.reason ? label(ai.reason) : undefined}>{aiStatusLabels[ai.status]}</span>;
}

export function AIRisk({ai}: {ai: AIState}) {
  return ai.risk_level ? <span className={`ai-risk ai-risk-${ai.risk_level}`}>{sentence(ai.risk_level)}</span> : <span className="muted">—</span>;
}

export function DecisionBadge({decision}: {decision: Decision | null}) {
  if (!decision) return <span className="muted">—</span>;
  return <span className={`decision-badge decision-${decision.decision}`} title={decision.evidence_changed ? 'Evidence changed after this decision' : decision.note || undefined}>{decisionLabels[decision.decision]}{decision.evidence_changed ? ' · review' : ''}</span>;
}

export function ArmDetailBadge({status, hideFromParentName}: {status: ArmDetailStatus | null | undefined; hideFromParentName?: boolean}) {
  if (!status) return null;
  const tone = status === 'collected' ? 'configured' : status === 'unsupported_type' ? 'legacy' : 'review-required';
  const label = armDetailLabels[status];
  return <>
    <span className={`state-badge arm-detail-badge ${tone}`} aria-hidden={hideFromParentName || undefined} title="Azure Resource Manager configuration enrichment">{label}</span>
    {hideFromParentName ? <span className="sr-only">{label}</span> : null}
  </>;
}

const ACTION_CATEGORY_LABELS: Record<string, string> = {
  priority: 'Prioritize first',
  risk: 'Risk and exposure',
  finding: 'Findings and rules',
  evidence: 'Evidence gaps',
  guardrail: 'Guardrails before change',
};

function groupActions(actions: Action[]) {
  const groups: {category: string; label: string; items: Action[]}[] = [];
  const index = new Map<string, number>();
  for (const action of actions) {
    const category = action.category || 'finding';
    if (!index.has(category)) {
      index.set(category, groups.length);
      groups.push({category, label: ACTION_CATEGORY_LABELS[category] || sentence(category), items: []});
    }
    groups[index.get(category)!].items.push(action);
  }
  return groups;
}

function ActionRow({a}: {a: Action}) {
  return (
    <li>
      <div className="action-heading"><strong>{a.title}</strong><span className="action-kind">{sentence(a.kind)}</span></div>
      <p>{a.rationale}</p>
      <small><span className="capitalize">{a.pillar}</span> · Effort {sentence(a.effort)} · Change risk {sentence(a.change_risk)} · Confidence {sentence(a.confidence)}</small>
      {!!a.evidence_codes.length && <small>Evidence: {a.evidence_codes.map(sentence).join(', ')}</small>}
      {!!a.prerequisites.length && <small>Before you start: {a.prerequisites.join(' · ')}</small>}
    </li>
  );
}

export function Actions({actions, grouped = false}: {actions: Action[]; grouped?: boolean}) {
  if (!actions.length) return <p className="inline-empty">The model didn’t suggest next steps beyond the review questions.</p>;
  if (!grouped || actions.every(a => !a.category)) {
    return <ol className="recommended-actions">{actions.map((a, i) => <ActionRow key={i} a={a}/>)}</ol>;
  }
  return (
    <div className="action-category-groups">
      {groupActions(actions).map(group => (
        <section key={group.category} className="action-category-group" aria-label={group.label}>
          <h4 className="action-category-title">{group.label}</h4>
          <ol className="recommended-actions">{group.items.map((a, i) => <ActionRow key={`${group.category}-${i}`} a={a}/>)}</ol>
        </section>
      ))}
    </div>
  );
}
