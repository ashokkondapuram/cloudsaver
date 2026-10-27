'use client';

import Link from 'next/link';
import {useEffect, useMemo, useState} from 'react';
import {Boxes, Download, FileCode2, ShieldCheck} from 'lucide-react';
import {api} from '../../lib/api';
import {dateTime, downloadFile, money} from '../../lib/finops';
import {sentence} from '../../lib/resources';
import {useWorkspace} from '../WorkspaceProvider';
import {Dialog} from '../ui/dialog';
import {EmptyState, Loading, Notice, SectionTitle} from '../ui/shared';

type Source={source_id:string;collector_type:string;status:string;coverage_ratio:number|null;valid_samples:number|null;expected_samples:number|null;observed_window_start:string|null;observed_window_end:string|null;reason_code:string|null};
type Metric={sufficient:boolean;p95:number|null;p99:number|null;maximum:number|null;coverage_ratio:number;gap_reason:string|null;window_start:string;window_end:string;max_gap_minutes:number|null};
type Evaluation={rule_id:string;name?:string;outcome:string;reason:string;safety_blocks?:string[];recommendation?:Record<string,number>|null};
type Resource={resource_id:string;resource_name:string;cluster_id:string;resource_type:string;namespace:string|null;evidence_digest:string;data_sources:Source[];reconciliation_status:string;
  evidence:{pod?:string;container?:string;node?:string;controller?:{name:string;kind:string}|null;qos_class?:string;hpa_present?:boolean|null;cpu_request?:number|null;memory_request?:number|null;fixed_heap_configured?:boolean;node_pool?:string;metrics?:Record<string,Metric|null>};
  costs:{workload_used_estimate_usd:number|null;workload_request_slack_estimate_usd:number|null;cluster_unallocated_slack_usd:number|null;billed_node_cost_usd:number|null;realizable_node_savings_usd:number|null;allocation_total_usd:number|null;explanation:string};evaluations:Evaluation[]};
type Capacity={allocatable:number|null;requested:number|null;daemonset:number|null;actual_p95:number|null;physical:number|null};
type NodePool={name:string|null;vm_size:string|null;count:number|null;mode:string|null;os_type:string|null};
type AzureResource={resource_id:string;resource_group:string|null;region:string|null;sku_tier:string|null;kubernetes_version:string|null;
  node_resource_group:string|null;power_state:string|null;fqdn:string|null;private_cluster:boolean|null;network_plugin:string|null;
  node_pools:NodePool[];node_count:number|null;tags:Record<string,string>};
type Cluster={cluster_id:string;coverage:Record<string,number>;sources:Source[];capacity:Record<'cpu'|'memory',Capacity>;azure_resource:AzureResource|null;billed_node_cost_usd?:number|null;realizable_node_savings_usd?:number|null;reconciliation_status:string};
type View={scan_id:string;observed_at:string;clusters:Cluster[];resources:Resource[];financial_note:string;rule_matrix:{rule_id:string;name:string;pillar:string;outcomes:Record<string,number>}[]};
type Patch={filename:string;content:string;diff:string;replicas_reviewed:number;warning:string;review_commands:string[]};
const labelOverrides:Record<string,string>={OOMKILL_OBSERVED:'Out-of-memory kill observed'};
const label=(value:string)=>labelOverrides[value]||sentence(value);
const amount=(value:number|null|undefined,unit='')=>value==null?'Unknown':value.toLocaleString('en-US',{maximumFractionDigits:2})+unit;

function AzureClusterDetails({resource}:{resource:AzureResource|null}) {
  if(!resource)return <p className="inline-help">No Azure resource matched this cluster in the current scan.</p>;
  const fields:[string,string][]=[
    ['Resource group',resource.resource_group||'Unknown'],['Region',resource.region||'Unknown'],
    ['Kubernetes version',resource.kubernetes_version||'Unknown'],['SKU tier',resource.sku_tier||'Unknown'],
    ['Node resource group',resource.node_resource_group||'Unknown'],['Power state',resource.power_state||'Unknown'],
    ['Network plugin',resource.network_plugin||'Unknown'],['Private cluster',resource.private_cluster==null?'Unknown':resource.private_cluster?'Yes':'No'],
    ['Node count',resource.node_count==null?'Unknown':String(resource.node_count)]];
  return <div className="k8s-azure-details">
    <dl className="settings-key-values">{fields.map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>
    {!!resource.node_pools.length&&<div className="drawer-cost-grid">{resource.node_pools.map((pool,i)=><article key={pool.name||i}><span>{pool.name||'Node pool'}</span><strong>{pool.count??'Unknown'}</strong><small>{pool.vm_size||'Unknown size'} · {pool.mode||'Unknown mode'} · {pool.os_type||'Unknown OS'}</small></article>)}</div>}
    <p className="inline-help">Fetched from Azure Resource Graph. Utilization, OOM kills and allocation evidence below require a Prometheus binding for this cluster.</p>
  </div>;
}

function CapacityBar({value,dimension}:{value:Capacity;dimension:'cpu'|'memory'}) {
  const divisor=dimension==='memory'?1024**3:1,unit=dimension==='memory'?' GiB':' cores';
  const known=value.allocatable!=null&&value.allocatable>0&&value.requested!=null&&value.daemonset!=null;
  return <article className="k8s-capacity"><h4>{dimension==='cpu'?'CPU':'Memory'} capacity</h4>
    <div className="k8s-capacity-track" aria-hidden="true">{known&&<><span className="k8s-daemon" style={{width:`${Math.min(100,100*value.daemonset!/value.allocatable!)}%`}}/><span className="k8s-requested" style={{width:`${Math.min(100-Math.min(100,100*value.daemonset!/value.allocatable!),100*Math.max(0,value.requested!-value.daemonset!)/value.allocatable!)}%`}}/></>}</div>
    <dl className="k8s-capacity-values"><div><dt>Allocatable</dt><dd>{amount(value.allocatable==null?null:value.allocatable/divisor,unit)}</dd></div><div><dt>DaemonSet overhead</dt><dd>{amount(value.daemonset==null?null:value.daemonset/divisor,unit)}</dd></div><div><dt>Workload requested, incl. agents</dt><dd>{amount(value.requested==null?null:value.requested/divisor,unit)}</dd></div><div><dt>Actual cluster P95 / physical</dt><dd>Unknown / Unknown</dd></div></dl>
    <p className="inline-help">Reservations describe allocation. Summing container P95 values would not establish cluster P95 or removable nodes.</p>
  </article>;
}

function ResourceReview({resource,scanId,onClose}:{resource:Resource|null;scanId:string;onClose:()=>void}) {
  const {token,canAdmin}=useWorkspace();
  const [patch,setPatch]=useState<Patch|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{setPatch(null);setError('');setBusy(false);},[resource?.resource_id]);
  if(!resource)return null;
  const r=resource;
  const candidates=r.evaluations.filter(e=>e.outcome==='condition_detected'&&e.recommendation&&!(e.safety_blocks||[]).length);
  async function preview(ruleId:string) {
    setBusy(true);setError('');setPatch(null);
    try {setPatch(await api<Patch>(`/scans/${scanId}/kubernetes/patch-preview`,token,{body:{resource_id:r.resource_id,rule_id:ruleId,evidence_digest:r.evidence_digest}}));}
    catch(cause){setError((cause as Error).message);}finally{setBusy(false);}
  }
  return <Dialog open={!!resource} onClose={onClose} title="Kubernetes resource review" className="k8s-review">
    <div className="dialog-content"><span className="eyebrow">{r.cluster_id} / {r.namespace||'Cluster scope'}</span><h3>{r.resource_name}</h3><p>{r.evidence.controller?`${r.evidence.controller.kind} / ${r.evidence.controller.name}`:r.resource_type}</p>
      <Notice tone="warning">Read-only evidence review. Every change requires workload-owner approval and a current manifest review.</Notice>
      <section className="drawer-section"><h4>Metric evidence</h4>{Object.entries(r.evidence.metrics||{}).length?<div className="summary-table-scroll"><table className="data-table"><thead><tr><th>Signal</th><th>P95</th><th>P99</th><th>Coverage</th></tr></thead><tbody>{Object.entries(r.evidence.metrics||{}).map(([name,m])=><tr key={name}><td>{label(name)}</td><td>{amount(m?.p95)}</td><td>{amount(m?.p99)}</td><td>{m?`${(100*m.coverage_ratio).toFixed(1)}% · ${m.sufficient?'complete':label(m.gap_reason||'incomplete')}`:'Unavailable'}</td></tr>)}</tbody></table></div>:<p>No historical metric evidence is attached.</p>}</section>
      <section className="drawer-section"><h4>Rules & safety gates</h4>{r.evaluations.map(e=><article className="k8s-rule-result" key={e.rule_id}><strong>{e.name||e.rule_id}</strong><span className="status-tag">{label(e.outcome)}</span><p>{e.reason}</p>{e.safety_blocks?.length? <p className="inline-help">Blocked: {e.safety_blocks.map(label).join(' · ')}</p>:null}</article>)}{!r.evaluations.length&&<p>No applicable contract is published for this object type.</p>}</section>
      <section className="drawer-section"><h4>Allocation & cloud invoice</h4><dl className="k8s-capacity-values">{[['Used allocation estimate',r.costs.workload_used_estimate_usd],['Request slack estimate',r.costs.workload_request_slack_estimate_usd],['Cluster unallocated cost',r.costs.cluster_unallocated_slack_usd],['Billed node cost',r.costs.billed_node_cost_usd],['Realizable node savings',r.costs.realizable_node_savings_usd]].map(([name,value])=><div key={String(name)}><dt>{String(name)}</dt><dd>{value==null?'Unknown':money(value as number)}</dd></div>)}</dl><p className="inline-help">{r.costs.explanation}</p></section>
      <section className="drawer-section"><h4>Manifest review</h4><p>No limits, HPA targets or live cluster resources are changed here. Preview eligibility is rechecked for every observed replica.</p>{canAdmin?candidates.map(e=><button className="button secondary" key={e.rule_id} disabled={busy} onClick={()=>preview(e.rule_id)}><FileCode2 size={16}/>{busy?'Checking evidence…':`Preview ${e.rule_id.includes('CPU')?'CPU':'memory'} request patch`}</button>):<p className="inline-help">A workspace administrator can generate eligible review patches.</p>}{canAdmin&&!candidates.length&&<p className="inline-help">No request patch is eligible under the saved evidence and safety gates.</p>}
        {error&&<Notice tone="error">{error}</Notice>}{patch&&<div aria-live="polite"><p>{patch.warning}</p><pre className="code-block">{patch.diff}</pre><details><summary>Strategic merge patch & dry-run review</summary><pre className="code-block">{patch.content}</pre><pre className="code-block">{patch.review_commands.join('\n')}</pre></details><button className="button secondary" onClick={()=>downloadFile(patch.content,patch.filename,'application/yaml')}><Download size={16}/>Download review patch</button></div>}</section>
    </div>
  </Dialog>;
}

export function KubernetesWorkspace() {
  const {scan,token}=useWorkspace();
  const [data,setData]=useState<View|null>(null),[error,setError]=useState('');
  const [cluster,setCluster]=useState(''),[namespace,setNamespace]=useState(''),[kind,setKind]=useState(''),[qos,setQos]=useState(''),[risk,setRisk]=useState(''),[query,setQuery]=useState('');
  const [selected,setSelected]=useState<Resource|null>(null),[page,setPage]=useState(0);
  useEffect(()=>{
    const request=new AbortController();setData(null);setError('');setSelected(null);
    if(scan?.status==='completed')api<View>(`/scans/${scan.scan_id}/kubernetes`,token,{signal:request.signal}).then(value=>{if(!request.signal.aborted)setData(value);}).catch(cause=>{if(!request.signal.aborted)setError((cause as Error).message);});
    return()=>request.abort();
  },[scan?.scan_id,scan?.status,token]);
  useEffect(()=>{setPage(0);},[cluster,namespace,kind,qos,risk,query]);
  const rows=useMemo(()=> (data?.resources||[]).filter(r=>(!cluster||r.cluster_id===cluster)&&(!namespace||r.namespace===namespace)&&(!kind||r.resource_type===kind)&&(!qos||r.evidence.qos_class===qos)&&(!risk||r.evaluations.some(e=>e.outcome==='condition_detected'&&(risk==='review'||e.safety_blocks?.includes(risk))))&&(!query||`${r.resource_name} ${r.evidence.controller?.name||''} ${r.evidence.pod||''}`.toLowerCase().includes(query.toLowerCase()))),[data,cluster,namespace,kind,qos,risk,query]);
  const clusters=(data?.clusters||[]).filter(c=>!cluster||c.cluster_id===cluster);
  const options=(field:'cluster_id'|'namespace'|'resource_type')=>[...new Set((data?.resources||[]).map(r=>r[field]).filter(Boolean))].sort() as string[];
  return <><SectionTitle eyebrow="MULTI-SOURCE ANALYSIS" title="Kubernetes & containers">Trace workload requests, reliability risks and allocation evidence back to their sources.</SectionTitle>
    {!scan?<EmptyState icon={Boxes} title="No scan selected">Run a scan with Kubernetes selected to discover your authorized clusters.</EmptyState>:error?<Notice tone="error">{error}</Notice>:!data?<Loading label="Loading Kubernetes evidence…"/>:!data.clusters.length?<EmptyState icon={Boxes} title="No Kubernetes inventory in this scan">Choose a completed Kubernetes scan. An operator API binding enables full discovery; metrics-only discovery cannot prove cluster coverage.</EmptyState>:<>
      <Notice tone="info">Observed {dateTime(data.observed_at)}. {data.financial_note} <Link className="text-link" href="/settings?tab=rules">Manage analysis rules</Link></Notice>
      <section className="panel"><div className="grid-heading"><div><h2>Cluster & source health</h2><p>Unknown metrics retain inventory and block dependent recommendations.</p></div><ShieldCheck size={20}/></div>
        {clusters.map(c=><article className="k8s-cluster" key={c.cluster_id}><h3>{c.cluster_id} <span className="status-tag">{label(c.reconciliation_status)}</span></h3>
          <AzureClusterDetails resource={c.azure_resource}/>
          <dl className="k8s-counts">{['discovered_count','in_scope_count','evaluated_count','insufficient_evidence_count','excluded_count','unsupported_count'].map(key=><div key={key}><dt>{label(key.replace('_count',''))}</dt><dd>{c.coverage[key]??'Unknown'}</dd></div>)}</dl><p className="inline-help">Counters describe resource sets and may overlap across rules. Secondary-source failures appear below; primary inventory failures do not create a clean snapshot.</p>
          <div className="k8s-sources">{c.sources.map(s=><details key={s.source_id}><summary><strong>{s.source_id}</strong><span>{label(s.status)}{s.coverage_ratio!=null?` · ${(100*s.coverage_ratio).toFixed(1)}%`:''}</span></summary><p>{s.expected_samples?`${s.valid_samples?.toLocaleString()} / ${s.expected_samples.toLocaleString()} samples`:'No sample denominator available'}</p><p>{s.observed_window_start?dateTime(s.observed_window_start):'Window unknown'} → {s.observed_window_end?dateTime(s.observed_window_end):'Unknown'}</p>{s.reason_code&&<p>{label(s.reason_code)}</p>}</details>)}</div>
          <p className="inline-help">Imported 30-day billed node cost: {c.billed_node_cost_usd==null?'Unknown':money(c.billed_node_cost_usd)} · Modeled consolidation under verified scheduling: {c.realizable_node_savings_usd==null?'Unknown':money(c.realizable_node_savings_usd)}. This is not post-change verified savings.</p><div className="k8s-capacity-grid"><CapacityBar value={c.capacity.cpu} dimension="cpu"/><CapacityBar value={c.capacity.memory} dimension="memory"/></div></article>)}
      </section>
      <section className="panel"><div className="grid-heading"><div><h2>Namespace & workload explorer <span className="count-badge">{rows.length}</span></h2><p>Includes discovered objects with no findings.</p></div></div><div className="enterprise-filters k8s-filters">
        <label>Cluster<select value={cluster} onChange={e=>setCluster(e.target.value)}><option value="">All clusters</option>{options('cluster_id').map(x=><option key={x}>{x}</option>)}</select></label>
        <label>Namespace<select value={namespace} onChange={e=>setNamespace(e.target.value)}><option value="">All namespaces</option>{options('namespace').map(x=><option key={x}>{x}</option>)}</select></label>
        <label>Object type<select value={kind} onChange={e=>setKind(e.target.value)}><option value="">All objects</option>{options('resource_type').map(x=><option key={x} value={x}>{x.split('/')[1]}</option>)}</select></label>
        <label>QoS<select value={qos} onChange={e=>setQos(e.target.value)}><option value="">All QoS classes</option>{['Guaranteed','Burstable','BestEffort'].map(x=><option key={x}>{x}</option>)}</select></label>
        <label>Review signal<select value={risk} onChange={e=>setRisk(e.target.value)}><option value="">All evidence</option><option value="review">Review required</option><option value="OOMKILL_OBSERVED">Out-of-memory kill observed</option><option value="COORDINATED_HPA_REVIEW_REQUIRED">HPA coordination</option></select></label>
        <label>Search<input type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Workload, pod or resource"/></label></div>
        <div className="grid-scroll" tabIndex={0} aria-label="Scrollable Kubernetes resource table"><table className="data-table"><thead><tr><th>Resource</th><th>Namespace / controller</th><th>QoS / HPA</th><th>Review signals</th><th>Request slack estimate</th><th>Node savings</th></tr></thead><tbody>{rows.slice(page*50,(page+1)*50).map(r=><tr key={r.resource_id}><td><button className="resource-name" onClick={()=>setSelected(r)}>{r.resource_name}<small>{r.resource_type.split('/')[1]}</small></button></td><td>{r.namespace||'Cluster scope'}<small>{r.evidence.controller?.name||'—'}</small></td><td>{r.evidence.qos_class||'Unknown'}<small>HPA {r.evidence.hpa_present==null?'unknown':r.evidence.hpa_present?'present':'absent'}</small></td><td>{r.evaluations.filter(e=>e.outcome==='condition_detected').length} detected / {r.evaluations.filter(e=>e.outcome==='insufficient_evidence').length} unknown</td><td>{r.costs.workload_request_slack_estimate_usd==null?'Unknown':money(r.costs.workload_request_slack_estimate_usd)}</td><td>{r.costs.realizable_node_savings_usd==null?'Unknown':money(r.costs.realizable_node_savings_usd)}</td></tr>)}</tbody></table></div>
        {!rows.length&&<p className="k8s-empty">No resources match these filters.</p>}<div className="grid-pagination"><span>{rows.length?`${page*50+1}–${Math.min(rows.length,(page+1)*50)} of ${rows.length}`:'0 resources'}</span><button className="button secondary small" disabled={page===0} onClick={()=>setPage(p=>p-1)}>Previous</button><button className="button secondary small" disabled={(page+1)*50>=rows.length} onClick={()=>setPage(p=>p+1)}>Next</button></div>
      </section>
      <section className="panel"><div className="grid-heading"><div><h2>Rule evidence matrix</h2><p>Detected conditions retain their safety blocks; missing history never becomes a pass.</p></div></div><div className="summary-table-scroll"><table className="data-table"><thead><tr><th>Rule</th><th>Pillar</th><th>Saved outcomes</th></tr></thead><tbody>{data.rule_matrix.map(r=><tr key={r.rule_id}><td>{r.name}</td><td>{r.pillar}</td><td>{Object.entries(r.outcomes).map(([state,count])=>`${count} ${label(state).toLowerCase()}`).join(' · ')||'No eligible observations'}</td></tr>)}</tbody></table></div></section>
      <ResourceReview key={selected?.resource_id||'closed'} resource={selected} scanId={data.scan_id} onClose={()=>setSelected(null)}/>
    </>}
  </>;
}
