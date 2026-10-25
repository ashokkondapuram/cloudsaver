'use client';
import Link from 'next/link';
import {useCallback, useDeferredValue, useEffect, useMemo, useRef, useState} from 'react';
import {useRouter, useSearchParams} from 'next/navigation';
import {BrainCircuit, ChevronRight, Download, FileCode2, Filter, Loader2, Printer, Search, Server, ShieldCheck, X} from 'lucide-react';
import {categories, categoryOf, knownPrice, protectionSignals, type Category, type Intent, type Pricing} from '../../lib/resource-insights';
import {identityOf} from '../../lib/resources';
import type {Finding} from '../../lib/types';
import {api} from '../../lib/api';
import {dateTime, downloadFile, money, providerNames} from '../../lib/finops';
import {ACTIVE_BATCH, aiStatusLabels, decisionLabels, sentence, useActiveBatch, useResources, type Batch, type ResourceRow, type Targets} from '../../lib/resources';
import {useWorkspace} from '../WorkspaceProvider';
import {Dialog} from '../ui/dialog';
import {EmptyState, Loading, Notice, ProviderBadge} from '../ui/shared';
import {AIRisk, AIStatusBadge, DecisionBadge, PillarDots} from './ResourceParts';
import {ResourceDrawer} from './ResourceDrawer';
import {AIProcessingDisclosure} from './AIProcessingDisclosure';

type Filters = {service_category:string;pillar_status:string;provider: string; review_priority: string; ai_status: string; ai_risk: string; decision: string};
const empty: Filters = {service_category:'',pillar_status:'',provider: '', review_priority: '', ai_status: '', ai_risk: '', decision: ''};
const priorityRank: Record<string, number> = {critical: 0, high: 1, evidence_required: 2};

function matches(row: ResourceRow, filters: Filters, query: string) {
  const needle = query.trim().toLowerCase();
  return (!filters.service_category||row.service_category===filters.service_category)&&(!filters.pillar_status||Object.values(row.pillars).includes(filters.pillar_status as 'observed'|'risk'|'unknown'))&&(!filters.provider || row.provider === filters.provider) && (!filters.review_priority || row.review_priority === filters.review_priority)
    && (!filters.ai_status || row.ai.status === filters.ai_status) && (!filters.ai_risk || (row.ai.risk_level || 'none') === filters.ai_risk)
    && (!filters.decision || (row.decision?.decision || 'none') === filters.decision)
    && (!needle || `${row.resource_name} ${row.resource_id}`.toLowerCase().includes(needle));
}

function BatchDialog({open, onClose, scanId, selected, total, onCreated}: {open: boolean; onClose: () => void; scanId: string; selected: ResourceRow[]; total: number; onCreated: (batch: Batch) => void}) {
  const {token} = useWorkspace();
  const [targets, setTargets] = useState<Targets | null>(null), [target, setTarget] = useState(''), [scope, setScope] = useState<'selected' | 'all'>('selected');
  const [ack, setAck] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const attempt = useRef<string | null>(null);
  useEffect(() => {
    if (!open) return;
    setAck(false); setError(''); setScope(selected.length ? 'selected' : 'all'); attempt.current = null;
    const request = new AbortController();
    api<Targets>('/ai/targets', token, {signal: request.signal}).then(t => {setTargets(t); setTarget(t.targets[0]?.target_id || '');}).catch(() => setTargets({enabled: false, hourly_attempt_limit: 0, targets: []}));
    return () => request.abort();
  }, [open, token, selected.length]);
  const count = scope === 'selected' ? selected.length : total;
  const limit = targets?.hourly_attempt_limit || 0;
  async function submit() {
    if (busy || !ack || !target || !count) return;
    attempt.current ||= crypto.randomUUID();
    setBusy(true); setError('');
    try {
      const batch = await api<Batch>(`/scans/${scanId}/ai-batches`, token, {body: {target_id: target, idempotency_key: attempt.current, acknowledge_external_processing: true,
        ...(scope === 'selected' ? {resource_keys: selected.map(r => r.resource_key)} : {all: true})}});
      onCreated(batch);
    } catch (cause) {setError((cause as Error).message);} finally {setBusy(false);}
  }
  return <Dialog open={open} onClose={onClose} title="Run AI assessment">
    <div className="dialog-content">
      {!targets ? <Loading label="Loading approved AI targets…"/> : !targets.enabled || !targets.targets.length ? <Notice tone="warning">No approved AI target is enabled for this workspace. Ask your platform operator to configure an AI target (Azure AI Foundry, Amazon Bedrock, or Google Vertex AI).</Notice> : <>
        <p>The model reviews each resource’s merged five-pillar evidence and suggests next steps. It runs in the background, one resource at a time.</p>
        <div className="segmented-control" role="radiogroup" aria-label="Resources to assess">
          <button type="button" role="radio" aria-checked={scope === 'selected'} aria-pressed={scope === 'selected'} disabled={!selected.length} onClick={() => setScope('selected')}>Selected ({selected.length.toLocaleString()})</button>
          <button type="button" role="radio" aria-checked={scope === 'all'} aria-pressed={scope === 'all'} onClick={() => setScope('all')}>All in this scan ({total.toLocaleString()})</button>
        </div>
        {count > 500 && <Notice tone="warning">A batch can include up to 500 resources. Select fewer resources to continue.</Notice>}
        <label className="ai-target-label">Approved model target<select value={target} disabled={busy} onChange={e => setTarget(e.target.value)}>{targets.targets.map(t => <option key={t.target_id} value={t.target_id}>{t.target_id} · {t.provider} · {t.model}</option>)}</select></label>
        <AIProcessingDisclosure targets={targets} targetId={target}/>
        <p className="inline-help">Your workspace can run {limit} AI attempts per hour. {count > limit ? `This batch will take about ${Math.ceil(count / limit)} hours and resumes automatically each hour.` : 'This batch should finish within the hour.'} Resources whose evidence changes before they’re assessed are skipped.</p>
        <p className="inline-help">Only sanitized facts are sent: check codes, statuses and allowlisted settings. Resource names, IDs, raw tags and free text stay in CloudSaver. Inference can incur provider charges.</p>
        <label className="checkbox-row ai-ack"><input type="checkbox" checked={ack} disabled={busy} onChange={e => setAck(e.target.checked)}/>I acknowledge external processing of this sanitized evidence.</label>
        {error && <Notice tone="error">{error}</Notice>}
        <div className="dialog-actions"><button className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={busy || !ack || !target || !count || count > 500} onClick={submit}>{busy ? <Loader2 size={16} className="spin"/> : <BrainCircuit size={16}/>}Start assessment</button></div>
      </>}
    </div>
  </Dialog>;
}

function BatchBanner({batch, onCancel, canAdmin}: {batch: Batch; onCancel: () => void; canAdmin: boolean}) {
  const done = batch.counts.completed + batch.counts.failed + batch.counts.skipped + batch.counts.uncertain + batch.counts.cancelled;
  const active = ACTIVE_BATCH.includes(batch.status);
  const percent = Math.round(100 * done / Math.max(1, batch.total));
  const extra = [batch.counts.failed && `${batch.counts.failed} failed`, batch.counts.skipped && `${batch.counts.skipped} skipped`, batch.counts.uncertain && `${batch.counts.uncertain} uncertain`].filter(Boolean).join(' · ');
  return <div className={`batch-banner batch-${batch.status}`} role="status">
    <BrainCircuit size={18}/>
    <div><strong>{batch.status === 'waiting_for_budget' ? 'AI assessment paused until the hourly limit resets' : active ? 'AI assessment in progress' : batch.status === 'cancelled' ? 'AI assessment cancelled' : 'AI assessment completed'}</strong>
      <span>{batch.counts.completed.toLocaleString()} of {batch.total.toLocaleString()} assessed{extra ? ` · ${extra}` : ''}{batch.status === 'waiting_for_budget' && batch.resume_after ? ` · resumes ${dateTime(batch.resume_after)}` : ''}</span>
      <div className="batch-progress" aria-hidden="true"><span style={{width: `${percent}%`}}/></div></div>
    {active && canAdmin && <button className="button secondary small" onClick={onCancel}><X size={14}/>Cancel</button>}
  </div>;
}

function matchesDiscovery(row: ResourceRow, scanFindings: Finding[], category: Category|'', intent: Intent, pricing: Pricing) {
  const related = scanFindings.filter(f => identityOf(row.provider, row.resource_id) === identityOf(f.cloud_provider || 'azure', f.resource_id));
  if (!category && !intent && !pricing) return true;
  if (!related.length) return false;
  if (category && !related.some(f => categoryOf(f) === category)) return false;
  if (intent === 'protected' && !related.some(f => protectionSignals(f).length > 0)) return false;
  if (intent === 'review' && related.some(f => protectionSignals(f).length > 0)) return false;
  if (pricing === 'known' && !related.some(knownPrice)) return false;
  if (pricing === 'unknown' && !related.some(f => !knownPrice(f))) return false;
  return true;
}

export function ResourcesView({initialProvider = '', initialCategory = '', initialIntent = '', initialPricing = ''}: {initialProvider?: string; initialCategory?: Category | ''; initialIntent?: Intent; initialPricing?: Pricing}) {
  const {scan, token, canAdmin, notify, openReview, setSelection} = useWorkspace();
  const router = useRouter(), params = useSearchParams();
  const live = !!scan && scan.status === 'completed' && scan.data_origin !== 'legacy_synthetic';
  const {page, error, reload} = useResources(scan?.scan_id, token, live);
  const {batch, refresh: refreshBatch} = useActiveBatch(live ? scan?.scan_id : undefined, token, reload);
  const [filters, setFilters] = useState<Filters>(empty), [query, setQuery] = useState(''), [selected, setSelected] = useState<Set<string>>(new Set());
  const [category, setCategory] = useState<Category | ''>(initialCategory), [intent, setIntent] = useState<Intent>(initialIntent), [pricing, setPricing] = useState<Pricing>(initialPricing);
  const [dialog, setDialog] = useState(false), [exporting, setExporting] = useState(false);
  const deferred = useDeferredValue(query);
  const openKey = params.get('resource');
  useEffect(() => {setFilters(f => ({...f, provider: params.get('provider') || initialProvider || ''})); setCategory(initialCategory); setIntent(initialIntent); setPricing(initialPricing);}, [params, initialProvider, initialCategory, initialIntent, initialPricing]);
  useEffect(() => {setSelected(new Set());}, [scan?.scan_id]);
  const findings = scan?.findings || [];
  const rows = useMemo(() => (page?.items || []).filter(r => matches(r, filters, deferred) && matchesDiscovery(r, findings, category, intent, pricing)).sort((a, b) => priorityRank[a.review_priority] - priorityRank[b.review_priority]), [page, filters, deferred, findings, category, intent, pricing]);
  const chosen = useMemo(() => (page?.items || []).filter(r => selected.has(r.resource_key)), [page, selected]);
  const reviewFindings = useMemo(() => {
    if (!scan || !chosen.length) return [];
    const keys = new Set(chosen.map(r => identityOf(r.provider, r.resource_id)));
    return scan.findings.filter(f => keys.has(identityOf(f.cloud_provider || 'azure', f.resource_id)));
  }, [scan, chosen]);
  useEffect(() => {setSelection(reviewFindings); return () => setSelection([]);}, [reviewFindings, setSelection]);
  const providerCounts = useMemo(() => Object.fromEntries([...new Set(findings.map(f => f.cloud_provider || 'azure'))].map(p => [p, findings.filter(f => (f.cloud_provider || 'azure') === p).length])), [findings]);
  const categoryCounts = useMemo(() => Object.fromEntries(categories.map(([id]) => [id, findings.filter(f => categoryOf(f) === id).length])), [findings]);
  const open = useCallback((key: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (key) next.set('resource', key); else next.delete('resource');
    next.delete('resource_id');
    const search = next.toString();
    router.replace(`/resources${search ? `?${search}` : ''}`, {scroll: false});
  }, [params, router]);
  useEffect(() => {
    const resourceId = params.get('resource_id');
    if (!resourceId || !page?.items.length || openKey) return;
    const provider = params.get('provider') || '';
    const match = page.items.find(r => r.resource_id === resourceId && (!provider || r.provider === provider));
    if (match) open(match.resource_key);
  }, [params, page?.items, openKey, open]);
  async function exportCsv() {
    if (!scan) return;
    setExporting(true);
    try {
      const search = new URLSearchParams(Object.entries({...filters, q: query}).filter(([, v]) => v)).toString();
      const report = await api<{filename: string; rows: number; content: string}>(`/scans/${scan.scan_id}/resources/export${search ? `?${search}` : ''}`, token);
      downloadFile(report.content, report.filename, 'text/csv;charset=utf-8');
      notify(`CSV download prepared for ${report.rows.toLocaleString()} resources.`);
    } catch (cause) {notify((cause as Error).message, 'error');} finally {setExporting(false);}
  }
  async function cancel() {
    if (!batch) return;
    try {await api(`/ai-batches/${batch.id}/cancel`, token, {method: 'POST'}); notify('Queued resources were cancelled.'); refreshBatch(); reload();}
    catch (cause) {notify((cause as Error).message, 'error');}
  }
  if (!scan) return <EmptyState icon={Server} title="No scan selected">Run a scan to analyze your resources.</EmptyState>;
  if (!live) return <EmptyState icon={Server} title="A live scan is required">Resource analysis uses saved observations from a completed live scan.</EmptyState>;
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!page) return <Loading label="Merging findings into resource assessments…"/>;
  const summary = page.summary;
  const allVisible = rows.length > 0 && rows.every(r => selected.has(r.resource_key));
  const toggleAll = () => setSelected(previous => {const next = new Set(previous); rows.forEach(r => allVisible ? next.delete(r.resource_key) : next.add(r.resource_key)); return next;});
  const toggle = (key: string) => setSelected(previous => {const next = new Set(previous); if (next.has(key)) next.delete(key); else next.add(key); return next;});
  const select = (name: keyof Filters, options: [string, string][], aria: string) => <label><span className="sr-only">{aria}</span><select aria-label={aria} value={filters[name]} onChange={e => setFilters(f => ({...f, [name]: e.target.value}))}>{options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>;
  const discoveryChips = [category && {label: `Category: ${categories.find(([id]) => id === category)?.[1]}`, clear: () => setCategory('')}, intent && {label: intent === 'protected' ? 'Protected intent' : 'Needs assessment', clear: () => setIntent('')}, pricing && {label: pricing === 'unknown' ? 'Price unknown' : 'Price observed', clear: () => setPricing('')}, filters.provider && {label: providerNames[filters.provider] || filters.provider, clear: () => setFilters(f => ({...f, provider: ''}))}].filter(Boolean) as {label: string; clear: () => void}[];
  const resetDiscovery = () => {setCategory(''); setIntent(''); setPricing(''); setFilters(f => ({...f, provider: ''}));};
  return <>
    <div className="resource-summary">
      <article><span>Resources</span><strong>{summary.total.toLocaleString()}</strong><small>From {scan.findings.length.toLocaleString()} findings</small></article>
      <article><span>AI assessed</span><strong>{(summary.ai_status.completed || 0).toLocaleString()}</strong><small>{(summary.ai_status.stale || 0).toLocaleString()} stale · {(summary.ai_status.not_run || 0).toLocaleString()} not run</small></article>
      <article><span>High or critical AI risk</span><strong>{((summary.ai_risk.high || 0) + (summary.ai_risk.critical || 0)).toLocaleString()}</strong><small>Unverified model suggestions</small></article>
      <article><span>Decisions</span><strong>{(summary.total - (summary.decision.none || 0)).toLocaleString()}</strong><small>{(summary.decision.defer || 0).toLocaleString()} deferred</small></article>
    </div>
    {summary.resolved_count != null && summary.no_longer_observed_count != null && <p className="resource-summary-note">Since the previous scan: {summary.resolved_count.toLocaleString()} resources no longer have findings and {summary.no_longer_observed_count.toLocaleString()} are no longer observed. This doesn’t prove deletion or savings.</p>}
    {batch && <BatchBanner batch={batch} onCancel={cancel} canAdmin={canAdmin}/>}
    <section className="panel resources-panel" aria-label="Resources">
      <div className="grid-heading"><div><h2>Resources <span className="count-badge">{rows.length.toLocaleString()}</span></h2><p>One place per resource — findings, pillars, pricing, AI, and decisions · observed {dateTime(page.observed_at)}</p></div>
        <div className="grid-display-controls">
          <Link className="button secondary" href="/resources/report"><Printer size={15}/>Print report</Link>
          <button className="button secondary" disabled={exporting} onClick={exportCsv}><Download size={15}/>Export CSV</button>
          {canAdmin && <button className="button primary" disabled={!!batch && ACTIVE_BATCH.includes(batch.status)} title={batch && ACTIVE_BATCH.includes(batch.status) ? 'An AI assessment is already running for this scan' : undefined} onClick={() => setDialog(true)}><BrainCircuit size={16}/>Run AI assessment</button>}
        </div></div>
      <div className="explorer-facets">
        <div className="provider-pills" role="group" aria-label="Cloud providers"><button aria-pressed={!filters.provider} onClick={() => setFilters(f => ({...f, provider: ''}))}>All clouds<span>{findings.length}</span></button>{Object.entries(providerCounts).sort().map(([id, count]) => <button key={id} className={`cloud-pill cloud-${id}`} aria-pressed={filters.provider === id} onClick={() => setFilters(f => ({...f, provider: f.provider === id ? '' : id}))}><span className="cloud-pill-dot"/>{providerNames[id] || id} <span>{count}</span></button>)}</div>
        <div className="category-pills" role="group" aria-label="Resource categories"><button aria-pressed={!category} onClick={() => setCategory('')}>All categories</button>{categories.filter(([id]) => (categoryCounts[id] || 0) > 0).map(([id, name]) => <button key={id} aria-pressed={category === id} onClick={() => setCategory(category === id ? '' : id)}>{name}<span>{categoryCounts[id]}</span></button>)}</div>
      </div>
      <div className="explorer-quick-views" role="group" aria-label="Evidence quick views"><span>Quick views</span><button aria-pressed={!intent && !pricing} onClick={() => {setIntent(''); setPricing('');}}>All evidence</button><button aria-pressed={intent === 'protected'} onClick={() => {setIntent(intent === 'protected' ? '' : 'protected'); setPricing('');}}><ShieldCheck size={13}/>Protected intent</button><button aria-pressed={pricing === 'unknown'} onClick={() => {setPricing(pricing === 'unknown' ? '' : 'unknown'); setIntent('');}}>Missing prices</button></div>
      {!!discoveryChips.length && <div className="active-filters"><Filter size={13}/>{discoveryChips.map(chip => <button key={chip.label} onClick={chip.clear}>{chip.label}<X size={12}/></button>)}<button className="clear-filters" onClick={resetDiscovery}>Clear all</button></div>}
      <div className="grid-filters">
        <label className="grid-search"><Search size={16}/><input type="search" aria-label="Search resources" placeholder="Search resource names or IDs…" value={query} onChange={e => setQuery(e.target.value)}/></label>
        {select('provider', [['', 'All clouds'], ...[...new Set(page.items.map(r => r.provider))].sort().map(p => [p, providerNames[p] || p] as [string, string])], 'Cloud provider')}
        {select('service_category',[['','All services'],...[...new Set(page.items.map(r=>r.service_category))].sort().map(v=>[v,sentence(v)] as [string,string])],'Service category')}
        {select('pillar_status',[['','All pillar statuses'],['observed','Observed'],['risk','Risk'],['unknown','Unknown']],'Pillar status')}
        {select('review_priority', [['', 'All priorities'], ['critical', 'Critical'], ['high', 'High'], ['evidence_required', 'Evidence required']], 'Review priority')}
        {select('ai_status', [['', 'All AI statuses'], ...Object.entries(aiStatusLabels)], 'AI status')}
        {select('ai_risk', [['', 'All AI risks'], ['critical', 'Critical'], ['high', 'High'], ['medium', 'Medium'], ['low', 'Low'], ['unknown', 'Unknown'], ['none', 'Not assessed']], 'AI risk')}
        {select('decision', [['', 'All decisions'], ...Object.entries(decisionLabels), ['none', 'No decision']], 'Decision')}
      </div>
      <div className="grid-scroll" tabIndex={0} aria-label="Scrollable resource table">
        <table className="data-table resource-table">
          <thead><tr><th><input type="checkbox" aria-label="Select all matching resources" checked={allVisible} onChange={toggleAll}/></th><th>Resource</th><th>Provider</th><th>Findings</th><th>Priority</th><th>Pillars</th><th>30d billed USD</th><th>30d effective USD</th><th>Retail opportunity</th><th>AI risk</th><th>AI status</th><th>Decision</th><th><span className="sr-only">Open</span></th></tr></thead>
          <tbody>{rows.map(r => <tr key={r.resource_key} className={selected.has(r.resource_key) ? 'row-selected' : ''} onClick={() => open(r.resource_key)}>
            <td onClick={e => e.stopPropagation()}><input type="checkbox" aria-label={`Select ${r.resource_name}`} checked={selected.has(r.resource_key)} onChange={() => toggle(r.resource_key)}/></td>
            <td><button className="resource-name" onClick={e => {e.stopPropagation(); open(r.resource_key);}}><strong>{r.resource_name || r.resource_id}</strong><small>{r.resource_type.split('/').slice(-1)[0]} {r.lifecycle_delta&&<span className="mini-badge">{r.lifecycle_delta}</span>}</small></button></td>
            <td><ProviderBadge provider={r.provider}/></td><td>{r.finding_count}</td><td>{sentence(r.review_priority)}</td><td><PillarDots pillars={r.pillars}/></td>
            <td className="money-cell">{money(r.billed_cost_usd??null)}</td><td className="money-cell">{money(r.effective_cost_usd??null)}</td>
            <td className={r.retail_estimate_usd === null ? 'unpriced-cell' : 'money-cell'}>{money(r.retail_estimate_usd)}</td>
            <td><AIRisk ai={r.ai}/></td><td><AIStatusBadge ai={r.ai}/></td><td><DecisionBadge decision={r.decision}/></td>
            <td><button className="icon-button" aria-label={`View analysis for ${r.resource_name}`} onClick={e => {e.stopPropagation(); open(r.resource_key);}}><ChevronRight size={16}/></button></td>
          </tr>)}
          {!rows.length && <tr><td colSpan={13}><EmptyState icon={Search} title="No matching resources">Try a broader search or remove a filter.<button className="button secondary" onClick={() => {setFilters(empty); setQuery(''); resetDiscovery();}}>Reset filters</button></EmptyState></td></tr>}</tbody>
        </table>
      </div>
      <div className="grid-footer"><span>{chosen.length ? `${chosen.length.toLocaleString()} selected · ` : ''}{rows.length.toLocaleString()} matching resources</span>{chosen.length > 0 && <button className="text-button" onClick={() => setSelected(new Set())}>Clear selection</button>}</div>
      {chosen.length > 0 && <div className="bulk-toolbar" role="region" aria-label="Selected resources actions"><span className="bulk-count"><strong>{chosen.length}</strong> selected</span><button className="button primary" onClick={() => openReview(reviewFindings)}><FileCode2 size={16}/>Review code<span className="shortcut-hint">⇧ R</span></button><button className="icon-button" aria-label="Clear selected resources" onClick={() => setSelected(new Set())}><X size={17}/></button></div>}
    </section>
    <BatchDialog open={dialog} onClose={() => setDialog(false)} scanId={scan.scan_id} selected={chosen} total={page.total} onCreated={created => {setDialog(false); notify(`AI assessment started for ${created.total.toLocaleString()} resources.`); refreshBatch(); reload();}}/>
    <ResourceDrawer scanId={scan.scan_id} resourceKey={openKey} onClose={() => open(null)} onChange={reload}/>
  </>;
}

export function ResourceReport() {
  const {scan, token, workspace} = useWorkspace();
  const live = !!scan && scan.status === 'completed' && scan.data_origin !== 'legacy_synthetic';
  const {page, error} = useResources(scan?.scan_id, token, live);
  if (!live) return <EmptyState icon={Server} title="A live scan is required">Select a completed live scan to print its resource report.</EmptyState>;
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!page) return <Loading label="Preparing your report…"/>;
  const rows = [...page.items].sort((a, b) => priorityRank[a.review_priority] - priorityRank[b.review_priority]);
  return <article className="resource-report">
    <div className="report-actions"><Link className="button secondary" href="/resources">Back</Link><button className="button primary" onClick={() => window.print()}><Printer size={15}/>Print</button></div>
    <header><h1>Resource analysis report</h1><p>{workspace?.name} · Scan {scan.scan_id.slice(0, 8)} · Observed {dateTime(page.observed_at)} · Generated {dateTime(new Date().toISOString())}</p>
      <p>{page.summary.total.toLocaleString()} resources · {(page.summary.ai_status.completed || 0).toLocaleString()} with current AI assessments · {(page.summary.total - (page.summary.decision.none || 0)).toLocaleString()} with decisions</p></header>
    {rows.map(r => <section key={r.resource_key} className="report-resource">
      <h2>{r.resource_name || r.resource_id} <small>{providerNames[r.provider] || r.provider} · {sentence(r.review_priority)} · {money(r.retail_estimate_usd)}</small></h2>
      <p className="report-id">{r.resource_id}</p>
      <p>Pillars: {Object.entries(r.pillars).map(([p, s]) => `${p} ${s}`).join(' · ')}</p>
      <p>AI: {aiStatusLabels[r.ai.status]}{r.ai.risk_level ? ` · suggested risk ${r.ai.risk_level}` : ''}{r.ai.summary ? ` — ${r.ai.summary}` : ''}</p>
      {!!r.ai.actions.length && <ol>{r.ai.actions.map((a, i) => <li key={i}><strong>{a.title}</strong> ({sentence(a.kind)}, effort {a.effort}, change risk {a.change_risk}) — {a.rationale}</li>)}</ol>}
      {r.decision && <p>Decision: {decisionLabels[r.decision.decision]} · {dateTime(r.decision.created_at)}{r.decision.note ? ` — ${r.decision.note}` : ''}{r.decision.evidence_changed ? ' (evidence changed since)' : ''}</p>}
    </section>)}
    <footer>AI text is unverified advice. It doesn’t approve actions or establish dependencies, billed cost or live state. Guardrails in CloudSaver remain required.</footer>
  </article>;
}
