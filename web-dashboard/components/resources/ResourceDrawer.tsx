'use client';
import {useEffect, useId, useRef, useState} from 'react';
import {BrainCircuit, CheckCircle2, History, ListChecks, MessageSquareText, ShieldCheck} from 'lucide-react';
import {api} from '../../lib/api';
import {dateTime, money, ruleLabel} from '../../lib/finops';
import {aiStatusLabels, decisionLabels, label, sentence, type DecisionKind, type ResourceDetail, type ResourceHistory, type Targets} from '../../lib/resources';
import {useWorkspace} from '../WorkspaceProvider';
import {Dialog} from '../ui/dialog';
import {EvidenceRadar} from '../drawer/EvidenceRadar';
import {Loading, Notice, ProviderBadge} from '../ui/shared';
import {Actions, AIStatusBadge, PillarDots} from './ResourceParts';

const formatDay = (value: string) => new Date(value + 'T00:00:00').toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'});

function Overview({detail}: {detail: ResourceDetail}) {
  const a = detail.assessment;
  return <>
    <div className="drawer-section"><h3>Resource identity</h3><dl className="detail-metadata">
      <div><dt>Provider</dt><dd><ProviderBadge provider={a.provider}/></dd></div><div><dt>Resource type</dt><dd>{a.resource_type || 'Not supplied'}</dd></div>
      <div><dt>Group / namespace</dt><dd>{a.resource_group || 'Not supplied'}</dd></div><div><dt>Account / scope</dt><dd><code>{a.scope_id}</code></dd></div>
      <div className="full-width"><dt>Resource ID</dt><dd><code>{a.resource_id}</code></dd></div></dl></div>
    <div className="drawer-section"><h3>Findings on this resource</h3><ul className="assessment-guardrails">{detail.findings.map(f => <li key={f.rule_id}>{ruleLabel(f.rule_id)}<p className="inline-help">{f.details}</p></li>)}</ul></div>
    <div className="drawer-section"><h3>Merged five-pillar assessment</h3><p className="inline-help">{a.evidence_coverage.observed} of {a.evidence_coverage.total} checks have observed evidence. Each check keeps its most severe status across findings. Known retail estimate: {money(a.retail_estimate_usd)}.</p>
      {!!a.protected_reasons.length && <Notice tone="warning">Recovery or retention intent detected: {a.protected_reasons.map(label).join(', ')}. AI can't suggest decommissioning this resource.</Notice>}
      {a.observation.status !== 'recent' && <Notice tone="warning">This observation is older than {a.observation.max_age_hours} hours or its time can't be verified. Run a new scan before planning a change.</Notice>}
      <EvidenceRadar pillars={a.pillars} onInspect={() => undefined}/>
      <div className="pillar-list">{a.pillars.map(p => <details key={p.pillar} open={p.status === 'risk'}><summary><strong className="capitalize">{p.pillar}</strong><span className={`assessment-state ${p.status}`}>{p.status === 'risk' ? 'Risk observed' : p.status === 'observed' ? 'Evidence observed' : 'Evidence incomplete'}</span></summary><div>{p.checks.map(c => <article key={c.code}><span className={`assessment-dot ${c.status}`}/><div><h4>{label(c.code)}</h4><p>{c.explanation}</p></div></article>)}</div></details>)}</div></div>
    <div className="drawer-section"><h3>Required guardrails</h3><ul className="assessment-guardrails">{a.guardrails.map(code => <li key={code}>{label(code)}</li>)}</ul></div>
    <p className="inline-help" title={a.evidence_digest}>Policy {a.policy_version} · Evidence fingerprint {a.evidence_digest.slice(0, 16)}</p>
  </>;
}

function Assessment({detail}: {detail: ResourceDetail}) {
  const result = detail.ai_result;
  if (!result) return <div className="drawer-section"><p className="inline-empty">{detail.ai.status === 'queued' || detail.ai.status === 'running' ? 'This resource is in an AI batch. Results appear here when it completes.' : detail.ai.status === 'failed' ? `The last AI run didn't complete (${label(detail.ai.reason || 'unknown')}). You can include it in a new batch.` : 'No AI assessment yet. Select this resource on the Resources page and run an AI assessment.'}</p></div>;
  return <div className="ai-result" aria-live="polite">
    <span className="eyebrow">UNVERIFIED MODEL ADVICE · {result.model}</span>
    {detail.ai.status === 'stale' && <Notice tone="warning">The resource evidence changed after this assessment. Run a new AI assessment before relying on it.</Notice>}
    <Notice tone="warning">{result.warning}</Notice>
    <h4>Suggested risk: {result.advice.risk_level}</h4><p>{result.advice.summary}</p>
    <h4>Recommended next steps</h4><Actions actions={result.advice.recommended_actions || []}/>
    {result.advice.pillars.map(p => <article key={p.pillar}><h4 className="capitalize">{p.pillar}</h4><p>{p.observation}</p><small>Saved check references: {p.evidence_codes.map(label).join(', ') || 'None — evidence gap'}</small></article>)}
    <h4>Questions for independent review</h4><ul>{result.advice.review_questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
    {result.usage && <p className="inline-help">Provider-reported usage: {result.usage.input_tokens ?? 'Unknown'} input tokens · {result.usage.output_tokens ?? 'Unknown'} output tokens. Billed cost is unavailable.</p>}
    <p className="inline-help">Assessed {detail.ai.created_at ? dateTime(detail.ai.created_at) : 'at an unknown time'}. The deterministic guardrails remain required regardless of model text.</p>
  </div>;
}

function Questions({detail, onChange}: {detail: ResourceDetail; onChange: () => void}) {
  const {token, canAdmin} = useWorkspace();
  const [targets, setTargets] = useState<Targets | null>(null), [target, setTarget] = useState(''), [question, setQuestion] = useState('');
  const [ack, setAck] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const attempt = useRef<string | null>(null);
  useEffect(() => {
    const request = new AbortController();
    api<Targets>('/ai/targets', token, {signal: request.signal}).then(t => {setTargets(t); setTarget(t.targets[0]?.target_id || '');}).catch(() => setTargets({enabled: false, hourly_attempt_limit: 0, targets: []}));
    return () => request.abort();
  }, [token]);
  async function ask(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !ack || !target || question.trim().length < 3) return;
    attempt.current ||= crypto.randomUUID();
    setBusy(true); setError('');
    try {
      await api(`/scans/${detail.scan_id}/resources/${detail.assessment.resource_key}/questions`, token, {body: {question: question.trim(), target_id: target,
        evidence_digest: detail.assessment.evidence_digest, idempotency_key: attempt.current, acknowledge_external_processing: true}});
      setQuestion(''); attempt.current = null; onChange();
    } catch (cause) {setError((cause as Error).message);} finally {setBusy(false);}
  }
  return <>
    <div className="drawer-section"><h3>Follow-up questions</h3><p className="inline-help">Answers use only the saved evidence and the latest AI assessment for this resource. You can ask up to 5 questions per resource per scan; {detail.followups_remaining} remaining.</p>
      {!detail.followups.length ? <p className="inline-empty">No questions yet.</p> : <div className="followup-list">{detail.followups.map(f => <article key={f.id}><strong>{f.question}</strong><p>{f.answer.answer}</p>{!!f.answer.evidence_codes.length && <small>Evidence: {f.answer.evidence_codes.map(label).join(', ')}</small>}{!!f.answer.limitations.length && <small>Limitations: {f.answer.limitations.join(' · ')}</small>}<small>{dateTime(f.created_at)}</small></article>)}</div>}</div>
    {!canAdmin ? <p className="inline-help">A workspace administrator can ask questions.</p> : !targets?.enabled || !targets.targets.length ? <p className="inline-empty">No approved AI target is enabled for this workspace.</p> : detail.followups_remaining > 0 && <form className="drawer-section followup-form" onSubmit={ask}>
      <label className="ai-target-label">Approved model target<select value={target} disabled={busy} onChange={e => setTarget(e.target.value)}>{targets.targets.map(t => <option key={t.target_id} value={t.target_id}>{t.target_id} · {t.model}</option>)}</select></label>
      <label className="ai-target-label">Your question<textarea maxLength={500} rows={3} value={question} disabled={busy} onChange={e => setQuestion(e.target.value)} placeholder="For example: What evidence is missing before this disk can be removed?"/></label>
      <small className="inline-help">{question.length}/500 · Your question is sent to the model with the sanitized evidence.</small>
      <label className="checkbox-row ai-ack"><input type="checkbox" checked={ack} disabled={busy} onChange={e => setAck(e.target.checked)}/>I acknowledge external processing of my question and this sanitized evidence.</label>
      {error && <Notice tone="error">{error}</Notice>}
      <button className="button primary" type="submit" disabled={busy || !ack || question.trim().length < 3}><MessageSquareText size={16}/>{busy ? 'Asking…' : 'Ask question'}</button>
    </form>}
  </>;
}

function HistoryTab({detail}: {detail: ResourceDetail}) {
  const {token} = useWorkspace();
  const [data, setData] = useState<ResourceHistory | null>(null), [error, setError] = useState('');
  useEffect(() => {
    const request = new AbortController();
    api<ResourceHistory>(`/resources/${detail.assessment.resource_key}/history`, token, {signal: request.signal}).then(setData).catch(cause => {if (!request.signal.aborted) setError((cause as Error).message);});
    return () => request.abort();
  }, [detail.assessment.resource_key, token]);
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!data) return <Loading label="Loading resource history…"/>;
  return <>
    <div className="drawer-section"><h3>Across recent scans</h3><div className="summary-table-scroll"><table className="summary-table"><thead><tr><th>Scan</th><th>Priority</th><th>Pillars</th><th>Changes</th></tr></thead><tbody>{data.scans.map(s => <tr key={s.scan_id} className={s.scan_id === detail.scan_id ? 'row-selected' : ''}><td>{dateTime(s.timestamp)}</td><td>{s.present ? sentence(s.review_priority || '') : 'Not flagged'}</td><td>{s.pillars ? <PillarDots pillars={s.pillars}/> : '—'}</td><td>{s.changes.length ? s.changes.map(sentence).join(', ') : 'No change'}</td></tr>)}</tbody></table></div></div>
    <div className="drawer-section"><h3>AI assessments</h3>{data.ai_results.length ? <ul className="assessment-guardrails">{data.ai_results.map(r => <li key={r.assessment_id}>{dateTime(r.created_at)} · {r.model} · suggested risk {r.risk_level}</li>)}</ul> : <p className="inline-empty">No AI assessments yet.</p>}</div>
    <div className="drawer-section"><h3>Decisions</h3>{data.decisions.length ? <ul className="assessment-guardrails">{data.decisions.map(d => <li key={d.id}>{decisionLabels[d.decision]} · {dateTime(d.created_at)}{d.note ? ` · ${d.note}` : ''}</li>)}</ul> : <p className="inline-empty">No decisions recorded.</p>}</div>
  </>;
}

function DecisionTab({detail, onChange}: {detail: ResourceDetail; onChange: () => void}) {
  const {token, canAdmin, notify} = useWorkspace();
  const [decision, setDecision] = useState<DecisionKind>('accept'), [note, setNote] = useState(''), [until, setUntil] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const today = new Date(), max = new Date(today.getTime() + 365 * 86400000);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const noteRequired = decision !== 'accept';
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (busy || (noteRequired && !note.trim())) return;
    setBusy(true); setError('');
    try {
      await api(`/resources/${detail.assessment.resource_key}/decisions`, token, {body: {scan_id: detail.scan_id, decision, note: note.trim(),
        defer_until: decision === 'defer' && until ? until : null, evidence_digest: detail.assessment.evidence_digest}});
      setNote(''); setUntil(''); notify('Decision saved.'); onChange();
    } catch (cause) {setError((cause as Error).message);} finally {setBusy(false);}
  }
  const current = detail.decision;
  return <>
    <div className="drawer-section"><h3>Current decision</h3>{current ? <><p><strong>{decisionLabels[current.decision]}</strong> · {dateTime(current.created_at)}{current.defer_until ? ` · until ${formatDay(current.defer_until)}` : ''}</p>{current.note && <p className="inline-help">{current.note}</p>}{current.evidence_changed && <Notice tone="warning">The evidence changed after this decision. Review the resource again.</Notice>}</> : <p className="inline-empty">No decision recorded yet.</p>}</div>
    {canAdmin ? <form className="drawer-section decision-form" onSubmit={save}><h3>Record a decision</h3>
      <div className="segmented-control" role="radiogroup" aria-label="Decision">{(['accept', 'dismiss', 'defer'] as const).map(value => <button type="button" key={value} role="radio" aria-checked={decision === value} aria-pressed={decision === value} onClick={() => setDecision(value)}>{value === 'accept' ? 'Accept' : value === 'dismiss' ? 'Dismiss' : 'Defer'}</button>)}</div>
      <label className="ai-target-label">Note{noteRequired ? '' : ' (optional)'}<textarea maxLength={1000} rows={3} value={note} onChange={e => setNote(e.target.value)} placeholder={decision === 'dismiss' ? 'Why this resource doesn’t need action' : decision === 'defer' ? 'What you are waiting for' : 'Context for your team'}/></label>
      {decision === 'defer' && <label className="ai-target-label">Review again on (optional)<input type="date" min={iso(new Date(today.getTime() + 86400000))} max={iso(max)} value={until} onChange={e => setUntil(e.target.value)}/></label>}
      <p className="inline-help">Decisions are recorded for your workspace and apply to this resource in future scans. A decision doesn’t change any cloud resource.</p>
      {error && <Notice tone="error">{error}</Notice>}
      <button className="button primary" type="submit" disabled={busy || (noteRequired && !note.trim())}><CheckCircle2 size={16}/>{busy ? 'Saving…' : 'Save decision'}</button>
    </form> : <p className="inline-help">A workspace administrator can record decisions.</p>}
  </>;
}

export function ResourceDrawer({scanId, resourceKey, onClose, onChange}: {scanId: string; resourceKey: string | null; onClose: () => void; onChange: () => void}) {
  const {token} = useWorkspace();
  const [detail, setDetail] = useState<ResourceDetail | null>(null), [error, setError] = useState(''), [tab, setTab] = useState('overview'), [version, setVersion] = useState(0);
  const id = useId();
  useEffect(() => {setTab('overview');}, [resourceKey]);
  useEffect(() => {
    if (!resourceKey) return;
    const request = new AbortController();
    setError('');
    api<ResourceDetail>(`/scans/${scanId}/resources/${resourceKey}`, token, {signal: request.signal}).then(result => {if (!request.signal.aborted) setDetail(result);})
      .catch(cause => {if (!request.signal.aborted) {setDetail(null); setError((cause as Error).message);}});
    return () => request.abort();
  }, [scanId, resourceKey, token, version]);
  const changed = () => {setVersion(v => v + 1); onChange();};
  const tabs = [{id: 'overview', label: 'Overview', icon: ShieldCheck}, {id: 'ai', label: 'AI assessment', icon: BrainCircuit}, {id: 'questions', label: 'Questions', icon: MessageSquareText}, {id: 'history', label: 'History', icon: History}, {id: 'decision', label: 'Decision', icon: ListChecks}];
  const current = detail && detail.assessment.resource_key === resourceKey ? detail : null;
  return <Dialog open={!!resourceKey} onClose={onClose} title="Resource analysis" drawer>
    {error ? <div className="dialog-content"><Notice tone="error">{error}</Notice></div> : !current ? <Loading label="Loading resource analysis…"/> : <>
      <div className="finding-drawer-header"><div className="finding-badges"><ProviderBadge provider={current.assessment.provider}/><span className={`state-badge ${current.assessment.disposition === 'protected' ? 'protected-intent' : 'review-required'}`}>{current.assessment.disposition === 'protected' ? 'Protected intent' : 'Review required'}</span><AIStatusBadge ai={current.ai}/></div><h2>{current.assessment.resource_name || current.assessment.resource_id}</h2><p>{current.assessment.finding_count} finding{current.assessment.finding_count === 1 ? '' : 's'} · {sentence(current.assessment.review_priority)} · <PillarDots pillars={Object.fromEntries(current.assessment.pillars.map(p => [p.pillar, p.status]))}/></p></div>
      <div className="drawer-tabs" role="tablist" aria-label="Resource analysis views">{tabs.map(t => <button key={t.id} id={`${id}-${t.id}-tab`} role="tab" aria-selected={tab === t.id} aria-controls={`${id}-${t.id}`} className={tab === t.id ? 'active' : ''} onClick={() => setTab(t.id)}><t.icon size={15}/>{t.label}</button>)}</div>
      <div className="drawer-tab-content" role="tabpanel" id={`${id}-${tab}`} aria-labelledby={`${id}-${tab}-tab`}>
        {tab === 'overview' ? <Overview detail={current}/> : tab === 'ai' ? <Assessment detail={current}/> : tab === 'questions' ? <Questions detail={current} onChange={changed}/> : tab === 'history' ? <HistoryTab detail={current}/> : <DecisionTab detail={current} onChange={changed}/>}
      </div>
      <div className="drawer-footer"><ShieldCheck size={15}/>AI status: {aiStatusLabels[current.ai.status]}. Advice is unverified and never changes cloud resources.</div>
    </>}
  </Dialog>;
}
