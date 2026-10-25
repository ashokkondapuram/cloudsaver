'use client';
import {PILLARS, aiStatusLabels, decisionLabels, label, sentence, type AIState, type Action, type Decision, type PillarStatus} from '../../lib/resources';

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

export function Actions({actions}: {actions: Action[]}) {
  if (!actions.length) return <p className="inline-empty">The model didn’t suggest next steps beyond the review questions.</p>;
  return <ol className="recommended-actions">{actions.map((a, i) => <li key={i}>
    <div className="action-heading"><strong>{a.title}</strong><span className="action-kind">{sentence(a.kind)}</span></div>
    <p>{a.rationale}</p>
    <small><span className="capitalize">{a.pillar}</span> · Effort {sentence(a.effort)} · Change risk {sentence(a.change_risk)} · Confidence {sentence(a.confidence)}</small>
    {!!a.evidence_codes.length && <small>Evidence: {a.evidence_codes.map(sentence).join(', ')}</small>}
    {!!a.prerequisites.length && <small>Before you start: {a.prerequisites.join(' · ')}</small>}
  </li>)}</ol>;
}
