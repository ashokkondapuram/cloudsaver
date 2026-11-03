'use client';
import Link from 'next/link';
import {useEffect, useRef, useState} from 'react';
import {Activity, Bot, BrainCircuit, CheckCircle2, CircleDollarSign, FileCode2, Gauge, History, LayoutDashboard, ListChecks, MessageSquareText, ShieldCheck, ShieldAlert} from 'lucide-react';
import {api} from '../../lib/api';
import {dateTime, money, ruleLabel, shortDate} from '../../lib/finops';
import {decisionLabels, label, sentence, type DecisionKind, type ResourceDetail, type ResourceHistory, type Targets} from '../../lib/resources';
import {useWorkspace} from '../WorkspaceProvider';
import {Dialog} from '../ui/dialog';
import {TabWorkspaceShell} from '../ui/TabWorkspaceShell';
import {resourceDrawerLeads} from '../../lib/workspace-tab-leads';
import {EvidenceRadar} from '../drawer/EvidenceRadar';
import {Loading, Notice, ProviderBadge} from '../ui/shared';
import {Actions, AIStatusBadge, ArmDetailBadge, PillarDots} from './ResourceParts';
import {AIProcessingDisclosure} from './AIProcessingDisclosure';
import {ActionSafetyPanel} from './ActionSafetyPanel';
import {FinancialFiveStrip} from './FinancialFiveStrip';
import {actionEvidenceFromResource} from '../../lib/control-plane';
import {CodeReview} from '../drawer/FindingDrawer';
import {ArchitecturalAssessment} from '../ServiceAnalysis';
import {findingKey} from '../../lib/finops';

function Evidence({detail}: {detail: ResourceDetail}) {
  const snapshot = detail.configuration_detail || detail.observation?.configuration_snapshot || {};
  const text = JSON.stringify(snapshot, null, 2);
  const readiness = detail.analysis_readiness || detail.observation?.evidence?.analysis_readiness;
  const armDetail = detail.assessment.arm_detail;
  return <div className="drawer-section"><h3>Evidence provenance</h3>
    <dl className="settings-key-values"><div><dt>Collector</dt><dd>{detail.observation?.collector_version || 'Not recorded'}</dd></div><div><dt>Schema</dt><dd>{detail.evidence_schema_version || detail.observation?.evidence_schema_version || 'Legacy'}</dd></div><div><dt>Observed</dt><dd>{detail.observation?.observed_at ? dateTime(detail.observation.observed_at) : 'Unknown'}</dd></div>
    {armDetail && <div><dt>ARM configuration detail</dt><dd><ArmDetailBadge status={armDetail}/></dd></div>}
    {readiness && <><div><dt>Configuration evidence</dt><dd>{sentence(readiness.configuration || 'unknown')}{readiness.configuration_total ? ` · ${readiness.configuration_observed ?? 0}/${readiness.configuration_total}` : ''}</dd></div>
    {!!readiness.telemetry_pending_rule_ids?.length && <div><dt>Telemetry still needed</dt><dd>{readiness.telemetry_pending_rule_ids.map(ruleLabel).join(', ')}</dd></div>}</>}
    </dl>
    <p className="inline-help">Configuration older than 24 hours needs a new scan. Per-check evidence is listed under Five-pillar checks above.</p>
    <details className="drawer-disclosure"><summary>Saved configuration{text.length > 16000 ? ' (truncated)' : ''}</summary><pre className="config-snapshot">{text.slice(0, 16000)}</pre></details>
  </div>;
}

function Telemetry({detail}:{detail:ResourceDetail}) {
  const metrics=detail.observation?.evidence?.metrics||{};const summaries=detail.observation?.evidence?.metric_summaries||{};
  return <section className="drawer-section"><h3>Utilization telemetry</h3><p className="inline-help">Validated 30-day windows need at least 95% coverage and no gap over one hour. Missing observations stay unknown.</p>{!Object.keys(metrics).length?<Notice>No metric history was collected for this resource.</Notice>:<div className="summary-table-scroll" tabIndex={0} aria-label="Saved metric windows"><table className="summary-table"><thead><tr><th>Metric</th><th>Window</th><th>Samples</th><th>Coverage</th><th>P95 / P99</th></tr></thead><tbody>{Object.entries(metrics).map(([name,m])=>{const summary=summaries[name]||m;return <tr key={name}><td>{sentence(name)}</td><td>{m.window_start?shortDate(m.window_start):'Unknown'} – {m.window_end?shortDate(m.window_end):'Unknown'}</td><td>{m.points?.length.toLocaleString()??'Summary only'}</td><td>{summary.sufficient===true&&summary.coverage_ratio!=null?`${(summary.coverage_ratio*100).toFixed(1)}%`:'Unverified'}</td><td>{summary.p95??'—'} / {summary.p99??'—'}</td></tr>;})}</tbody></table></div>}<p className="inline-help">Low utilization alone doesn’t establish a safe target or approval to change capacity.</p></section>;
}

const decimal = (value: number | null | undefined, digits = 2) => value == null ? 'Unknown' : value.toLocaleString('en-US', {maximumFractionDigits: digits});
const unitCost = (value: number) => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4}).format(value);

function Observability({detail}: {detail: ResourceDetail}) {
  const signals = detail.observability;
  if (!signals) return <div className="drawer-section"><h3>Observability</h3><Notice>No connector metrics or traces are linked to this resource. Workspace admins can add Prometheus, REST metrics, Tempo or Jaeger connectors in Settings, under Integrations.</Notice><p><Link className="text-link" href="/settings?tab=integrations">Open integrations</Link></p></div>;
  return <>
    {signals.latency_reasons.length > 0 && <Notice tone="warning">Latency-sensitive: {signals.latency_reasons.join('; ')}. Review capacity changes against these signals before you approve them.</Notice>}
    <div className="drawer-section"><h3>Cost per 1,000 requests</h3>
      <p className="enterprise-amount">{signals.cost_per_1000_requests_usd == null ? 'Unknown' : unitCost(signals.cost_per_1000_requests_usd)}</p>
      <p className="inline-help">{signals.cost_per_1000_requests_reason || 'Average daily billed cost over the last 30 days, divided by average daily requests from the linked request-rate metric.'}</p></div>
    <div className="drawer-section"><h3>Linked metrics</h3>{!signals.metrics.length ? <Notice>No metric series are linked to this resource.</Notice> : <div className="summary-table-scroll" tabIndex={0} aria-label="Linked connector metrics"><table className="summary-table"><thead><tr><th>Metric</th><th>Source</th><th>Window</th><th>Coverage</th><th>P50 / P95 / Max</th></tr></thead><tbody>{signals.metrics.map((m, i) => <tr key={`${m.connector}:${m.query_id}:${i}`}><td>{sentence(m.metric === 'custom' ? m.query_id : m.metric)}{m.unit && <small> ({m.unit})</small>}</td><td>{m.connector}</td><td>{m.window_start ? shortDate(m.window_start) : 'Unknown'} – {m.window_end ? shortDate(m.window_end) : 'Unknown'}</td><td>{decimal(m.coverage_pct, 1)}%</td><td>{decimal(m.p50)} / {decimal(m.p95)} / {decimal(m.max)}</td></tr>)}</tbody></table></div>}</div>
    <div className="drawer-section"><h3>Linked services</h3>{!signals.services.length ? <Notice>No traced services are linked to this resource.</Notice> : <div className="drawer-card-list">{signals.services.map(s => <article key={`${s.connector}:${s.service}`} className="drawer-card"><header><h4>{s.service}</h4><span className="assessment-state unknown">{s.sampled ? `${decimal(s.traces_sampled ?? 0, 0)} sampled traces` : 'Trace metrics'}</span></header>
      <dl className="settings-key-values"><div><dt>Requests per second</dt><dd>{decimal(s.requests_per_second)}</dd></div><div><dt>Error rate</dt><dd>{s.error_rate_pct == null ? 'Unknown' : `${decimal(s.error_rate_pct)}%`}</dd></div><div><dt>Latency P50 / P95</dt><dd>{decimal(s.latency_p50_ms, 0)} ms / {decimal(s.latency_p95_ms, 0)} ms</dd></div></dl>
      {s.dependencies.length > 0 && <p className="inline-help">Calls: {s.dependencies.map(d => `${d.service} (${decimal(d.calls, 0)})`).join(', ')}</p>}
      <small>{s.connector} · {s.window_start ? dateTime(s.window_start) : 'Unknown'} – {s.window_end ? dateTime(s.window_end) : 'Unknown'}</small></article>)}</div>}</div>
  </>;
}

function Rules({detail}: {detail: ResourceDetail}) {
  return <div className="drawer-section"><h3>Rule evaluations</h3>{!detail.rule_evaluations?.length ? <Notice>This observation has no per-rule evaluation records. No findings doesn’t mean a rule passed.</Notice> : <div className="drawer-card-list">{detail.rule_evaluations.map(rule => <article key={rule.rule_id} className="drawer-card">
    <header><h4>{ruleLabel(rule.rule_id)}</h4><span className={`assessment-state ${rule.outcome === 'condition_detected' ? 'risk' : rule.outcome === 'condition_not_detected' ? 'observed' : 'unknown'}`}>{sentence(rule.outcome)}</span></header><p>{rule.reason}</p><small><code>{rule.rule_id}</code> · version {rule.rule_version}{rule.destructive_actions_blocked ? ' · Destructive actions blocked' : ''}</small></article>)}</div>}</div>;
}

const utcDayOffset = (days: number) => {
  const now = new Date();
  const base = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return new Date(base + days * 86400000).toISOString().slice(0, 10);
};

type AzureCostSnapshot = {
  schema_version?: string;
  resource_type?: string | null;
  arm?: {status: string; resource_type?: string; location?: string; arm_api_version?: string; document?: {typed_configuration?: Record<string, unknown>}};
  cost_management: {observation: {start: string; end: string; billed_cost_usd: number | null; effective_cost_usd: number | null; currency: string | null; coverage_complete: boolean}; baseline: AzureCostSnapshot['cost_management']['observation'] | null};
  retail_prices: {monthly_run_rate_usd: number | null; window_run_rate_usd: number | null};
  financial: {balance: NonNullable<ResourceDetail['costs']>; booked_savings_usd: number | null; finance_reconciled_benefit_usd?: number | null};
  warning: string | null;
};

function Costs({detail, onFetched}: {detail: ResourceDetail; onFetched: () => void}) {
  const {token, canAdmin, canBill} = useWorkspace();
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [observationEnd, setObservationEnd] = useState(() => utcDayOffset(0));
  const [observationStart, setObservationStart] = useState(() => utcDayOffset(-30));
  const [baselineEnd, setBaselineEnd] = useState(() => utcDayOffset(-30));
  const [baselineStart, setBaselineStart] = useState(() => utcDayOffset(-60));
  const [azureEvidence, setAzureEvidence] = useState<AzureCostSnapshot | null>(null);
  const supplemental = [['modeled_future_cost_usd', 'Modeled future cost', 'USD']] as const;
  async function importCost() {
    setBusy(true); setError('');
    try {
      const qs = new URLSearchParams({
        resource_id: detail.assessment.resource_id,
        scope_id: detail.assessment.scope_id,
        start: observationStart,
        end: observationEnd,
      }).toString();
      await api(`/finops/resource-cost?${qs}`, token, {method: 'POST', body: {}});
      onFetched();
    } catch (cause) {setError((cause as Error).message);}
    finally {setBusy(false);}
  }
  async function fetchAzureCosts() {
    setBusy(true); setError('');
    try {
      const qs = new URLSearchParams({
        resource_id: detail.assessment.resource_id,
        scope_id: detail.assessment.scope_id,
        start: observationStart,
        end: observationEnd,
        baseline_start: baselineStart,
        baseline_end: baselineEnd,
        scan_id: detail.scan_id,
      });
      const snapshot = await api<AzureCostSnapshot>(`/finops/azure-resource-costs?${qs}`, token);
      setAzureEvidence(snapshot);
    } catch (cause) {setError((cause as Error).message);}
    finally {setBusy(false);}
  }
  const currency = azureEvidence?.cost_management.observation.currency || detail.costs?.currency || 'USD';
  const obs = azureEvidence?.cost_management.observation;
  const base = azureEvidence?.cost_management.baseline;
  const fin = azureEvidence?.financial;
  return <div className="drawer-section drawer-costs-panel"><h3>Costs</h3>
    <FinancialFiveStrip detail={detail} token={token} canAdmin={canAdmin} knownOnly/>
    {detail.assessment.provider === 'azure' && canBill && <div className="outcome-form drawer-cost-fetch">
      <p className="inline-help">Live Azure Cost Management (billed + amortized) and scan retail meters. End dates are exclusive UTC day boundaries.</p>
      <label>Observation start<input type="date" value={observationStart} onChange={e => setObservationStart(e.target.value)}/></label>
      <label>Observation end<input type="date" value={observationEnd} onChange={e => setObservationEnd(e.target.value)}/></label>
      <label>Baseline start<input type="date" value={baselineStart} onChange={e => setBaselineStart(e.target.value)}/></label>
      <label>Baseline end<input type="date" value={baselineEnd} onChange={e => setBaselineEnd(e.target.value)}/></label>
      <div className="drawer-header-actions">
        <button className="button primary" disabled={busy} onClick={fetchAzureCosts}>{busy ? 'Calling Azure…' : 'Fetch retail + billed from Azure'}</button>
        <button className="button secondary" disabled={busy} onClick={importCost}>{busy ? 'Importing…' : 'Import observation window to billing'}</button>
      </div>
    </div>}
    {error && <Notice tone="error">{error}</Notice>}
    {azureEvidence && obs && fin && <dl className="settings-key-values azure-cost-snapshot">
      {azureEvidence.resource_type && <div><dt>ARM resource type</dt><dd><code>{azureEvidence.resource_type}</code>{azureEvidence.arm?.location ? ` · ${azureEvidence.arm.location}` : ''}</dd></div>}
      <div><dt>Observation billed</dt><dd>{money(obs.billed_cost_usd, currency)} · {formatDay(obs.start)} – {formatDay(obs.end)}</dd></div>
      <div><dt>Observation effective</dt><dd>{money(obs.effective_cost_usd, currency)}</dd></div>
      <div><dt>Azure retail (window)</dt><dd>{money(azureEvidence.retail_prices.window_run_rate_usd, currency)} · monthly {money(azureEvidence.retail_prices.monthly_run_rate_usd, currency)}</dd></div>
      <div><dt>Billed vs retail</dt><dd>{money(fin.balance.billed_vs_retail_usd, currency)}</dd></div>
      {base && <div><dt>Baseline billed</dt><dd>{money(base.billed_cost_usd, currency)} · {formatDay(base.start)} – {formatDay(base.end)}</dd></div>}
      <div><dt>Booked savings (billing delta)</dt><dd>{fin.booked_savings_usd == null ? 'Unknown' : money(fin.booked_savings_usd, currency)}</dd></div>
      {fin.finance_reconciled_benefit_usd != null && <div><dt>Finance reconciled benefit</dt><dd>{money(fin.finance_reconciled_benefit_usd, currency)}</dd></div>}
    </dl>}
    {azureEvidence?.warning && <Notice tone="warning">{azureEvidence.warning}</Notice>}
    {supplemental.map(([key, name, cur]) => {
      const value = detail.costs?.[key];
      if (value == null) return null;
      return (
        <dl key={key} className="settings-key-values"><div><dt>{name}</dt><dd>{money(value, cur)}</dd></div></dl>
      );
    })}
    <p className="inline-help">{detail.costs?.explanation || 'Billing and target-cost evidence are not attached to this observation.'}</p>
    {!!detail.financial_overlaps?.length && <Notice tone="warning">Overlapping alternatives share a workload opportunity group. Their estimates must not be added together.<ul>{detail.financial_overlaps.map(item => <li key={`${item.resource_id}:${item.rule_id}`}>{item.resource_name || item.resource_id} · {ruleLabel(item.rule_id)}</li>)}</ul></Notice>}</div>;
}

function Dependencies({detail}: {detail: ResourceDetail}) {
  return <div className="drawer-section"><h3>Dependencies</h3><p className="inline-help">Only authorized relationships returned by the collector appear here. A missing edge doesn’t prove there’s no dependency.</p>
    {!detail.observation?.dependency_refs?.length ? <Notice>No dependency evidence is available. Verify topology, locks, backup and failover before you change this resource.</Notice> : <div className="drawer-card-list">{detail.observation.dependency_refs.map((edge, index) => <article key={index} className="drawer-card"><header><h4>{sentence(edge.relationship)}</h4><span className="assessment-state unknown">{sentence(edge.verification_state)}</span></header><p><code>{edge.from_resource_id}</code> → <code>{edge.to_resource_id}</code></p><small>Observed {edge.observed_at ? dateTime(edge.observed_at) : 'at an unknown time'}</small></article>)}</div>}
    {!!detail.assessment.protected_reasons.length && <Notice>Protection signals: {detail.assessment.protected_reasons.map(sentence).join(', ')}. These prevent destructive changes.</Notice>}</div>;
}

const formatDay = (value: string) => new Date(value + 'T00:00:00').toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'});
const pillarState = (status: string) => status === 'risk' ? 'Risk observed' : status === 'observed' ? 'Evidence observed' : 'Evidence incomplete';

function Overview({detail, onOpenTab}: {detail: ResourceDetail; onOpenTab: (tab: string) => void}) {
  const a = detail.assessment;
  const retail = detail.costs?.retail_run_rate_usd ?? detail.costs?.retail_estimate_usd ?? a.retail_estimate_usd;
  const balance = detail.costs?.billed_vs_retail_usd;
  return <>
    {!!a.protected_reasons.length && <Notice tone="warning">Recovery or retention intent detected: {a.protected_reasons.map(label).join(', ')}.</Notice>}
    {a.observation.status !== 'recent' && <Notice tone="warning">Observation is stale. Run a new scan before you plan a change.</Notice>}
    <dl className="settings-key-values overview-snapshot">
      <div><dt>Findings</dt><dd>{detail.findings.length ? `${detail.findings.length} in this scan` : 'None'}</dd></div>
      <div><dt>Azure retail run-rate</dt><dd>{retail == null ? 'Unknown' : money(retail)}</dd></div>
      <div><dt>Billed vs retail</dt><dd>{balance == null ? 'Unknown' : money(balance)}</dd></div>
      <div><dt>Retail-modeled waste</dt><dd>{detail.costs?.retail_waste_opportunity_usd == null ? 'Unknown' : money(detail.costs.retail_waste_opportunity_usd)}</dd></div>
      <div><dt>Evidence checks</dt><dd>{a.evidence_coverage.total ? `${a.evidence_coverage.observed}/${a.evidence_coverage.total} observed` : 'Not evaluated'}</dd></div>
    </dl>
    {!!detail.action_items?.length && <div className="drawer-section"><h3>Review action items</h3><p className="inline-help">Derived from saved evidence, guardrails, and findings — not from AI.</p><Actions actions={detail.action_items} grouped/></div>}
    <div className="drawer-section overview-radar"><EvidenceRadar pillars={a.pillars} onInspect={() => onOpenTab('evidence')}/></div>
    <div className="drawer-header-actions overview-actions">
      {detail.findings.length > 0 && <button type="button" className="button secondary small" onClick={() => onOpenTab('findings')}><ListChecks size={14}/>Review findings</button>}
      <button type="button" className="button secondary small" onClick={() => onOpenTab('costs')}><CircleDollarSign size={14}/>Costs</button>
      <button type="button" className="button secondary small" onClick={() => onOpenTab('evidence')}><Activity size={14}/>Evidence & checks</button>
    </div>
  </>;
}

function AssessmentChecks({detail}: {detail: ResourceDetail}) {
  const a = detail.assessment;
  const [pillar, setPillar] = useState('');
  return <div className="drawer-section"><h3>Five-pillar checks</h3>
    <p className="inline-help">{a.evidence_coverage.observed} of {a.evidence_coverage.total} checks have observed evidence.</p>
    <div className="pillar-list">{a.pillars.map(p => <details key={p.pillar} open={pillar ? pillar === p.pillar : p.status === 'risk'}><summary><strong className="capitalize">{p.pillar}</strong><span className={`assessment-state ${p.status}`}>{pillarState(p.status)}</span></summary><div>{p.checks.map(c => <article key={c.code}><span className={`assessment-dot ${c.status}`}/><div><h4>{sentence(c.code)}</h4><p>{c.explanation}</p>{!!c.evidence_fields.length && <small className="inline-help">Evidence: {c.evidence_fields.join(', ')}</small>}</div></article>)}</div></details>)}</div>
    <details className="drawer-disclosure"><summary>Resource identity</summary><dl className="detail-metadata">
      <div><dt>Resource type</dt><dd>{a.resource_type || 'Not supplied'}</dd></div><div><dt>Service category</dt><dd>{sentence(a.service_category || 'other')}</dd></div>
      <div><dt>Group or namespace</dt><dd>{a.resource_group || 'Not supplied'}</dd></div><div><dt>Account or scope</dt><dd><code>{a.scope_id}</code></dd></div>
      <div className="full-width"><dt>Resource ID</dt><dd><code>{a.resource_id}</code></dd></div></dl></details>
    {!!a.guardrails.length && <details className="drawer-disclosure"><summary>Required guardrails</summary><ul className="assessment-guardrails">{a.guardrails.map(code => <li key={code}>{sentence(code)}</li>)}</ul></details>}
    <p className="inline-help" title={a.evidence_digest}>Policy {a.policy_version} · Evidence fingerprint {a.evidence_digest.slice(0, 16)}</p>
  </div>;
}

function Findings({detail}: {detail: ResourceDetail}) {
  if (!detail.findings.length) return <p className="inline-empty">No findings are attached to this resource in the selected scan.</p>;
  return <div className="drawer-section"><h3>Findings on this resource</h3><p className="inline-help">Each finding is reviewed separately. Open one to see its provenance, protection signals and AI advisory.</p>
    <div className="finding-review-list">{detail.findings.map((f, index) => <details key={findingKey(f)} className="finding-review" open={index === 0}>
      <summary><span><strong>{ruleLabel(f.rule_id)}</strong><small>{f.details}</small></span><span className="finding-review-cost">{f.estimated_monthly_waste_usd == null ? 'Price unknown' : `${money(f.estimated_monthly_waste_usd)}/mo`}</span></summary>
      <ArchitecturalAssessment finding={f} embedded/>
    </details>)}</div></div>;
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
  return resourceKey ? <ResourceDetailDrawer key={JSON.stringify([scanId,resourceKey,token])} scanId={scanId} resourceKey={resourceKey} onClose={onClose} onChange={onChange}/> : null;
}

function ResourceDetailDrawer({scanId,resourceKey,onClose,onChange}:{scanId:string;resourceKey:string;onClose:()=>void;onChange:()=>void}) {
  const {token, canAdmin} = useWorkspace();
  const [detail, setDetail] = useState<ResourceDetail | null>(null), [error, setError] = useState(''), [version, setVersion] = useState(0);
  useEffect(() => {
    if (!resourceKey) return;
    const request = new AbortController();
    setError('');
    api<ResourceDetail>(`/scans/${scanId}/resources/${resourceKey}`, token, {signal: request.signal}).then(result => {if (!request.signal.aborted) setDetail(result);})
      .catch(cause => {if (!request.signal.aborted) {setDetail(null); setError((cause as Error).message);}});
    return () => request.abort();
  }, [scanId, resourceKey, token, version]);
  const [tab, setTab] = useState('overview');
  useEffect(() => {setTab('overview');}, [resourceKey]);
  const changed = () => {setVersion(v => v + 1); onChange();};
  const refetch = () => setVersion(v => v + 1);
  const current = detail && detail.assessment.resource_key === resourceKey ? detail : null;
  const a = current?.assessment;
  const tabs = current ? [
    {id: 'overview', label: 'Overview', icon: LayoutDashboard},
    {id: 'findings', label: `Findings (${current.findings.length})`, icon: ListChecks},
    {id: 'evidence', label: 'Evidence', icon: Activity},
    {id: 'costs', label: 'Costs', icon: CircleDollarSign},
    {id: 'safety', label: 'Action safety', icon: ShieldAlert},
    {id: 'observability', label: current.observability?.latency_reasons.length ? 'Observability (latency-sensitive)' : 'Observability', icon: Gauge},
    {id: 'ai', label: 'AI', icon: BrainCircuit},
    {id: 'decision', label: 'Decision', icon: CheckCircle2},
    {id: 'history', label: 'History', icon: History},
    {id: 'code', label: 'Code', icon: FileCode2},
  ].map(item => ({...item, lead: resourceDrawerLeads[item.id]})) : [];
  return <Dialog open={!!resourceKey} onClose={onClose} title="Resource details" drawer>
    {error ? <div className="dialog-content"><Notice tone="error">{error}</Notice></div> : !current || !a ? <Loading label="Loading resource details…"/> : <>
      <div className="finding-drawer-header resource-drawer-header">
        <div className="finding-badges"><ProviderBadge provider={a.provider}/><span className={`state-badge ${a.disposition === 'protected' ? 'protected-intent' : 'review-required'}`}>{a.disposition === 'protected' ? 'Protected intent' : 'Review required'}</span><span className={`priority-badge priority-${a.review_priority}`}>{sentence(a.review_priority)}</span><ArmDetailBadge status={a.arm_detail}/><AIStatusBadge ai={current.ai}/>{current.decision && <span className="state-badge">{decisionLabels[current.decision.decision]}</span>}</div>
        <h2>{a.resource_name || a.resource_id}</h2>
        <p>{a.resource_type.split('/').slice(-1)[0] || 'Resource'}{a.resource_group ? ` · ${a.resource_group}` : ''} · <PillarDots pillars={Object.fromEntries(a.pillars.map(p => [p.pillar, p.status]))}/></p>
        <p className="drawer-header-meta">Observed {a.observation.observed_at ? shortDate(a.observation.observed_at) : 'Unknown'}{current.findings.length ? ` · ${current.findings.length} finding${current.findings.length === 1 ? '' : 's'}` : ''}</p>
        <div className="drawer-header-actions"><Link className="button secondary small" href={`/agents?resource=${encodeURIComponent(a.resource_id)}`}><Bot size={14}/>Draft a tag or snapshot plan</Link><button type="button" className="button secondary small" onClick={() => setTab('ai')}><BrainCircuit size={14}/>{current.ai_result ? 'View AI assessment' : 'AI assessment'}</button></div>
      </div>
      <TabWorkspaceShell id="resource-drawer" label="Resource details sections" className="drawer-tab-shell" tabs={tabs} value={tab} onChange={setTab} panelClassName="drawer-tab-content">
        {tab === 'overview' && <Overview detail={current} onOpenTab={setTab}/>}
        {tab === 'findings' && <Findings detail={current}/>}
        {tab === 'evidence' && <><AssessmentChecks detail={current}/><Evidence detail={current}/><Telemetry detail={current}/><Rules detail={current}/><Dependencies detail={current}/></>}
        {tab === 'costs' && <Costs detail={current} onFetched={refetch}/>}
        {tab === 'safety' && (
          <ActionSafetyPanel
            token={token}
            actionId={`resource:${a.resource_id}`}
            supported={current.findings.some(f => f.estimated_monthly_waste_usd != null && f.estimated_monthly_waste_usd > 0)}
            evidence={actionEvidenceFromResource(current)}
            canAdmin={canAdmin}
          />
        )}
        {tab === 'observability' && <Observability detail={current}/>}
        {tab === 'ai' && <><div className="drawer-section"><h3>AI assessment</h3><Assessment detail={current}/></div><Questions detail={current} onChange={changed}/></>}
        {tab === 'decision' && <DecisionTab detail={current} onChange={changed}/>}
        {tab === 'history' && <HistoryTab detail={current}/>}
        {tab === 'code' && <div className="drawer-section"><h3>Review code</h3><CodeReview findings={current.findings}/></div>}
      </TabWorkspaceShell>
      <div className="drawer-footer"><ShieldCheck size={15}/>AI advice is unverified and never changes cloud resources.</div>
    </>}
  </Dialog>;
}
