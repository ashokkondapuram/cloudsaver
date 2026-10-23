'use client';
import {useEffect,useRef,useState} from 'react';
import {BarChart3,BrainCircuit,ShieldCheck} from 'lucide-react';
import {api} from '../lib/api';
import {findingKey,money} from '../lib/finops';
import type {Finding} from '../lib/types';
import {useWorkspace} from './WorkspaceProvider';
import {EmptyState,Loading,Notice,ProviderBadge,SectionTitle} from './ui/shared';
type Check={code:string;status:'observed'|'risk'|'unknown';explanation:string};
type Assessment={disposition:string;protected_reasons:string[];evidence_coverage:{observed:number;total:number};guardrails:string[];pillars:{pillar:string;status:Check['status'];checks:Check[]}[]};
type Analysis={assessment:Assessment;ai_context:Record<string,unknown>};
type Targets={enabled:boolean;hourly_attempt_limit:number;targets:{target_id:string;provider:string;model:string}[]};
type Review={cached:boolean;warning:string;guardrails:string[];advice:{summary:string;risk_level:string;pillars:{pillar:string;observation:string;evidence_codes:string[]}[];review_questions:string[]}};
type Services={services:{provider:string;service_category:string;findings:number;protected_findings:number;risk_findings:number;unknown_price_findings:number;known_retail_subtotal_usd:number|null}[]};
const label=(value:string)=>value.replaceAll('_',' ').toLowerCase();
export function ServiceAnalysis(){
  const {scan,token}=useWorkspace();
  const [data,setData]=useState<Services|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    setData(null);setError('');const request=new AbortController();
    if(scan&&scan.status==='completed'&&scan.data_origin!=='legacy_synthetic')api<Services>(`/scans/${scan.scan_id}/analysis`,token,{signal:request.signal}).then(result=>{if(!request.signal.aborted)setData(result);}).catch(cause=>{if(!request.signal.aborted)setError((cause as Error).message);});
    return()=>request.abort();
  },[scan?.scan_id,token,scan?.status,scan?.data_origin]);
  return <section className="panel service-analysis"><SectionTitle title="Service architecture analysis">Five-pillar review signals across the complete selected snapshot · independent of page filters</SectionTitle>{error?<Notice tone="error">{error}</Notice>:!scan||scan.data_origin==='legacy_synthetic'?<EmptyState icon={BarChart3} title="A live scan is required">Service analysis uses saved resource observations.</EmptyState>:!data?<Loading label="Analysing saved service evidence…"/>:!data.services.length?<p className="inline-empty">No findings in this snapshot. This does not certify the full estate.</p>:<div className="summary-table-scroll"><table className="summary-table"><thead><tr><th>Service category</th><th>Provider</th><th>Findings</th><th>Protected</th><th>Observed risks</th><th>Unpriced</th><th>Known retail portion</th></tr></thead><tbody>{data.services.map(row=><tr key={row.provider+row.service_category}><td className="capitalize">{row.service_category}</td><td><ProviderBadge provider={row.provider}/></td><td>{row.findings}</td><td>{row.protected_findings}</td><td>{row.risk_findings}</td><td>{row.unknown_price_findings}</td><td>{money(row.known_retail_subtotal_usd)}</td></tr>)}</tbody></table></div>}<p className="analysis-footnote">Finding observations cover a subset of your inventory. Counts overlap across protected and risk columns. Open a finding’s 360° assessment to inspect the evidence; billed spend and realizable savings remain unknown.</p></section>;
}
export function ArchitecturalAssessment({finding}:{finding:Finding}){
  const {scan,token,canAdmin}=useWorkspace();
  const [data,setData]=useState<Analysis|null>(null),[targets,setTargets]=useState<Targets|null>(null),[target,setTarget]=useState('');
  const [error,setError]=useState(''),[aiError,setAIError]=useState(''),[ack,setAck]=useState(false),[busy,setBusy]=useState(false),[result,setResult]=useState<Review|null>(null);
  const controller=useRef<AbortController|null>(null),attempt=useRef(new Map<string,string>());
  const fingerprint=JSON.stringify([scan?.scan_id,findingKey(finding),token]);
  const current=useRef(fingerprint);current.current=fingerprint;
  useEffect(()=>{
    const request=new AbortController();controller.current?.abort();controller.current=request;
    setData(null);setTargets(null);setTarget('');setError('');setAIError('');setAck(false);setBusy(false);setResult(null);attempt.current.clear();
    if(!scan||scan.status!=='completed'||scan.data_origin==='legacy_synthetic'){setError('Assessment requires a completed live scan observation.');return()=>request.abort();}
    Promise.all([api<Analysis>(`/scans/${scan.scan_id}/analysis/resource`,token,{body:{resource_id:finding.resource_id,rule_id:finding.rule_id},signal:request.signal}),api<Targets>('/ai/targets',token,{signal:request.signal}).catch(()=>({enabled:false,hourly_attempt_limit:0,targets:[]}))]).then(([analysis,available])=>{if(!request.signal.aborted){setData(analysis);setTargets(available);setTarget(available.targets[0]?.target_id||'');}}).catch(cause=>{if(!request.signal.aborted)setError((cause as Error).message);});
    return()=>request.abort();
  },[fingerprint]);
  async function evaluate(){
    if(!ack||!target||!data||!scan||busy)return;
    const version=fingerprint,request=new AbortController();controller.current?.abort();controller.current=request;
    if(!attempt.current.has(target))attempt.current.set(target,crypto.randomUUID());
    setBusy(true);setAIError('');setResult(null);
    try{
      const review=await api<Review>(`/scans/${scan.scan_id}/ai-risk-evaluation`,token,{body:{resource_id:finding.resource_id,rule_id:finding.rule_id,target_id:target,idempotency_key:attempt.current.get(target),acknowledge_external_processing:true},signal:request.signal});
      if(!request.signal.aborted&&current.current===version)setResult(review);
    }catch(cause){if(!request.signal.aborted&&current.current===version)setAIError((cause as Error).message);}
    finally{if(!request.signal.aborted&&current.current===version)setBusy(false);}
  }
  if(error)return <Notice tone="error">{error}</Notice>;
  if(!data)return <Loading label="Building five-pillar assessment…"/>;
  const assessment=data.assessment;
  return <div className="architecture-assessment"><div className="assessment-intro"><ShieldCheck size={23}/><div><span className="eyebrow">360° SERVICE ANALYSIS</span><h3>{assessment.disposition==='protected'?'Protected resource':'Independent review required'}</h3><p>{assessment.evidence_coverage.observed} of {assessment.evidence_coverage.total} checks have observed evidence. An observed setting is not a safety certification.</p></div></div>
    {!!assessment.protected_reasons.length&&<Notice tone="warning">Recovery or retention intent detected: {assessment.protected_reasons.map(label).join(', ')}. Destructive script generation is blocked.</Notice>}
    <div className="pillar-list">{assessment.pillars.map(pillar=><details key={pillar.pillar} open={pillar.status==='risk'}><summary><strong className="capitalize">{pillar.pillar}</strong><span className={`assessment-state ${pillar.status}`}>{pillar.status==='risk'?'Risk observed':pillar.status==='observed'?'Evidence observed':'Evidence incomplete'}</span></summary><div>{pillar.checks.map(check=><article key={check.code}><span className={`assessment-dot ${check.status}`}/><div><h4>{label(check.code)}</h4><p>{check.explanation}</p><small>{check.status==='unknown'?'Unknown — needs verification':check.status==='risk'?'Observed risk':'Observed setting'}</small></div></article>)}</div></details>)}</div>
    <div className="drawer-section"><h3>Required guardrails</h3><ul className="assessment-guardrails">{assessment.guardrails.map(code=><li key={code}>{label(code)}</li>)}</ul></div>
    <section className="ai-advisory"><div className="ai-advisory-heading"><BrainCircuit size={21}/><div><h3>AI risk advisory</h3><p>Optional cloud model review · no action approval or generated code</p></div></div>
      {!targets?.enabled||!targets.targets.length?<p className="inline-empty">No approved AI target is enabled for this workspace. An operator can configure a tenant-bound Azure, Bedrock, or Vertex target.</p>:<><label className="ai-target-label">Approved model target<select value={target} disabled={busy} onChange={e=>{setTarget(e.target.value);setAck(false);setResult(null);setAIError('');}}>{targets.targets.map(item=><option key={item.target_id} value={item.target_id}>{item.target_id} · {item.provider} · {item.model}</option>)}</select></label><details className="raw-evidence"><summary>Inspect the exact evidence sent to the model</summary><pre className="evidence-json">{JSON.stringify(data.ai_context,null,2)}</pre></details><p className="inline-help">Only the displayed facts and a fixed review instruction are sent. Resource names, resource IDs, raw tags, and free-text scan details are excluded. The selected cloud provider processes the request; operator retention and regional policies apply. Limit: {targets.hourly_attempt_limit} attempts per workspace per UTC hour.</p><label className="checkbox-row ai-ack"><input type="checkbox" checked={ack} disabled={busy||!canAdmin} onChange={e=>setAck(e.target.checked)}/>I acknowledge external processing of this sanitized evidence.</label><button className="button primary" disabled={!canAdmin||!ack||!target||busy} onClick={evaluate}><BrainCircuit size={16}/>{busy?'Requesting advisory…':result?'Read cached advisory':'Request AI advisory'}</button>{!canAdmin&&<p className="inline-help">A workspace administrator can request AI inference.</p>}<p className="inline-help">Repeated submissions for this target reuse the attempt key. Pending or uncertain requests are not automatically invoked again; inference can incur provider charges.</p></>}
      {aiError&&<Notice tone="error">{aiError}</Notice>}{result&&<div className="ai-result" aria-live="polite"><span className="eyebrow">UNVERIFIED MODEL ADVICE{result.cached?' · CACHED':''}</span><Notice tone="warning">{result.warning}</Notice><h4>Suggested risk: {result.advice.risk_level}</h4><p>{result.advice.summary}</p>{result.advice.pillars.map(p=><article key={p.pillar}><h4 className="capitalize">{p.pillar}</h4><p>{p.observation}</p><small>Saved check references: {p.evidence_codes.map(label).join(', ')||'None — evidence gap'}</small></article>)}<h4>Questions for independent review</h4><ul>{result.advice.review_questions.map((q,i)=><li key={i}>{q}</li>)}</ul><p className="inline-help">The deterministic guardrails above remain required regardless of model text.</p></div>}
    </section>
  </div>;
}
