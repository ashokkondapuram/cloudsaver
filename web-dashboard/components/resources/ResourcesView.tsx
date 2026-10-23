'use client';
import Link from 'next/link';
import {useCallback, useDeferredValue, useEffect, useMemo, useRef, useState} from 'react';
import {useRouter, useSearchParams} from 'next/navigation';
import {BrainCircuit, ChevronRight, Download, Loader2, Printer, Search, Server, X} from 'lucide-react';
import {api} from '../../lib/api';
import {dateTime, downloadFile, money, providerNames} from '../../lib/finops';
import {ACTIVE_BATCH, aiStatusLabels, decisionLabels, sentence, useActiveBatch, useResources, type Batch, type ResourceRow, type Targets} from '../../lib/resources';
import {useWorkspace} from '../WorkspaceProvider';
import {Dialog} from '../ui/dialog';
import {EmptyState, Loading, Notice, ProviderBadge} from '../ui/shared';
import {AIRisk, AIStatusBadge, DecisionBadge, PillarDots} from './ResourceParts';
import {ResourceDrawer} from './ResourceDrawer';

type Filters = {provider: string; review_priority: string; ai_status: string; ai_risk: string; decision: string};
const empty: Filters = {provider: '', review_priority: '', ai_status: '', ai_risk: '', decision: ''};
const priorityRank: Record<string, number> = {critical: 0, high: 1, evidence_required: 2};

function matches(row: ResourceRow, filters: Filters, query: string) {
  const needle = query.trim().toLowerCase();
  return (!filters.provider || row.provider === filters.provider) && (!filters.review_priority || row.review_priority === filters.review_priority)
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

export function ResourcesView() {
  const {scan, token, canAdmin, notify} = useWorkspace();
  const router = useRouter(), params = useSearchParams();
  const live = !!scan && scan.status === 'completed' && scan.data_origin !== 'legacy_synthetic';
  const {page, error, reload} = useResources(scan?.scan_id, token, live);
  const {batch, refresh: refreshBatch} = useActiveBatch(live ? scan?.scan_id : undefined, token, reload);
  const [filters, setFilters] = useState<Filters>(empty), [query, setQuery] = useState(''), [selected, setSelected] = useState<Set<string>>(new Set());
  const [dialog, setDialog] = useState(false), [exporting, setExporting] = useState(false);
  const deferred = useDeferredValue(query);
  const openKey = params.get('resource');
  useEffect(() => {setSelected(new Set());}, [scan?.scan_id]);
  const rows = useMemo(() => (page?.items || []).filter(r => matches(r, filters, deferred)).sort((a, b) => priorityRank[a.review_priority] - priorityRank[b.review_priority]), [page, filters, deferred]);
  const chosen = useMemo(() => (page?.items || []).filter(r => selected.has(r.resource_key)), [page, selected]);
  const open = useCallback((key: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (key) next.set('resource', key); else next.delete('resource');
    const search = next.toString();
    router.replace(`/resources${search ? `?${search}` : ''}`, {scroll: false});
  }, [params, router]);
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
  return <>
    <div className="resource-summary">
      <article><span>Resources</span><strong>{summary.total.toLocaleString()}</strong><small>From {scan.findings.length.toLocaleString()} findings</small></article>
      <article><span>AI assessed</span><strong>{(summary.ai_status.completed || 0).toLocaleString()}</strong><small>{(summary.ai_status.stale || 0).toLocaleString()} stale · {(summary.ai_status.not_run || 0).toLocaleString()} not run</small></article>
      <article><span>High or critical AI risk</span><strong>{((summary.ai_risk.high || 0) + (summary.ai_risk.critical || 0)).toLocaleString()}</strong><small>Unverified model suggestions</small></article>
      <article><span>Decisions</span><strong>{(summary.total - (summary.decision.none || 0)).toLocaleString()}</strong><small>{(summary.decision.defer || 0).toLocaleString()} deferred</small></article>
    </div>
    {batch && <BatchBanner batch={batch} onCancel={cancel} canAdmin={canAdmin}/>}
    <section className="panel resources-panel" aria-label="Resource analysis">
      <div className="grid-heading"><div><h2>Resource analysis <span className="count-badge">{rows.length.toLocaleString()}</span></h2><p>One assessment per resource, merged from all of its findings · observed {dateTime(page.observed_at)}</p></div>
        <div className="grid-display-controls">
          <button className="button secondary" disabled={exporting} onClick={exportCsv}><Download size={15}/>Export CSV</button>
          <Link className="button secondary" href="/resources/report"><Printer size={15}/>Print report</Link>
          {canAdmin && <button className="button primary" disabled={!!batch && ACTIVE_BATCH.includes(batch.status)} title={batch && ACTIVE_BATCH.includes(batch.status) ? 'An AI assessment is already running for this scan' : undefined} onClick={() => setDialog(true)}><BrainCircuit size={16}/>Run AI assessment</button>}
        </div></div>
      <div className="grid-filters">
        <label className="grid-search"><Search size={16}/><input type="search" aria-label="Search resources" placeholder="Search resource names or IDs…" value={query} onChange={e => setQuery(e.target.value)}/></label>
        {select('provider', [['', 'All clouds'], ...[...new Set(page.items.map(r => r.provider))].sort().map(p => [p, providerNames[p] || p] as [string, string])], 'Cloud provider')}
        {select('review_priority', [['', 'All priorities'], ['critical', 'Critical'], ['high', 'High'], ['evidence_required', 'Evidence required']], 'Review priority')}
        {select('ai_status', [['', 'All AI statuses'], ...Object.entries(aiStatusLabels)], 'AI status')}
        {select('ai_risk', [['', 'All AI risks'], ['critical', 'Critical'], ['high', 'High'], ['medium', 'Medium'], ['low', 'Low'], ['unknown', 'Unknown'], ['none', 'Not assessed']], 'AI risk')}
        {select('decision', [['', 'All decisions'], ...Object.entries(decisionLabels), ['none', 'No decision']], 'Decision')}
      </div>
      <div className="grid-scroll" tabIndex={0} aria-label="Scrollable resource table">
        <table className="data-table resource-table">
          <thead><tr><th><input type="checkbox" aria-label="Select all matching resources" checked={allVisible} onChange={toggleAll}/></th><th>Resource</th><th>Provider</th><th>Findings</th><th>Priority</th><th>Pillars</th><th>Retail estimate</th><th>AI risk</th><th>AI status</th><th>Decision</th><th><span className="sr-only">Open</span></th></tr></thead>
          <tbody>{rows.map(r => <tr key={r.resource_key} className={selected.has(r.resource_key) ? 'row-selected' : ''} onClick={() => open(r.resource_key)}>
            <td onClick={e => e.stopPropagation()}><input type="checkbox" aria-label={`Select ${r.resource_name}`} checked={selected.has(r.resource_key)} onChange={() => toggle(r.resource_key)}/></td>
            <td><button className="resource-name" onClick={e => {e.stopPropagation(); open(r.resource_key);}}><strong>{r.resource_name || r.resource_id}</strong><small>{r.resource_type.split('/').slice(-1)[0]}</small></button></td>
            <td><ProviderBadge provider={r.provider}/></td><td>{r.finding_count}</td><td>{sentence(r.review_priority)}</td><td><PillarDots pillars={r.pillars}/></td>
            <td className={r.retail_estimate_usd === null ? 'unpriced-cell' : 'money-cell'}>{money(r.retail_estimate_usd)}</td>
            <td><AIRisk ai={r.ai}/></td><td><AIStatusBadge ai={r.ai}/></td><td><DecisionBadge decision={r.decision}/></td>
            <td><button className="icon-button" aria-label={`View analysis for ${r.resource_name}`} onClick={e => {e.stopPropagation(); open(r.resource_key);}}><ChevronRight size={16}/></button></td>
          </tr>)}
          {!rows.length && <tr><td colSpan={11}><EmptyState icon={Search} title="No matching resources">Try a broader search or remove a filter.<button className="button secondary" onClick={() => {setFilters(empty); setQuery('');}}>Reset filters</button></EmptyState></td></tr>}</tbody>
        </table>
      </div>
      <div className="grid-footer"><span>{chosen.length ? `${chosen.length.toLocaleString()} selected · ` : ''}{rows.length.toLocaleString()} matching resources</span>{chosen.length > 0 && <button className="text-button" onClick={() => setSelected(new Set())}>Clear selection</button>}</div>
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
