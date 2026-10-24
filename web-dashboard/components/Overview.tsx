'use client';

import Link from 'next/link';
import {useEffect, useMemo, useState} from 'react';
import {Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts';
import {ArrowDownRight, ArrowRight, ArrowUpRight, Blocks, CheckCircle2, ChevronRight, Cloud, FileCode2, History, ShieldCheck, Sparkles, Target, Wallet} from 'lucide-react';
import {api} from '../lib/api';
import {compact, dateTime, money, opportunityTotals, providerColors, providerNames, providerOf, ruleLabel, scopeOf} from '../lib/finops';
import type {Finding} from '../lib/types';
import {useWorkspace} from './WorkspaceProvider';
import {EmptyState, Loading, PriorityBadge, ProviderBadge, SectionTitle} from './ui/shared';

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
  const {scan,workspace,scope,canAdmin,setOverlay,openFinding} = useWorkspace();
  const findings = useScopedFindings();
  const priced = findings.filter(f => f.estimated_monthly_waste_usd !== null);
  const knownTotal = scope.length ? opportunityTotals(findings).total : scan?.total_monthly_waste_usd;
  const high = findings.filter(f => ['CRITICAL','HIGH'].includes(f.severity)).length;
  const rank:Record<string,number> = {CRITICAL:0,HIGH:1,MEDIUM:2,LOW:3,INFO:4};
  const priorities = [...findings].sort((a,b) => (rank[a.severity] ?? 5) - (rank[b.severity] ?? 5) || (b.estimated_monthly_waste_usd || 0) - (a.estimated_monthly_waste_usd || 0)).slice(0,5);
  return <>
    <section className="kpi-grid" aria-label="Workspace metrics"><article className="metric-card metric-featured"><div className="metric-label">Monthly retail estimate<Wallet size={17}/></div><strong className={knownTotal == null ? 'metric-unknown' : ''}>{money(knownTotal)}</strong><div className="metric-footnote"><span className="small-dot"/>{priced.length}/{findings.length} findings have price evidence</div></article><article className="metric-card"><div className="metric-label">Findings to review<Blocks size={17}/></div><strong>{scan ? compact(findings.length) : '—'}</strong><div className="metric-footnote"><span className="mini-badge amber">{high} high priority</span><span>in this view</span></div></article><article className="metric-card"><div className="metric-label">Pricing coverage<Target size={17}/></div><strong>{findings.length ? `${Math.round(priced.length/findings.length*100)}%` : '—'}</strong><div className="metric-footnote">{findings.length - priced.length} findings need pricing evidence</div></article><article className="metric-card"><div className="metric-label">Scopes scanned<Cloud size={17}/></div><strong>{scan ? scope.length || scan.subscriptions_scanned : '—'}</strong><div className="metric-footnote">{(scan?.cloud_providers || workspace?.providers || []).map(p => providerNames[p] || p).join(' · ') || 'Authorized sources only'}</div></article></section>
    <div className="analytics-grid"><TrendChart/><Distribution findings={findings}/></div>
    <div className="overview-lower"><section className="panel priority-panel"><SectionTitle title="Your review queue" action={<Link className="text-link" href="/findings">View all findings<ArrowRight size={15}/></Link>}>Start with higher-priority resource signals</SectionTitle>{priorities.length ? <div className="priority-list">{priorities.map(f => <button key={f.resource_id + f.rule_id} onClick={() => openFinding(f)}><span className={`resource-symbol resource-${providerOf(f)}`}><Blocks size={18}/></span><span className="priority-resource"><strong>{f.resource_name}</strong><small>{ruleLabel(f.rule_id)}</small></span><ProviderBadge provider={providerOf(f)}/><PriorityBadge severity={f.severity}/><span className="priority-cost">{money(f.estimated_monthly_waste_usd)}</span><ChevronRight size={15}/></button>)}</div> : <EmptyState icon={ShieldCheck} title={scan ? 'No findings in this view' : 'Ready for your first scan'}>{scan ? 'Try a different scope or select another snapshot.' : 'Discover resource signals across your authorized cloud providers.'}{!scan && canAdmin && <button className="button primary" onClick={() => setOverlay('scan')}><SearchIcon/>Run first scan</button>}</EmptyState>}</section><section className="panel workspace-checklist"><SectionTitle title="Workspace foundations">Your path from visibility to review</SectionTitle><div className="checklist-item"><CheckCircle2 size={20}/><div><strong>Cloud scopes configured</strong><p>{workspace?.configured_scope_count ?? workspace?.subscription_ids.length} authorized scopes available.</p></div><Link href="/settings" aria-label="View cloud accounts"><ChevronRight size={16}/></Link></div><div className={`checklist-item ${scan ? '' : 'pending'}`}><CheckCircle2 size={20}/><div><strong>{scan ? 'Resource snapshot saved' : 'Capture a resource snapshot'}</strong><p>{scan ? dateTime(scan.timestamp) : 'A scan creates your first review baseline.'}</p></div></div><div className={`checklist-item ${priced.length ? '' : 'pending'}`}><Target size={20}/><div><strong>{priced.length ? 'Cost evidence available' : 'Build your cost evidence'}</strong><p>Unknown prices stay separate from verified estimates.</p></div><Link href="/allocation" aria-label="View cost evidence"><ChevronRight size={16}/></Link></div><Link href="/automation" className="checklist-link"><FileCode2 size={17}/><span>Explore review workflows</span><ArrowRight size={15}/></Link></section></div>
  </>;
}

function SearchIcon() {return <Sparkles size={15}/>;}
