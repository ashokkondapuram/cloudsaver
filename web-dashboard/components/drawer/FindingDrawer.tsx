'use client';

import Link from 'next/link';
import {useEffect, useId, useRef, useState} from 'react';
import {Activity, ArrowRight, Check, Clipboard, Clock3, Code2, Copy, Database, Download, FileCode2, GitPullRequest, Layers3, Loader2, ShieldCheck, Wallet} from 'lucide-react';
import {api} from '../../lib/api';
import {bashRules, dateTime, downloadFile, findingKey, money, observedTags, providerOf, ruleLabel, scopeOf, terraformRules} from '../../lib/finops';
import type {Delivery, Finding} from '../../lib/types';
import {useWorkspace} from '../WorkspaceProvider';
import {Dialog} from '../ui/dialog';
import {EmptyState, Loading, Notice, PriorityBadge, ProviderBadge} from '../ui/shared';

export function CodeReview({findings}: {findings:Finding[]}) {
  const {scan,token,workspace,canAdmin,notify} = useWorkspace();
  const [result,setResult] = useState<{content:string;filename:string;kind:string}|null>(null);
  const [busy,setBusy] = useState(''), [error,setError] = useState('');
  const controller = useRef<AbortController | null>(null);
  const resources = [...new Set(findings.map(f => f.resource_id))];
  const fingerprint = JSON.stringify([scan?.scan_id,resources]);
  const current = useRef(fingerprint); current.current = fingerprint;
  useEffect(() => {controller.current?.abort();setResult(null);setError('');setBusy('');return()=>controller.current?.abort();}, [fingerprint]);
  const common = !!scan && scan.status === 'completed' && scan.data_origin !== 'legacy_synthetic' && canAdmin && resources.length > 0 && resources.length <= 50;
  const sameProvider = new Set(findings.map(providerOf)).size === 1;
  const canTerraform = common && workspace?.can_export_terraform && sameProvider && findings.every(f => terraformRules.has(f.rule_id));
  const canBash = common && sameProvider && findings.every(f => providerOf(f) === 'azure' && bashRules.has(f.rule_id));
  const reason = !canAdmin ? 'A workspace administrator can generate review artifacts.' : scan?.data_origin === 'legacy_synthetic' ? 'Historical synthetic snapshots cannot generate code.' : !resources.length ? 'Select at least one resource to review.' : resources.length > 50 ? 'Choose up to 50 unique resources per review.' : !sameProvider ? 'Choose resources from one provider per review.' : !canTerraform && !canBash ? 'These finding types or your current plan do not support code export.' : '';
  async function generate(kind:'terraform'|'bash') {
    controller.current?.abort(); const request = new AbortController();controller.current = request;
    const version = fingerprint;setBusy(kind);setError('');setResult(null);
    try {
      const response = await api<{hcl?:string;script?:string;filename:string}>(`/scans/${scan!.scan_id}/${kind === 'terraform' ? 'remediation-terraform' : 'remediation'}`,token,{body:{resource_ids:resources},signal:request.signal});
      if(current.current !== version || request.signal.aborted) return;
      setResult({content:response.hcl || response.script || '',filename:response.filename,kind});
    } catch(cause) {if(!request.signal.aborted && current.current === version) setError((cause as Error).message);}
    finally {if(current.current === version) setBusy('');}
  }
  return <div className="code-review"><div className="review-safety"><ShieldCheck size={20}/><div><strong>Review before execution</strong><p>These controls generate code. CloudSaver does not execute it or change your cloud resources.</p></div></div>
    {!!reason && <Notice tone="warning">{reason}</Notice>}
    <div className="code-review-actions"><button className="button primary" disabled={!canTerraform || !!busy} onClick={() => generate('terraform')}>{busy === 'terraform' ? <Loader2 size={16} className="spin"/> : <FileCode2 size={16}/>}Preview Terraform imports</button><button className="button secondary" disabled={!canBash || !!busy} onClick={() => generate('bash')}>{busy === 'bash' ? <Loader2 size={16} className="spin"/> : <Code2 size={16}/>}Preview Bash script</button></div>
    {!workspace?.can_export_terraform && canAdmin && <p className="inline-help">Terraform review requires a plan with export access. <Link href="/settings">View your plan</Link></p>}
    {error && <Notice tone="error">{error}</Notice>}{busy && <Loading label="Generating your review artifact…"/>}
    {result ? <div className="code-file"><div className="code-file-header"><span><FileCode2 size={15}/>{result.filename}</span><div><button className="icon-button" aria-label="Copy generated code" onClick={() => navigator.clipboard.writeText(result.content).then(()=>notify('Code copied to clipboard.')).catch(()=>notify('Clipboard is unavailable. Download the file instead.','info'))}><Copy size={15}/></button><button className="button secondary small" onClick={() => downloadFile(result.content,result.filename)}><Download size={14}/>Download</button></div></div><pre tabIndex={0} aria-label="Generated code preview"><code>{result.content}</code></pre><div className="code-file-footer">{result.kind === 'terraform' ? 'Import declarations only · inspect provider and state ownership before use' : 'Review all deletion, snapshot, and retention behavior before execution'}</div></div> : !busy && <div className="code-preview-empty"><FileCode2 size={28}/><h4>Your generated code will appear here</h4><p>Preview an artifact to inspect the exact content before downloading.</p></div>}
    <p className="inline-help">A generated artifact is not deletion approval. Independently verify resource state, backups, and retention requirements.</p>
  </div>;
}

function Evidence({finding}: {finding:Finding}) {
  const {scan,notify} = useWorkspace();
  const tags = observedTags(finding);
  const evidence = Object.entries(finding.evidence || {}).filter(([key]) => !['tags','labels'].includes(key));
  return <><div className="drawer-section"><span className="eyebrow">WHY THIS RESOURCE WAS FLAGGED</span><h3>{ruleLabel(finding.rule_id)}</h3><p className="finding-explanation">{finding.details}</p></div><div className="observation-summary"><div><Clock3 size={17}/><span>Observed<strong>{scan ? dateTime(scan.timestamp) : 'Unknown'}</strong></span></div><div><Database size={17}/><span>Source<strong>{String(finding.evidence?.source || 'Saved resource observation')}</strong></span></div></div>
    <div className="drawer-section"><h3>Resource identity</h3><dl className="detail-metadata"><div><dt>Provider</dt><dd><ProviderBadge provider={providerOf(finding)}/></dd></div><div><dt>Resource type</dt><dd>{finding.resource_type}</dd></div><div><dt>Group / namespace</dt><dd>{finding.resource_group || 'Not supplied'}</dd></div><div><dt>Account / scope</dt><dd><code>{scopeOf(finding)}</code></dd></div><div className="full-width"><dt>Resource ID <button className="icon-button" aria-label="Copy resource ID" onClick={() => navigator.clipboard.writeText(finding.resource_id).then(()=>notify('Resource ID copied.')).catch(()=>notify('Clipboard access is unavailable.','info'))}><Copy size={13}/></button></dt><dd><code>{finding.resource_id}</code></dd></div></dl></div>
    {!!evidence.length && <div className="drawer-section"><h3>Observed evidence</h3><dl className="detail-metadata">{evidence.slice(0,8).map(([key,value]) => <div key={key} className={typeof value === 'object' ? 'full-width' : ''}><dt>{key.replaceAll('_',' ')}</dt><dd>{typeof value === 'object' ? <pre className="evidence-json">{JSON.stringify(value,null,2)}</pre> : String(value ?? 'Not supplied')}</dd></div>)}</dl><details className="raw-evidence"><summary>View complete observation JSON</summary><pre className="evidence-json">{JSON.stringify(finding.evidence,null,2)}</pre></details></div>}
    <div className="drawer-section"><h3>Observed tags</h3>{Object.keys(tags).length ? <div className="tag-list">{Object.entries(tags).map(([key,value]) => <span key={key}>{key}<strong>{value}</strong></span>)}</div> : <p className="muted">No tags were supplied in this observation.</p>}</div>
  </>;
}

function CostBreakdown({finding}: {finding:Finding}) {
  const amount = finding.estimated_monthly_waste_usd;
  const cost = finding.cost_attribution;
  return <><div className="drawer-cost-grid"><article><span>Monthly retail estimate</span><strong>{money(amount)}</strong><small>USD / month</small></article><article><span>Net realizable savings</span><strong>{money(cost?.realizable_savings_usd)}</strong><small>After applicable costs and constraints</small></article></div><div className="drawer-section"><h3>Follow the calculation</h3><dl className="calculation-list"><div><dt>Pricing confidence</dt><dd><span className={`evidence-badge ${cost?.confidence === 'HIGH' ? 'verified' : ''}`}>{cost?.confidence === 'HIGH' ? 'High confidence' : 'Unknown'}</span></dd></div><div><dt>Price basis</dt><dd>{cost?.calculation_basis || 'No verified price evidence is attached to this finding.'}</dd></div>{cost?.unit_price != null && <div><dt>Unit price</dt><dd>{money(cost.unit_price)}{cost.unit_of_measure ? ` / ${cost.unit_of_measure}` : ''}</dd></div>}<div><dt>Annualized retail estimate</dt><dd>{amount == null ? 'Not estimated' : money(amount*12)}</dd></div></dl></div><Notice>Retail estimates are not your billed spend. Realizable savings require billing, workload, backup, and retention evidence.</Notice><div className="drawer-section"><h3>Historical spend</h3><div className="evidence-unavailable"><Wallet size={21}/><div><strong>No billing time series attached</strong><p>This resource observation does not contain a historical cost feed.</p></div></div></div></>;
}

function FindingActivity() {
  const {scan,token} = useWorkspace();
  const [rows,setRows] = useState<Delivery[] | null>(null), [error,setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    api<{items:Delivery[]}>('/operations/deliveries?limit=100',token,{signal:controller.signal}).then(page => setRows(page.items.filter(row => row.scan_id === scan?.scan_id))).catch(()=>{if(!controller.signal.aborted)setError('Delivery history is unavailable.');});
    return () => controller.abort();
  }, [scan?.scan_id,token]);
  return <><div className="drawer-section"><h3>Snapshot provenance</h3><div className="audit-timeline"><div><span className="timeline-dot"/><strong>Resource observation saved</strong><time>{scan ? dateTime(scan.timestamp) : 'Unknown'}</time><p>Scan <code>{scan?.scan_id}</code></p></div></div></div><div className="drawer-section"><h3>Recent scan notification delivery</h3><p className="muted">Matching entries among the 100 most recent workspace deliveries.</p>{error ? <Notice>{error}</Notice> : !rows ? <Loading/> : rows.length ? <div className="audit-timeline">{rows.map(row => <div key={row.id}><span className="timeline-dot"/><strong>{row.target_id || row.kind} · {row.status.replaceAll('_',' ')}</strong><time>{dateTime(row.updated_at)}</time><p>{row.attempts} attempts · {row.error_code?.replaceAll('_',' ') || 'No error recorded'}</p></div>)}</div> : <p className="inline-empty">No matching notification deliveries in recent history.</p>}<Link className="text-link" href="/activity">Open delivery history<ArrowRight size={15}/></Link></div><div className="integration-placeholder"><Clipboard size={22}/><h3>Issue tracking is not connected</h3><p>Jira and ServiceNow issue assignment are not available in this workspace.</p><Link className="text-link" href="/settings">View integrations<ArrowRight size={14}/></Link></div></>;
}

export function FindingDrawer() {
  const {overlay,setOverlay,finding} = useWorkspace();
  const [tab,setTab] = useState('evidence');
  const id = useId();
  useEffect(() => {setTab('evidence');}, [finding]);
  if (!finding) return null;
  const tabs = [{id:'evidence',label:'Evidence',icon:Layers3},{id:'cost',label:'Cost breakdown',icon:Wallet},{id:'code',label:'Review code',icon:FileCode2},{id:'activity',label:'Activity & ITSM',icon:Activity}];
  return <Dialog open={overlay === 'finding'} onClose={() => setOverlay(null)} title="Finding details" drawer>
    <div className="finding-drawer-header"><div className="finding-badges"><ProviderBadge provider={providerOf(finding)}/><PriorityBadge severity={finding.severity}/><span className="state-badge review-required">Review required</span></div><h2>{finding.resource_name}</h2><p>{ruleLabel(finding.rule_id)}</p></div>
    <div className="drawer-tabs" role="tablist" aria-label="Finding detail views" onKeyDown={e => {if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();const index=tabs.findIndex(t=>t.id===tab);const next=tabs[(index+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length];setTab(next.id);document.getElementById(`${id}-${next.id}-tab`)?.focus();}}}>{tabs.map(item => <button key={item.id} role="tab" id={`${id}-${item.id}-tab`} aria-controls={`${id}-${item.id}`} aria-selected={tab===item.id} tabIndex={tab===item.id?0:-1} onClick={() => setTab(item.id)}><item.icon size={15}/>{item.label}</button>)}</div>
    <div className="drawer-tab-content" role="tabpanel" id={`${id}-${tab}`} aria-labelledby={`${id}-${tab}-tab`} key={findingKey(finding)+tab}>{tab==='evidence'?<Evidence finding={finding}/>:tab==='cost'?<CostBreakdown finding={finding}/>:tab==='code'?<CodeReview findings={[finding]}/>:<FindingActivity/>}</div>
    <div className="drawer-footer"><ShieldCheck size={15}/>Read-only evidence. All code requires independent review.</div>
  </Dialog>;
}

export function ReviewDrawer() {
  const {overlay,setOverlay,review,scan} = useWorkspace();
  const [included,setIncluded] = useState<string[]>([]);
  useEffect(() => {if(overlay==='review')setIncluded(review.map(findingKey));}, [overlay,review]);
  const findings = review.filter(f => included.includes(findingKey(f)));
  return <Dialog open={overlay==='review'} onClose={() => setOverlay(null)} title="Review selected resources" drawer><div className="dialog-content"><div className="batch-review-heading"><span className="review-icon"><FileCode2 size={23}/></span><div><h3>{findings.length} findings selected</h3><p>Scan {scan?.scan_id.slice(0,8)} · review artifacts only</p></div></div><details className="review-selection" open><summary>Resources included in this review</summary><div>{review.map(f => <label key={findingKey(f)}><input type="checkbox" checked={included.includes(findingKey(f))} onChange={() => setIncluded(previous => previous.includes(findingKey(f)) ? previous.filter(id => id!==findingKey(f)) : [...previous,findingKey(f)])}/><span><strong>{f.resource_name}</strong><small>{ruleLabel(f.rule_id)}</small></span><ProviderBadge provider={providerOf(f)}/></label>)}</div></details><CodeReview findings={findings}/></div></Dialog>;
}
