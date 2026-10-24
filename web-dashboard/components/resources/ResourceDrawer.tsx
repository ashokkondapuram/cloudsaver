'use client';
import Link from 'next/link';
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
import {AIProcessingDisclosure} from './AIProcessingDisclosure';

function Evidence({detail}: {detail: ResourceDetail}) {
  const text = JSON.stringify(detail.observation?.configuration_snapshot || {}, null, 2);
  return <div className="drawer-section"><h3>Evidence provenance</h3>
    <p>Collector: {detail.observation?.collector_version || 'Not recorded'} · Schema: {detail.observation?.evidence_schema_version || 'Legacy'}</p>
    <p>Observed: {detail.observation?.observed_at ? dateTime(detail.observation.observed_at) : 'Unknown'}. Configuration older than 24 hours requires refresh.</p>
    {detail.assessment.pillars.flatMap(pillar => pillar.checks).map(check => <article key={`${check.pillar}:${check.code}`}><h4>{sentence(check.code)} · {check.status}</h4><p>{check.explanation}</p><small>Evidence fields: {check.evidence_fields.join(', ') || 'None returned'}</small></article>)}
    <details><summary>Saved configuration ({text.length > 16000 ? 'truncated' : 'available fields'})</summary><pre style={{whiteSpace: 'pre-wrap', overflowWrap: 'anywhere'}}>{text.slice(0, 16000)}</pre></details>
  </div>;
}

function Telemetry({detail}:{detail:ResourceDetail}) {
  const metrics=detail.observation?.evidence?.metrics||{};const summaries=detail.observation?.evidence?.metric_summaries||{};
  return <section className="drawer-section"><h3>Saved utilization telemetry</h3><p>Collector-validated 30-day five-minute windows need at least 95% coverage and no gap over one hour. Missing observations remain unknown; legacy summaries retain their own windows.</p>{!Object.keys(metrics).length?<Notice>No metric history was collected for this resource.</Notice>:<div className="grid-scroll" tabIndex={0} aria-label="Saved metric windows"><table className="data-table"><thead><tr><th>Metric</th><th>Window</th><th>Samples</th><th>Validated coverage</th><th>P95 / P99</th></tr></thead><tbody>{Object.entries(metrics).map(([name,m])=>{const summary=summaries[name]||m;return <tr key={name}><td>{sentence(name)}</td><td>{m.window_start?dateTime(m.window_start):'Unknown'} → {m.window_end?dateTime(m.window_end):'Unknown'}</td><td>{m.points?.length??'Summary only'}</td><td>{summary.sufficient===true&&summary.coverage_ratio!=null?`${(summary.coverage_ratio*100).toFixed(1)}%`:'Insufficient or unverified'}</td><td>{summary.p95??'Unknown'} / {summary.p99??'Unknown'}</td></tr>;})}</tbody></table></div>}<p>Low utilization alone does not establish a safe target or approval to change capacity.</p></section>;
}

function Rules({detail}: {detail: ResourceDetail}) {
  return <div className="drawer-section"><h3>Frozen rule evaluations</h3>{!detail.rule_evaluations?.length ? <Notice>No per-rule evaluation records exist in this observation. An absence of findings does not establish a pass.</Notice> : detail.rule_evaluations.map(rule => <article key={rule.rule_id}>
    <h4>{rule.rule_id}</h4><p>{sentence(rule.outcome)} · version {rule.rule_version}</p><p>{rule.reason}</p>{rule.destructive_actions_blocked && <strong>Protected — destructive actions blocked</strong>}</article>)}</div>;
}

function Costs({detail}: {detail: ResourceDetail}) {
  const fields = [['billed_cost_usd', '30-day billed cost'], ['effective_cost_usd','30-day effective cost'], ['retail_estimate_usd', 'Retail review estimate'], ['modeled_future_cost_usd', 'Modeled future cost'],
    ['opportunity_usd', 'Modeled opportunity'], ['verified_realized_savings_usd', 'Verified realized savings']] as const;
  return <div className="drawer-section"><h3>Financial evidence</h3><dl className="settings-key-values">{fields.map(([key, name]) => <div key={key}><dt>{name}</dt><dd>{detail.costs?.[key] == null ? 'Unknown' : money(detail.costs[key])}</dd></div>)}</dl>
    <p>{detail.costs?.explanation || 'Billing and target-cost evidence are not attached to this observation.'}</p>
    {!!detail.financial_overlaps?.length && <Notice tone="warning">Overlapping alternatives share a workload opportunity group. Their estimates must not be added together.<ul>{detail.financial_overlaps.map(item => <li key={`${item.resource_id}:${item.rule_id}`}>{item.resource_name || item.resource_id} · {item.rule_id}</li>)}</ul></Notice>}</div>;
}

function Dependencies({detail}: {detail: ResourceDetail}) {
  return <div className="drawer-section"><h3>Observed typed relationships</h3><p>Only returned, authorized graph nodes are shown. Missing edges do not establish that dependencies are absent.</p>
    {!detail.observation?.dependency_refs?.length ? <Notice>No typed dependency evidence is available. Verify topology, locks, backup and failover independently.</Notice> : <ul>{detail.observation.dependency_refs.map((edge, index) => <li key={index}><strong>{sentence(edge.relationship)} · {edge.verification_state}</strong><p>{edge.from_resource_id} → {edge.to_resource_id}</p><small>Observed: {edge.observed_at ? dateTime(edge.observed_at) : 'Unknown'}</small></li>)}</ul>}
    {!!detail.assessment.protected_reasons.length && <Notice>Protection signals: {detail.assessment.protected_reasons.map(sentence).join(', ')}. These prevent destructive changes.</Notice>}</div>;
}

const formatDay = (value: string) => new Date(value + 'T00:00:00').toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'});

function Overview({detail}: {detail: ResourceDetail}) {
  const a = detail.assessment;
  return <>
    <div className="drawer-section"><Link className="button secondary" href={`/agents?resource=${encodeURIComponent(a.resource_id)}`}>Draft a safe tag or snapshot plan</Link><h3>Resource identity</h3><dl className="detail-metadata">
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
    <h4>Deterministic evidence confidence: {result.confidence_band?.replaceAll('_', ' ') || 'Not recorded'}</h4>
    <p className="inline-help">This band describes saved evidence completeness. It is not a measured model-accuracy rate.</p>
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
      <AIProcessingDisclosure targets={targets} targetId={target}/>
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
  const tabs = [{id: 'overview', label: 'Overview', icon: ShieldCheck}, {id: 'evidence', label: 'Evidence', icon: ListChecks},
    {id:'telemetry',label:'30d telemetry',icon:ListChecks}, {id: 'rules', label: 'Rules', icon: ListChecks}, {id: 'cost', label: 'Cost', icon: ListChecks},
    {id: 'dependencies', label: 'Dependencies', icon: ShieldCheck}, {id: 'ai', label: 'AI Advice', icon: BrainCircuit},
    {id: 'history', label: 'History', icon: History}, {id: 'decision', label: 'Decisions', icon: ListChecks}];
  const current = detail && detail.assessment.resource_key === resourceKey ? detail : null;
  return <Dialog open={!!resourceKey} onClose={onClose} title="Resource analysis" drawer>
    {error ? <div className="dialog-content"><Notice tone="error">{error}</Notice></div> : !current ? <Loading label="Loading resource analysis…"/> : <>
      <div className="finding-drawer-header"><div className="finding-badges"><ProviderBadge provider={current.assessment.provider}/><span className={`state-badge ${current.assessment.disposition === 'protected' ? 'protected-intent' : 'review-required'}`}>{current.assessment.disposition === 'protected' ? 'Protected intent' : 'Review required'}</span><AIStatusBadge ai={current.ai}/></div><h2>{current.assessment.resource_name || current.assessment.resource_id}</h2><p>{current.assessment.finding_count} finding{current.assessment.finding_count === 1 ? '' : 's'} · {sentence(current.assessment.review_priority)} · <PillarDots pillars={Object.fromEntries(current.assessment.pillars.map(p => [p.pillar, p.status]))}/></p></div>
      <div className="drawer-tabs" role="tablist" aria-label="Resource analysis views">{tabs.map(t => <button key={t.id} id={`${id}-${t.id}-tab`} role="tab" aria-selected={tab === t.id} aria-controls={`${id}-${t.id}`} className={tab === t.id ? 'active' : ''} onClick={() => setTab(t.id)}><t.icon size={15}/>{t.label}</button>)}</div>
      <div className="drawer-tab-content" role="tabpanel" id={`${id}-${tab}`} aria-labelledby={`${id}-${tab}-tab`}>
        {tab === 'overview' ? <Overview detail={current}/> : tab === 'evidence' ? <Evidence detail={current}/> : tab==='telemetry'?<Telemetry detail={current}/>:tab === 'rules' ? <Rules detail={current}/> : tab === 'cost' ? <Costs detail={current}/> : tab === 'dependencies' ? <Dependencies detail={current}/> : tab === 'ai' ? <><Assessment detail={current}/><Questions detail={current} onChange={changed}/></> : tab === 'history' ? <HistoryTab detail={current}/> : <DecisionTab detail={current} onChange={changed}/>}
      </div>
      <div className="drawer-footer"><ShieldCheck size={15}/>AI status: {aiStatusLabels[current.ai.status]}. Advice is unverified and never changes cloud resources.</div>
    </>}
  </Dialog>;
}
