'use client';
import Link from 'next/link';
import {useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {
  ArrowsIn,
  ArrowsOut,
  Brain,
  ChatCircleText,
  CheckCircle,
  ClockCounterClockwise,
  CurrencyCircleDollar,
  FileCode,
  Gauge,
  Layout,
  ListChecks,
  Pulse,
  Robot,
  SealCheck,
  ShieldWarning,
} from '@phosphor-icons/react';
import {resourceDrawerLeads} from '../../lib/workspace-tab-leads';
import {api} from '../../lib/api';
import {dateTime, money, ruleLabel, shortDate, checkLabel, providerNames, ruleProvider} from '../../lib/finops';
import type {Finding} from '../../lib/types';
import {decisionLabels, label, sentence, type DecisionKind, type ResourceDetail, type ResourceHistory, type ResourceRow, type RuleConflict, type Targets} from '../../lib/resources';
import {useWorkspace} from '../WorkspaceProvider';
import {Dialog} from '../ui/dialog';
import {TabWorkspaceShell} from '../ui/TabWorkspaceShell';
import {resourceDetailQuery, type ResourceIdentity} from '../../lib/resource-insight';
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
  const a = detail.assessment;
  const reconciliation = detail.reconciliation_status || detail.observation?.reconciliation_status;
  return <div className="drawer-section"><h3>Evidence provenance</h3>
    <dl className="settings-key-values">
      <div><dt>Scan</dt><dd><code>{detail.scan_id}</code></dd></div>
      <div><dt>Collector</dt><dd>{detail.observation?.collector_version || 'Not recorded'}</dd></div>
      <div><dt>Schema</dt><dd>{detail.evidence_schema_version || detail.observation?.evidence_schema_version || 'Legacy'}</dd></div>
      <div><dt>Observed</dt><dd>{detail.observation?.observed_at ? dateTime(detail.observation.observed_at) : 'Unknown'}</dd></div>
      {a.observation?.status && <div><dt>Observation freshness</dt><dd>{sentence(a.observation.status)}{a.observation.max_age_hours ? ` · ${a.observation.max_age_hours}h window` : ''}</dd></div>}
      {reconciliation && <div><dt>Source reconciliation</dt><dd>{sentence(reconciliation)}</dd></div>}
      {!!detail.observation?.data_sources?.length && <div className="full-width"><dt>Data sources</dt><dd>{detail.observation.data_sources.map(source => `${source.source_id || source.collector_type || 'Source'} (${sentence(source.status || 'unknown')})`).join(' · ')}</dd></div>}
    </dl>
    <p className="inline-help">Configuration older than 24 hours needs a new scan. Per-check evidence is listed under Five-pillar checks above.</p>
  </div>;
}

function Configuration({detail}: {detail: ResourceDetail}) {
  const snapshot = detail.configuration_detail || detail.observation?.configuration_snapshot || {};
  const text = JSON.stringify(snapshot, null, 2);
  const readiness = detail.analysis_readiness || detail.observation?.evidence?.analysis_readiness;
  const registry = detail.type_registry || detail.observation?.evidence?.type_registry;
  const armDetail = detail.assessment.arm_detail;
  const hasSnapshot = text !== '{}';
  return <div className="drawer-section"><h3>Configuration</h3>
    <dl className="settings-key-values">
      {armDetail && <div><dt>ARM configuration detail</dt><dd><ArmDetailBadge status={armDetail}/></dd></div>}
      {readiness && <>
        <div><dt>Configuration evidence</dt><dd>{sentence(readiness.configuration || 'unknown')}{readiness.configuration_total ? ` · ${readiness.configuration_observed ?? 0}/${readiness.configuration_total}` : ''}</dd></div>
        {!!readiness.telemetry_pending_rule_ids?.length && <div><dt>Telemetry still needed</dt><dd>{readiness.telemetry_pending_rule_ids.filter(id => ruleProvider(id) === detail.assessment.provider).map(ruleLabel).join(', ') || 'None for this provider'}</dd></div>}
      </>}
      {!!registry?.evidence_fields_pending?.length && <div><dt>Registry fields pending</dt><dd>{registry.evidence_fields_pending.map(label).join(', ')}</dd></div>}
      {detail.evidence_incomplete && <div><dt>Collection status</dt><dd>Background refresh is filling remaining evidence.</dd></div>}
    </dl>
    {!hasSnapshot && !readiness && !armDetail ? <Notice>No typed configuration snapshot is attached to this observation.</Notice>
      : <details className="drawer-disclosure" open={hasSnapshot}><summary>Saved configuration{text.length > 16000 ? ' (truncated)' : ''}</summary><pre className="config-snapshot">{text.slice(0, 16000)}</pre></details>}
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
  if (!signals) return <div className="drawer-section"><h3>Observability</h3><Notice>No metrics or traces are linked. Add connectors in Settings → Integrations.</Notice><p><Link className="text-link" href="/settings?tab=integrations">Open integrations</Link></p></div>;
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

function conflictTone(severity: RuleConflict['severity']): 'error' | 'warning' | 'info' {
  return severity === 'block' ? 'error' : severity === 'review' ? 'warning' : 'info';
}

function Rules({detail}: {detail: ResourceDetail}) {
  const matches = detail.rule_matches;
  const conflicts = detail.rule_conflicts ?? [];
  const primary = matches?.primary_match;
  const evaluationGroups = detail.rule_evaluation_groups?.length
    ? detail.rule_evaluation_groups
    : detail.rule_evaluations?.length
      ? [{provider: detail.assessment.provider, label: `${providerNames[detail.assessment.provider] || detail.assessment.provider} analysis rules`, evaluations: detail.rule_evaluations}]
      : [];
  return <div className="drawer-section"><h3>Rules &amp; matching</h3>
    {conflicts.length > 0 && <div className="rule-conflict-list">{conflicts.map((conflict, index) => <Notice key={`${conflict.kind}:${conflict.rule_id ?? index}`} tone={conflictTone(conflict.severity)}>{conflict.rule_id ? <><strong>{ruleLabel(conflict.rule_id)}</strong> · </> : null}{conflict.message}</Notice>)}</div>}
    {(primary || (matches?.alternate_matches?.length ?? 0) > 0 || matches?.opportunity_group_id) && <div className="rule-match-summary">
      <p className="inline-help">When several rules fire, one primary recommendation is chosen (Turbonomic-style action market). Alternates stay visible but should not be summed with the primary.</p>
      {matches?.opportunity_group_id && <p className="inline-help">Opportunity group: <code>{matches.opportunity_group_id}</code>{matches.overlap_policy ? ` · ${label(matches.overlap_policy)}` : ''}</p>}
      {primary && <article className="drawer-card rule-match-primary"><header><h4>Primary match · {ruleLabel(primary.rule_id)}</h4><span className="assessment-state risk">{sentence(primary.match_confidence)} confidence</span></header>
        <dl className="settings-key-values compact"><div><dt>Action</dt><dd>{sentence(primary.action_class)}</dd></div><div><dt>Channel</dt><dd>{label(primary.display_channel)}</dd></div></dl>
        {(primary.safety_blocks?.length ?? 0) > 0 && <p className="inline-help">Safety: {primary.safety_blocks!.join(', ')}</p>}
        {(primary.protected_reasons?.length ?? 0) > 0 && <p className="inline-help">Protected: {primary.protected_reasons!.map(sentence).join(', ')}</p>}
      </article>}
      {(matches?.alternate_matches?.length ?? 0) > 0 && <div className="rule-alternate-list"><h4 className="rule-alternate-title">Alternate matches</h4><div className="drawer-card-list">{matches!.alternate_matches.map(alt => <article key={alt.rule_id} className="drawer-card rule-match-alternate"><header><h4>{ruleLabel(alt.rule_id)}</h4><span className="assessment-state unknown">{sentence(alt.match_confidence)}</span></header><p className="inline-help">{alt.suppressed_reason ? label(alt.suppressed_reason) : 'Lower rank in action market'}</p><small>{label(alt.display_channel)} · {sentence(alt.action_class)}</small></article>)}</div></div>}
    </div>}
    <h4 className="rule-evaluations-title">Per-rule evaluations</h4>
    {!evaluationGroups.length ? <Notice>This observation has no per-rule evaluation records. No findings doesn’t mean a rule passed.</Notice> : evaluationGroups.map(group => <section key={group.provider} className="check-group-section">
      <h4>{group.label}</h4>
      <div className="drawer-card-list">{group.evaluations.map(rule => <article key={rule.rule_id} className="drawer-card">
    <header><h4>{ruleLabel(rule.rule_id)}</h4><span className={`assessment-state ${rule.outcome === 'condition_detected' ? 'risk' : rule.outcome === 'condition_not_detected' ? 'observed' : 'unknown'}`}>{sentence(rule.outcome)}</span></header><p>{rule.reason}</p><small>{rule.rule_version ? `Version ${rule.rule_version}` : 'Current policy'}{rule.destructive_actions_blocked ? ' · Destructive actions blocked' : ''}{rule.safety_blocks?.length ? ` · Safety: ${rule.safety_blocks.join(', ')}` : ''}</small></article>)}</div>
    </section>)}</div>;
}

function governanceCollectionLabel(status: string | null | undefined): string {
  if (status === 'collected') return 'Collected from Azure';
  if (status === 'unavailable_or_incomplete') return 'Could not be loaded';
  return 'Not collected yet';
}

function AzureGovernancePanel({detail}: {detail: ResourceDetail}) {
  const gov = detail.azure_governance;
  const policies = gov?.policy_states ?? [];
  const advisor = gov?.advisor_recommendations ?? [];
  return <>
    <div className="drawer-section"><h3>Azure Policy</h3>
      <p className="inline-help">{governanceCollectionLabel(gov?.collection?.azure_policy)} · Assignment compliance for this resource ID. This is separate from CloudSaver analysis rules.</p>
      {!policies.length ? <Notice>{gov?.collection?.azure_policy === 'unavailable_or_incomplete' ? 'Azure Policy could not be read. Verify Policy Insights Reader on the subscription.' : 'No policy states were returned for this resource.'}</Notice>
        : <div className="summary-table-scroll" tabIndex={0} aria-label="Azure Policy states"><table className="summary-table"><thead><tr><th>Assignment</th><th>Definition</th><th>Compliance</th></tr></thead><tbody>{policies.map((row, index) => <tr key={`${row.policy_assignment_id || row.policy_definition_id || index}`}><td>{row.policy_assignment_name || 'Unknown assignment'}{row.policy_set_definition_name ? <small> · {row.policy_set_definition_name}</small> : null}</td><td>{row.policy_definition_name || row.policy_definition_id || 'Unknown definition'}</td><td>{sentence(row.compliance_state || 'unknown')}</td></tr>)}</tbody></table></div>}
    </div>
    <div className="drawer-section"><h3>Azure Advisor</h3>
      <p className="inline-help">{governanceCollectionLabel(gov?.collection?.advisor)} · Active recommendations scoped to this resource.</p>
      {!advisor.length ? <Notice>{gov?.collection?.advisor === 'unavailable_or_incomplete' ? 'Advisor recommendations could not be loaded. Verify Reader access on Advisor.' : 'Advisor returned no recommendations for this resource.'}</Notice>
        : <div className="drawer-card-list">{advisor.map(row => <article key={row.recommendation_id || `${row.category}:${row.problem}`} className="drawer-card"><header><h4>{row.problem || row.category || 'Recommendation'}</h4><span className="assessment-state unknown">{sentence(row.impact || row.risk || 'unknown impact')}</span></header>{row.solution ? <p>{row.solution}</p> : null}{row.last_updated ? <small>Updated {dateTime(row.last_updated)}</small> : null}</article>)}</div>}
    </div>
  </>;
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
  const supplemental = [
    ['modeled_future_cost_usd', 'Modeled future cost', 'USD'],
    ['opportunity_usd', 'Retail opportunity total', 'USD'],
    ['verified_realized_savings_usd', 'Verified realized savings', 'USD'],
  ] as const;
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
        persist: 'true',
      });
      const snapshot = await api<AzureCostSnapshot>(`/finops/azure-resource-costs?${qs}`, token);
      setAzureEvidence(snapshot);
      onFetched();
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
        <button type="button" className="button primary" disabled={busy} onClick={fetchAzureCosts}>{busy ? 'Calling Azure…' : 'Fetch billed costs from Azure'}</button>
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

function pillarSummaryCounts(pillars: ResourceDetail['assessment']['pillars']) {
  let risk = 0;
  let observed = 0;
  let unknown = 0;
  for (const p of pillars) {
    if (p.status === 'risk') risk++;
    else if (p.status === 'observed') observed++;
    else unknown++;
  }
  return {risk, observed, unknown, total: pillars.length};
}

function Overview({detail, onOpenTab}: {detail: ResourceDetail; onOpenTab: (tab: string) => void}) {
  const a = detail.assessment;
  const retail = detail.costs?.retail_run_rate_usd ?? detail.costs?.retail_estimate_usd ?? a.retail_estimate_usd;
  const balance = detail.costs?.billed_vs_retail_usd;
  const hasBilled = detail.costs?.billed_cost_usd != null || a.billed_cost_usd != null;
  const retailLabel = retail == null ? 'Not estimated' : money(retail);
  const balanceLabel = balance != null ? money(balance) : hasBilled ? 'Unknown' : 'Billed not imported';
  const waste = detail.costs?.retail_waste_opportunity_usd;
  const pc = pillarSummaryCounts(a.pillars);
  const freshnessStale = a.observation?.status !== 'recent' || !!detail.analysis_stale;
  const healthTitle =
    pc.risk > 0
      ? 'Risk signals on this resource'
      : pc.total > 0 && pc.observed === pc.total
        ? 'Pillar evidence complete'
        : pc.total > 0
          ? 'Evidence still filling in'
          : 'Assessment overview';
  const nextSteps = useMemo(() => {
    const steps: {key: string; title: string; detail: string; action: ReactNode}[] = [];
    if (freshnessStale) {
      steps.push({
        key: 'refresh',
        title: 'Refresh evidence',
        detail: detail.analysis_stale ? 'Analysis is marked stale for this resource.' : 'Observation is outside the freshness window your policy expects.',
        action: (
          <span className="resource-overview-step-hint">
            Inventory refreshes on your workspace schedule.{' '}
            <Link className="text-link" href="/resources">Open Resources</Link> to confirm the latest snapshot.
          </span>
        ),
      });
    }
    if (a.protected_reasons.length) {
      steps.push({
        key: 'protected',
        title: 'Confirm protection intent',
        detail: `Recovery or retention: ${a.protected_reasons.map(label).join(', ')}`,
        action: (
          <button type="button" className="text-link" onClick={() => onOpenTab('safety')}>
            Open Action safety
          </button>
        ),
      });
    }
    if (detail.findings.length) {
      steps.push({
        key: 'findings',
        title: 'Review findings',
        detail: `${detail.findings.length} finding${detail.findings.length === 1 ? '' : 's'} in this scan`,
        action: (
          <button type="button" className="text-link" onClick={() => onOpenTab('findings')}>
            Open Findings
          </button>
        ),
      });
    }
    if (pc.risk > 0) {
      steps.push({
        key: 'pillars',
        title: 'Inspect pillar checks',
        detail: `${pc.risk} pillar${pc.risk === 1 ? '' : 's'} with risk observed`,
        action: (
          <button type="button" className="text-link" onClick={() => onOpenTab('evidence')}>
            Open Evidence
          </button>
        ),
      });
    }
    if (detail.ai.status === 'stale' || detail.ai.status === 'failed') {
      steps.push({
        key: 'ai',
        title: 'Reconcile AI assessment',
        detail: detail.ai.status === 'stale' ? 'Evidence changed after the last model run.' : 'The last AI run did not complete.',
        action: (
          <button type="button" className="text-link" onClick={() => onOpenTab('ai')}>
            Open AI
          </button>
        ),
      });
    }
    if (retail == null && !hasBilled) {
      steps.push({
        key: 'costs',
        title: 'Attach billing context',
        detail: 'Retail and billed amounts prioritize FinOps work.',
        action: (
          <button type="button" className="text-link" onClick={() => onOpenTab('costs')}>
            Open Costs
          </button>
        ),
      });
    }
    return steps.slice(0, 5);
  }, [a.protected_reasons, detail.ai.status, detail.analysis_stale, detail.findings.length, freshnessStale, hasBilled, onOpenTab, pc.risk, retail]);
  return <>
    {!!a.protected_reasons.length && <Notice tone="warning">Recovery or retention intent detected: {a.protected_reasons.map(label).join(', ')}.</Notice>}
    {a.observation?.status !== 'recent' && <Notice tone="warning">Observation is outside the expected freshness window. Confirm the latest inventory snapshot before you plan an infrastructure change.</Notice>}
    <div className="resource-overview-hero">
      <div className="resource-overview-hero-main">
        <span className="eyebrow">Resource health</span>
        <h3 className="resource-overview-hero-title">{healthTitle}</h3>
        <p className="resource-overview-hero-lead">
          {pc.total ? (
            <>
              {pc.observed} of {pc.total} pillars with complete evidence
              {pc.risk > 0 ? ` · ${pc.risk} with risk` : ''}
              {pc.unknown > 0 ? ` · ${pc.unknown} incomplete` : ''}
            </>
          ) : (
            'Pillar coverage will appear when this resource type is evaluated.'
          )}
          {a.evidence_coverage.total ? (
            <> · {a.evidence_coverage.observed}/{a.evidence_coverage.total} checks observed</>
          ) : (
            <> · checks not evaluated</>
          )}
        </p>
        <div className="resource-overview-pillar-strip" role="list" aria-label="Five-pillar status">
          {a.pillars.map(p => (
            <span key={p.pillar} role="listitem" className={`resource-overview-pillar-chip resource-overview-pillar-chip--${p.status}`}>
              <span className="capitalize">{p.pillar}</span>
              <small>{pillarState(p.status)}</small>
            </span>
          ))}
        </div>
      </div>
      <dl className="drawer-facts resource-overview-facts">
        <div><dt>Findings</dt><dd>{detail.findings.length ? `${detail.findings.length} in this scan` : 'None'}</dd></div>
        <div><dt>Retail run-rate</dt><dd>{retailLabel}</dd></div>
        <div><dt>Billed vs retail</dt><dd title={balanceLabel}>{balanceLabel}</dd></div>
        <div><dt>Last analyzed</dt><dd>{detail.refresh_in_progress ? 'Refreshing from Azure…' : detail.last_analyzed_at ? dateTime(detail.last_analyzed_at) : 'Not yet analyzed'}{!detail.refresh_in_progress && detail.analysis_stale ? ' · stale' : ''}</dd></div>
      </dl>
    </div>
    {nextSteps.length > 0 && (
      <div className="resource-overview-next" aria-label="Suggested next steps">
        <h3 className="resource-overview-next-title">Next steps</h3>
        <ul className="resource-overview-next-list">
          {nextSteps.map(step => (
            <li key={step.key}>
              <div className="resource-overview-step-copy">
                <strong>{step.title}</strong>
                <p>{step.detail}</p>
              </div>
              <div className="resource-overview-step-action">{step.action}</div>
            </li>
          ))}
        </ul>
      </div>
    )}
    <details className="drawer-disclosure resource-overview-snapshot">
      <summary>Full cost &amp; telemetry snapshot</summary>
      <dl className="settings-key-values overview-snapshot">
        <div><dt>Findings</dt><dd>{detail.findings.length ? `${detail.findings.length} in this scan` : 'None'}</dd></div>
        {a.region ? <div><dt>Region</dt><dd>{a.region}</dd></div> : null}
        <div><dt>Azure retail run-rate</dt><dd>{retailLabel}</dd></div>
        <div><dt>Billed vs retail</dt><dd>{balanceLabel}</dd></div>
        <div><dt>Retail-modeled waste</dt><dd>{waste == null ? (retail == null ? 'Not estimated' : 'None modeled') : money(waste)}</dd></div>
        <div><dt>Evidence checks</dt><dd>{a.evidence_coverage.total ? `${a.evidence_coverage.observed}/${a.evidence_coverage.total} observed` : 'Not evaluated'}</dd></div>
        <div><dt>Last analyzed</dt><dd>{detail.refresh_in_progress ? 'Refreshing from Azure…' : detail.last_analyzed_at ? dateTime(detail.last_analyzed_at) : 'Not yet analyzed'}{!detail.refresh_in_progress && detail.analysis_stale ? ' · stale' : ''}</dd></div>
        <div><dt>Azure status fetched</dt><dd>{detail.azure_status_fetched_at ? dateTime(detail.azure_status_fetched_at) : 'Not fetched'}</dd></div>
      </dl>
    </details>
    {retail == null && !hasBilled && (
      <p className="inline-help overview-cost-hint">Retail and billed amounts come from Azure Cost Management and billing sync. Open the <button type="button" className="text-link" onClick={() => onOpenTab('costs')}>Costs</button> tab to fetch live Azure charges for this resource.</p>
    )}
    {!!detail.action_items?.length && <div className="drawer-section"><h3>Review action items</h3><p className="inline-help">Derived from saved evidence, guardrails, and findings — not from AI.</p><Actions actions={detail.action_items} grouped/></div>}
    <div className="drawer-section overview-radar"><EvidenceRadar pillars={a.pillars} onInspect={() => onOpenTab('evidence')}/></div>
    <div className="drawer-header-actions overview-actions">
      {detail.findings.length > 0 && <button type="button" className="button secondary small" onClick={() => onOpenTab('findings')}><ListChecks size={14} weight="regular"/>Review findings</button>}
      <button type="button" className="button secondary small" onClick={() => onOpenTab('costs')}><CurrencyCircleDollar size={14} weight="regular"/>Costs</button>
      <button type="button" className="button secondary small" onClick={() => onOpenTab('evidence')}><Pulse size={14} weight="regular"/>Evidence & checks</button>
    </div>
  </>;
}

function checksByPillar(checks: ResourceDetail['assessment']['pillars'][number]['checks']) {
  const pillars = new Map<string, typeof checks>();
  for (const check of checks) {
    const bucket = pillars.get(check.pillar) || [];
    bucket.push(check);
    pillars.set(check.pillar, bucket);
  }
  return [...pillars.entries()].map(([pillar, items]) => ({pillar, items}));
}

function AssessmentChecks({detail}: {detail: ResourceDetail}) {
  const a = detail.assessment;
  const [pillar, setPillar] = useState('');
  const groups = a.check_groups?.length ? a.check_groups : [{scope: 'shared' as const, provider: '*', label: 'Evidence checks', checks: a.pillars.flatMap(p => p.checks)}];
  return <div className="drawer-section"><h3>Evidence checks by cloud</h3>
    <p className="inline-help">{a.evidence_coverage.observed} of {a.evidence_coverage.total} checks apply to this resource{a.evidence_scope?.family_label ? ` (${a.evidence_scope.family_label})` : ''}. Only controls relevant to {a.resource_type || 'this type'} are evaluated.</p>
    {groups.map(group => <section key={`${group.scope}:${group.provider}`} className="check-group-section">
      <h4>{group.label}</h4>
      <div className="pillar-list">{checksByPillar(group.checks).map(p => <details key={`${group.provider}:${p.pillar}`} open={pillar ? pillar === `${group.provider}:${p.pillar}` : p.items.some(c => c.status === 'risk')} onToggle={event => {if ((event.target as HTMLDetailsElement).open) setPillar(`${group.provider}:${p.pillar}`);}}><summary><strong className="capitalize">{p.pillar}</strong><span className={`assessment-state ${p.items.some(c => c.status === 'risk') ? 'risk' : p.items.every(c => c.status === 'observed') ? 'observed' : 'unknown'}`}>{pillarState(p.items.some(c => c.status === 'risk') ? 'risk' : p.items.every(c => c.status === 'observed') ? 'observed' : 'unknown')}</span></summary><div>{p.items.map(c => <article key={c.code}><span className={`assessment-dot ${c.status}`}/><div><h4>{checkLabel(c.code)}</h4><p>{c.explanation}</p>{c.evidence_json ? <pre className="evidence-json">{JSON.stringify(c.evidence_json, null, 2)}</pre> : null}</div></article>)}</div></details>)}</div>
    </section>)}
    <details className="drawer-disclosure"><summary>Resource identity</summary><dl className="detail-metadata">
      <div><dt>Resource type</dt><dd>{a.resource_type || 'Not supplied'}</dd></div><div><dt>Service category</dt><dd>{sentence(a.service_category || 'other')}</dd></div>
      {a.region ? <div><dt>Region</dt><dd>{a.region}</dd></div> : null}
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
      <button className="button primary" type="submit" disabled={busy || !ack || question.trim().length < 3}><ChatCircleText size={16} weight="regular"/>{busy ? 'Asking…' : 'Ask question'}</button>
    </form>}
  </>;
}

function HistoryTab({detail}: {detail: ResourceDetail}) {
  const {token} = useWorkspace();
  const [data, setData] = useState<ResourceHistory | null>(null), [error, setError] = useState(''), [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setData(null);
    setError('');
    const request = new AbortController();
    api<ResourceHistory>(`/resources/${detail.assessment.resource_key}/history`, token, {signal: request.signal}).then(setData).catch(cause => {if (!request.signal.aborted) setError((cause as Error).message);});
    return () => request.abort();
  }, [detail.assessment.resource_key, token, attempt]);
  if (error) {
    const retryable = /gateway could not be reached|could not be reached/i.test(error);
    return (
      <div className="drawer-section">
        <Notice tone="error">{error}</Notice>
        {retryable && <button type="button" className="button secondary small" onClick={() => setAttempt(v => v + 1)}>Retry</button>}
      </div>
    );
  }
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
      <button className="button primary" type="submit" disabled={busy || (noteRequired && !note.trim())}><CheckCircle size={16} weight="regular"/>{busy ? 'Saving…' : 'Save decision'}</button>
    </form> : <p className="inline-help">A workspace administrator can record decisions.</p>}
  </>;
}

export function ResourceDrawer({scanId, resourceKey, identity, previewRow = null, relatedFindings = [], onClose, onChange}: {
  scanId: string;
  resourceKey: string | null;
  identity?: ResourceIdentity | null;
  previewRow?: ResourceRow | null;
  relatedFindings?: Finding[];
  onClose: () => void;
  onChange: () => void;
}) {
  return resourceKey ? (
    <ResourceInsightView
      key={`${scanId}:${resourceKey}`}
      scanId={scanId}
      resourceKey={resourceKey}
      identity={identity}
      previewRow={previewRow}
      relatedFindings={relatedFindings}
      layout="drawer"
      onClose={onClose}
      onChange={onChange}
    />
  ) : null;
}

function fetchStagesPending(stages: ResourceDetail['fetch_stages'] | undefined): boolean {
  if (!stages) return false;
  return Object.values(stages).some(s => s === 'pending' || s === 'running');
}

function FetchStagesNotice({stages}: {stages: ResourceDetail['fetch_stages']}) {
  if (!stages || !fetchStagesPending(stages)) return null;
  const labels: Record<string, string> = {
    costs: 'Billed costs',
    activity_log: 'Activity log',
    retail: 'Retail meters',
    analysis: 'Analysis',
    recommendations: 'Recommendations',
  };
  const pending = Object.entries(stages).filter(([, s]) => s === 'pending' || s === 'running').map(([k]) => labels[k] || k);
  if (!pending.length) return null;
  return <Notice tone="info">Still loading for this resource: {pending.join(', ')}. Sections update as each stage completes.</Notice>;
}

export function ResourceInsightView({scanId, resourceKey, identity, previewRow = null, relatedFindings = [], layout, onClose, onChange}: {
  scanId: string;
  resourceKey: string;
  identity?: ResourceIdentity | null;
  previewRow?: ResourceRow | null;
  relatedFindings?: Finding[];
  layout: 'drawer' | 'page';
  onClose: () => void;
  onChange: () => void;
}) {
  const {token, canAdmin} = useWorkspace();
  const [detail, setDetail] = useState<ResourceDetail | null>(null), [error, setError] = useState(''), [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    setDetail(null);
    setError('');
    setLoading(true);
  }, [resourceKey]);
  useEffect(() => {
    const request = new AbortController();
    setError('');
    setLoading(true);
    const query = resourceDetailQuery(identity);
    api<ResourceDetail>(`/scans/${scanId}/resources/${encodeURIComponent(resourceKey)}${query}`, token, {signal: request.signal})
      .then(result => {
        if (request.signal.aborted || result.assessment.resource_key !== resourceKey) return;
        setDetail(result);
        setError('');
      })
      .catch(cause => {
        if (!request.signal.aborted) setError((cause as Error).message);
      })
      .finally(() => {
        if (!request.signal.aborted) setLoading(false);
      });
    return () => request.abort();
  }, [scanId, resourceKey, token, version, identity?.provider, identity?.resourceId]);
  useEffect(() => {
    if (!fetchStagesPending(detail?.fetch_stages)) return;
    const timer = window.setInterval(() => setVersion(v => v + 1), 4000);
    return () => window.clearInterval(timer);
  }, [detail?.fetch_stages]);
  const [tab, setTab] = useState('overview');
  const [drawerExpanded, setDrawerExpanded] = useState(false);
  useEffect(() => {setTab('overview'); setDrawerExpanded(false);}, [resourceKey]);
  const changed = () => {setVersion(v => v + 1); onChange();};
  const refetch = () => setVersion(v => v + 1);
  const current = detail?.assessment.resource_key === resourceKey ? detail : null;
  const view = current && !current.findings.length && relatedFindings.length
    ? {...current, findings: relatedFindings}
    : current;
  const preview = !view && previewRow?.resource_key === resourceKey ? previewRow : null;
  const showAzureGovernance = (view?.assessment.provider ?? preview?.provider) === 'azure';
  const drawerTabIds: readonly string[] = ['overview', 'findings', 'evidence', ...(showAzureGovernance ? ['azure'] : []), 'costs', 'safety', 'observability', 'ai', 'decision', 'history', 'code'];
  useEffect(() => {
    if (view && !drawerTabIds.includes(tab)) setTab('overview');
  }, [view, tab, showAzureGovernance]);
  const tabs = (view || preview) ? [
    {id: 'overview', label: 'Overview', icon: Layout},
    {id: 'findings', label: `Findings (${(view?.findings.length ?? preview?.finding_count ?? 0)})`, icon: ListChecks},
    {id: 'evidence', label: 'Evidence', icon: Pulse},
    ...(showAzureGovernance ? [{id: 'azure', label: 'Azure Policy & Advisor', icon: SealCheck}] : []),
    {id: 'costs', label: 'Costs', icon: CurrencyCircleDollar},
    {id: 'safety', label: 'Action safety', icon: ShieldWarning},
    {id: 'observability', label: 'Observability', icon: Gauge},
    {id: 'ai', label: 'AI', icon: Brain},
    {id: 'decision', label: 'Decision', icon: CheckCircle},
    {id: 'history', label: 'History', icon: ClockCounterClockwise},
    {id: 'code', label: 'Code', icon: FileCode},
  ].map(item => ({...item, lead: resourceDrawerLeads[item.id]})) : [];
  const body = error && !view && !preview ? (
    <div className={layout === 'page' ? 'resource-insight-shell panel' : 'dialog-content'}><Notice tone="error">{error}</Notice></div>
  ) : !view && !preview ? (
    <div className={layout === 'page' ? 'resource-insight-shell panel' : 'dialog-content'}>
      {identity?.resourceId && <p className="inline-help"><code>{identity.resourceId}</code></p>}
      <Loading label={loading ? 'Loading resource details…' : 'Waiting for resource evidence…'}/>
      {error && <Notice tone="error">{error}</Notice>}
    </div>
  ) : !view && preview ? (
    <>
      <div className={`finding-drawer-header resource-drawer-header${layout === 'page' ? ' resource-insight-header' : ''}`}>
        <div className="finding-badges"><ProviderBadge provider={preview.provider}/><span className={`state-badge ${preview.disposition === 'protected' ? 'protected-intent' : 'review-required'}`}>{preview.disposition === 'protected' ? 'Protected' : 'Review'}</span><span className={`priority-badge priority-${preview.review_priority}`}>{sentence(preview.review_priority)}</span><ArmDetailBadge status={preview.arm_detail}/><AIStatusBadge ai={preview.ai}/>{preview.decision && <span className="state-badge">{decisionLabels[preview.decision.decision]}</span>}</div>
        <h2>{preview.resource_name || preview.resource_id}</h2>
        <p>{preview.resource_type.split('/').slice(-1)[0] || 'Resource'}{preview.resource_group ? ` · ${preview.resource_group}` : ''} · <PillarDots pillars={preview.pillars}/></p>
        <p className="drawer-header-meta">Loading full evidence for this resource…</p>
      </div>
      <TabWorkspaceShell id={layout === 'page' ? 'resource-insight' : 'resource-drawer'} label="Resource details sections" className="drawer-tab-shell" tabs={tabs} value={tab} onChange={setTab} panelClassName="drawer-tab-content" tabIcons={false}>
        <Loading label="Loading resource details…"/>
      </TabWorkspaceShell>
      <div className="drawer-footer"><SealCheck size={15} weight="regular"/>AI advice is unverified and never changes cloud resources.</div>
    </>
  ) : view ? (
    (() => {
      const a = view.assessment;
      return <>
      <FetchStagesNotice stages={view.fetch_stages}/>
      <div className={`finding-drawer-header resource-drawer-header${layout === 'page' ? ' resource-insight-header' : ''}`}>
        <div className="finding-badges"><ProviderBadge provider={a.provider}/><span className={`state-badge ${a.disposition === 'protected' ? 'protected-intent' : 'review-required'}`}>{a.disposition === 'protected' ? 'Protected' : 'Review'}</span><span className={`priority-badge priority-${a.review_priority}`}>{sentence(a.review_priority)}</span><ArmDetailBadge status={a.arm_detail}/><AIStatusBadge ai={view.ai}/>{view.decision && <span className="state-badge">{decisionLabels[view.decision.decision]}</span>}</div>
        <h2>{a.resource_name || a.resource_id}</h2>
        <p>{a.resource_type.split('/').slice(-1)[0] || 'Resource'}{a.resource_group ? ` · ${a.resource_group}` : ''} · <PillarDots pillars={Object.fromEntries(a.pillars.map(p => [p.pillar, p.status]))}/></p>
        <p className="drawer-header-meta">Observed {a.observation?.observed_at ? shortDate(a.observation.observed_at) : 'Unknown'}{view.findings.length ? ` · ${view.findings.length} finding${view.findings.length === 1 ? '' : 's'}` : ''}</p>
        <div className="drawer-header-actions">
          <Link className="button secondary small" href={`/agents?resource=${encodeURIComponent(a.resource_id)}`}><Robot size={14} weight="regular"/>Draft agent plan</Link>
          <button type="button" className="button secondary small" onClick={() => setTab('ai')}><Brain size={14} weight="regular"/>{view.ai_result ? 'View AI assessment' : 'AI assessment'}</button>
        </div>
      </div>
      <TabWorkspaceShell id={layout === 'page' ? 'resource-insight' : 'resource-drawer'} label="Resource details sections" className="drawer-tab-shell" tabs={tabs} value={tab} onChange={setTab} panelClassName="drawer-tab-content" tabIcons={false}>
        {tab === 'overview' && <Overview detail={view} onOpenTab={setTab}/>}
        {tab === 'findings' && <Findings detail={view}/>}
        {tab === 'evidence' && <><AssessmentChecks detail={view}/><Evidence detail={view}/><Configuration detail={view}/><Telemetry detail={view}/><Rules detail={view}/><Dependencies detail={view}/></>}
        {tab === 'azure' && showAzureGovernance && <AzureGovernancePanel detail={view}/>}
        {tab === 'costs' && <Costs detail={view} onFetched={refetch}/>}
        {tab === 'safety' && (
          <ActionSafetyPanel
            token={token}
            actionId={`resource:${a.resource_id}`}
            supported={view.findings.some(f => f.estimated_monthly_waste_usd != null && f.estimated_monthly_waste_usd > 0)}
            evidence={actionEvidenceFromResource(view)}
            canAdmin={canAdmin}
          />
        )}
        {tab === 'observability' && <Observability detail={view}/>}
        {tab === 'ai' && <><div className="drawer-section"><h3>AI assessment</h3><Assessment detail={view}/></div><Questions detail={view} onChange={changed}/></>}
        {tab === 'decision' && <DecisionTab detail={view} onChange={changed}/>}
        {tab === 'history' && <HistoryTab detail={view}/>}
        {tab === 'code' && <div className="drawer-section"><h3>Review code</h3>{view.findings.length ? <CodeReview findings={view.findings}/> : <Notice tone="info">No findings are attached to this resource in this scan. Remediation code requires a flagged finding with a supported rule.</Notice>}</div>}
      </TabWorkspaceShell>
      <div className="drawer-footer"><SealCheck size={15} weight="regular"/>AI advice is unverified and never changes cloud resources.</div>
    </>;
    })()
  ) : null;
  if (layout === 'page') {
    return <div className="resource-insight-shell panel">{body}</div>;
  }
  return (
    <Dialog
      open={!!resourceKey}
      onClose={onClose}
      title="Resource details"
      drawer
      className={drawerExpanded ? 'drawer-expanded' : ''}
      headerExtra={
        <button type="button" className="icon-button" aria-label={drawerExpanded ? 'Collapse drawer' : 'Expand drawer'} aria-pressed={drawerExpanded} onClick={() => setDrawerExpanded(v => !v)}>
          {drawerExpanded ? <ArrowsIn size={18} weight="regular"/> : <ArrowsOut size={18} weight="regular"/>}
        </button>
      }
    >
      {body}
    </Dialog>
  );
}
