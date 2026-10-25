'use client';

import Link from 'next/link';
import {useEffect, useMemo, useState} from 'react';
import {Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts';
import {ArrowDownRight, ArrowRight, ArrowUpRight, Blocks, CheckCircle2, ChevronRight, Cloud, FileCode2, History, ShieldCheck, Sparkles, Target, Wallet} from 'lucide-react';
import {api} from '../lib/api';
import {compact, dateTime, money, opportunityTotals, providerColors, providerNames, providerOf, ruleLabel, scopeOf} from '../lib/finops';
import type {Finding} from '../lib/types';
import {useWorkspace} from './WorkspaceProvider';
import {useResources} from '../lib/resources';
import {BillingEvidencePanel} from './EnterpriseEvidence';
import {EmptyState, Loading, Notice, PriorityBadge, ProviderBadge, SectionTitle} from './ui/shared';

export function useScopedFindings() {
  const {scan,scope} = useWorkspace();
  return useMemo(() => (scan?.findings || []).filter(f => !scope.length || scope.includes(scopeOf(f))), [scan,scope]);
}

type Trend = {total_snapshots:number;direction:string;net_change_usd:number|null;new_findings_count:number|null;resolved_findings_count:number|null;snapshots:{scan_id:string;timestamp:string;total_findings:number;total_monthly_waste_usd?:number|null}[]};

export function TrendChart() {
  const {scan,token,scope,setScope} = useWorkspace();
  const [trend,setTrend] = useState<Trend | null>(null), [error,setError] = useState(''), [metric,setMetric] = useState<'findings'|'estimate'>('findings');
  useEffect(() => {
    setTrend(null); setError('');
    if (!scan) return;
    const controller = new AbortController();
    api<Trend>(`/trends?days=30&scan_id=${encodeURIComponent(scan.scan_id)}`,token,{signal:controller.signal}).then(setTrend).catch(() => {if (!controller.signal.aborted) setError('History could not be loaded. Refresh the workspace to try again.');});
    return () => controller.abort();
  }, [scan?.scan_id,token]);
  const points = (trend?.snapshots || []).map(point => ({...point,time:new Date(point.timestamp).valueOf(),findings:point.total_findings,estimate:point.total_monthly_waste_usd ?? null}));
  const hasPrices = points.filter(p => p.estimate !== null).length >= 2;
  return <section className="panel trajectory-panel"><SectionTitle title="Finding trajectory" action={<div className="segmented-control" aria-label="Chart metric"><button aria-pressed={metric === 'findings'} onClick={() => setMetric('findings')}>Findings</button><button aria-pressed={metric === 'estimate'} disabled={!hasPrices} title={hasPrices ? 'View comparable retail estimates' : 'Two priced snapshots are required'} onClick={() => setMetric('estimate')}>Retail estimate</button></div>}>Comparable snapshots · last 30 days</SectionTitle>
    {scope.length ? <EmptyState icon={History} title="History uses complete scan scopes">Clear the scope filter to compare snapshots with the same provider and scope selection.<button className="text-button" onClick={() => setScope([])}>Clear scope filter<ArrowRight size={14}/></button></EmptyState> : !scan ? <EmptyState icon={History} title="Your history starts with a scan">Saved observations will build a picture of resource changes over time.</EmptyState> : error ? <p className="chart-error" role="status">{error}</p> : !trend ? <Loading label="Loading comparable snapshots…"/> : points.length < 2 ? <EmptyState icon={History} title="A baseline is taking shape">{points.length ? 'One snapshot is available. A second scan with matching scope is needed to compare changes.' : 'No comparable snapshots are available for this scan.'}</EmptyState> : <>
      <div className="chart-summary"><strong>{metric === 'findings' ? compact(points[points.length-1].findings) : money(points[points.length-1].estimate)}</strong><span>{metric === 'findings' ? 'findings in latest snapshot' : 'latest monthly retail estimate'}</span><div>{trend.new_findings_count !== null && <><span className="trend-delta"><ArrowUpRight size={14}/>{trend.new_findings_count} new</span><span className="trend-delta decrease"><ArrowDownRight size={14}/>{trend.resolved_findings_count} no longer observed</span></>}</div></div>
      <div className="trend-chart" role="img" aria-label={`${metric === 'findings' ? 'Finding count' : 'Monthly retail estimate'} across ${points.length} comparable snapshots`}>
        <ResponsiveContainer width="100%" height="100%"><AreaChart data={points} margin={{top:12,right:16,bottom:0,left:0}} accessibilityLayer>
          <defs><linearGradient id="trajectory-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6366f1" stopOpacity={0.2}/><stop offset="95%" stopColor="#6366f1" stopOpacity={0.01}/></linearGradient></defs>
          <CartesianGrid vertical={false} stroke="var(--chart-grid)" strokeDasharray="3 4"/>
          <XAxis type="number" dataKey="time" domain={['dataMin','dataMax']} tickFormatter={v => new Date(v).toLocaleDateString(undefined,{month:'short',day:'numeric'})} axisLine={false} tickLine={false} tick={{fill:'var(--chart-muted)',fontSize:11}} minTickGap={35} tickMargin={12}/>
          <YAxis width={55} allowDecimals={false} axisLine={false} tickLine={false} tick={{fill:'var(--chart-muted)',fontSize:11}} tickFormatter={v => metric === 'estimate' ? '$' + compact(v) : compact(v)}/>
          <Tooltip content={({active,payload}) => active && payload?.length ? <div className="chart-tooltip"><strong>{dateTime(payload[0].payload.timestamp)}</strong><span>{metric === 'findings' ? `${payload[0].payload.findings} findings` : money(payload[0].payload.estimate)}</span></div> : null}/>
          <Area type="monotone" dataKey={metric} name={metric === 'findings' ? 'Findings' : 'Retail estimate'} stroke="var(--chart-line)" strokeWidth={2.5} fill="url(#trajectory-fill)" dot={{r:3,fill:'var(--surface)',strokeWidth:2}} activeDot={{r:5}} isAnimationActive={false} connectNulls={false}/>
        </AreaChart></ResponsiveContainer>
      </div><div className="chart-caption"><span><i/>Observed {metric === 'findings' ? 'findings' : 'retail estimates'}</span><span>{trend.total_snapshots} comparable scans · absence does not prove remediation</span></div>
    </>}
  </section>;
}

function Distribution({findings}: {findings:Finding[]}) {
  const providers = [...new Set(findings.map(providerOf))];
  const distribution = providers.map(provider => ({name:providerNames[provider] || provider,provider,value:findings.filter(f => providerOf(f) === provider).length}));
  return <section className="panel distribution-panel"><SectionTitle title="Multi-cloud distribution">Where your findings are concentrated</SectionTitle>{findings.length ? <><div className="distribution-chart"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={distribution} dataKey="value" nameKey="name" innerRadius={66} outerRadius={88} paddingAngle={3} stroke="none" isAnimationActive={false}>{distribution.map(item => <Cell key={item.provider} fill={providerColors[item.provider] || '#64748b'}/>)}</Pie><Tooltip formatter={(value) => [String(value)+' findings','Observed']}/></PieChart></ResponsiveContainer><div className="donut-center"><strong>{compact(findings.length)}</strong><span>findings</span></div></div><div className="distribution-legend">{distribution.map(item => <Link key={item.provider} href={`/findings?provider=${item.provider}`}><span className="legend-provider"><i style={{background:providerColors[item.provider]}}/>{item.name}</span><strong>{item.value}<small>{Math.round(item.value/findings.length*100)}%</small></strong><ChevronRight size={14}/></Link>)}</div></> : <EmptyState icon={Cloud} title="No findings to group">Provider coverage will appear after a completed scan.</EmptyState>}</section>;
}

export function Overview() {
  const {scan,workspace,scope,canAdmin,setOverlay,token,canBill,openFinding}=useWorkspace();
  const {page,error}=useResources(scan?.scan_id,token,!!scan&&scan.status==='completed');
  const findings=useScopedFindings();
  const rows=(page?.items||[]).filter(r=>!scope.length||scope.includes(r.scope_id));
  const complete=!!page&&page.total===page.items.length;
  const eligible=new Set(rows.filter(r=>r.disposition==='requires_review').map(r=>r.resource_id));
  const opportunities=findings.filter(f=>eligible.has(f.resource_id));
  const totals=opportunityTotals(opportunities);
  const priorities=[...rows].filter(r=>r.disposition==='requires_review').slice(0,5);
  const baseline=page?.commitment_baseline;
  return <>
    {error&&<Notice tone="error">{error}</Notice>}
    {!complete&&page&&<Notice>Resource metrics require the complete authorized result set. Narrow the scan before relying on totals.</Notice>}
    <section className="kpi-grid" aria-label="Workspace metrics">
      <article className="metric-card metric-featured"><div className="metric-label">Deduplicated retail opportunity<Wallet size={17}/></div><strong>{money(complete?totals.total:null)}</strong><div className="metric-footnote">Review resources only · estimates, not realized savings</div></article>
      <article className="metric-card"><div className="metric-label">Resources requiring review<Blocks size={17}/></div><strong>{complete?rows.filter(r=>r.disposition==='requires_review').length:'—'}</strong><div className="metric-footnote">One merged five-pillar review per resource</div></article>
      <article className="metric-card"><div className="metric-label">Protected resources<ShieldCheck size={17}/></div><strong>{complete?rows.filter(r=>r.disposition==='protected').length:'—'}</strong><div className="metric-footnote">Recovery, retention and locks take precedence</div></article>
      <article className="metric-card"><div className="metric-label">Clean hourly commitment ceiling<Target size={17}/></div><strong>{scope.length?'Select all scan scopes':baseline?.recommended_new_commitment_hr==null?'Unknown':`$${baseline.recommended_new_commitment_hr}/hr`}</strong><div className="metric-footnote">Complete hourly evidence required · purchase approval separate</div></article>
    </section>
    {baseline&&<Notice>{baseline.warning}</Notice>}
    <div className="analytics-grid"><TrendChart/><Distribution findings={findings}/></div>
    <div className="overview-lower"><section className="panel priority-panel"><SectionTitle title="Your resource review queue" action={<Link className="text-link" href="/resources">View all resources<ArrowRight size={15}/></Link>}>Merged cost, reliability, performance, security and operations evidence</SectionTitle>{priorities.length?<div className="priority-list">{priorities.map(r=><Link className="priority-resource" key={r.resource_key} href={`/resources?resource=${r.resource_key}`}><strong>{r.resource_name}</strong><small>{r.finding_count} rule signals · {r.review_priority.replaceAll('_',' ')}</small><ProviderBadge provider={r.provider}/><span>{money(r.retail_estimate_usd)}</span><ChevronRight size={15}/></Link>)}</div>:<EmptyState icon={ShieldCheck} title={scan?'No resources require review in this view':'Ready for your first scan'}>{scan?'Review evidence gaps and healthy inventory in Resources.':'Discover resources across your authorized cloud scopes.'}{!scan&&canAdmin&&<button className="button primary" onClick={()=>setOverlay('scan')}>Run first scan</button>}</EmptyState>}</section><section className="panel workspace-checklist"><SectionTitle title="Workspace foundations">Keep evidence and execution connected</SectionTitle><p>{workspace?.configured_scope_count??workspace?.subscription_ids.length} authorized cloud scopes.</p><p>{scan?`Snapshot ${dateTime(scan.timestamp)}`:'Capture a resource snapshot to begin.'}</p><Link className="button secondary" href="/settings">Configure scopes and evidence</Link><Link className="button secondary" href="/agents">Review agent tasks</Link></section></div>
    <section className="panel priority-panel"><SectionTitle title="Your review queue" action={<Link className="text-link" href="/findings">View all findings<ArrowRight size={15}/></Link>}>Individual rule findings; the resource queue above merges overlapping signals.</SectionTitle>{findings.length ? <div className="priority-list">{[...findings].sort((a,b)=>({CRITICAL:0,HIGH:1,MEDIUM:2,LOW:3,INFO:4}[a.severity]??5)-({CRITICAL:0,HIGH:1,MEDIUM:2,LOW:3,INFO:4}[b.severity]??5)).slice(0,6).map(f=><button key={f.resource_id+f.rule_id} onClick={()=>openFinding(f,findings)}><span className={`resource-symbol resource-${providerOf(f)}`}><Blocks size={18}/></span><span className="priority-resource"><strong>{f.resource_name}</strong><small>{ruleLabel(f.rule_id)}</small></span><ProviderBadge provider={providerOf(f)}/><PriorityBadge severity={f.severity}/><span className="priority-cost">{money(f.estimated_monthly_waste_usd)}</span><ChevronRight size={15}/></button>)}</div>:<EmptyState icon={ShieldCheck} title="No findings in this view">Select a completed scan or review your filters.</EmptyState>}</section>
    {canBill&&<BillingEvidencePanel/>}
  </>;
}

function SearchIcon() {return <Sparkles size={15}/>;}
