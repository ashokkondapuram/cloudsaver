'use client';
import {useEffect,useId,useRef,useState} from 'react';
import {BarChart3,BrainCircuit,ShieldCheck} from 'lucide-react';
import {useRouter} from 'next/navigation';
import {api} from '../lib/api';
import {resourceKeyOf,sentence} from '../lib/resources';
import {dateTime,findingKey,money} from '../lib/finops';
import type {Finding} from '../lib/types';
import {EvidenceRadar} from './drawer/EvidenceRadar';
import {useWorkspace} from './WorkspaceProvider';
import {EmptyState,Loading,Notice,ProviderBadge,SectionTitle} from './ui/shared';
type Observation={status:'recent'|'stale'|'unknown'|'invalid';observed_at:string|null;max_age_hours:number};
type Check={evidence_fields?:string[];code:string;status:'observed'|'risk'|'unknown';explanation:string};
type Assessment={policy_version?:string;evidence_digest?:string;observation?:Observation;review_priority?:string;evidence_gap_codes?:string[];disposition:string;protected_reasons:string[];evidence_coverage:{observed:number;total:number};guardrails:string[];pillars:{pillar:string;status:Check['status'];checks:Check[]}[]};
type Analysis={assessment:Assessment;ai_context:Record<string,unknown>};
type Targets={enabled:boolean;hourly_attempt_limit:number;targets:{target_id:string;provider:string;model:string;max_output_tokens?:number;allowed_source_providers?:string[]}[]};
type Review={usage?:{input_tokens:number|null;output_tokens:number|null;billed_cost_usd:null};evidence_digest?:string;assessment_policy_version?:string;cached:boolean;warning:string;guardrails:string[];advice:{summary:string;risk_level:string;pillars:{pillar:string;observation:string;evidence_codes:string[]}[];review_questions:string[]}};
type Services={policy_version?:string;review_queue_total?:number;coverage?:{finding_observations:number;unique_resources_with_findings:number;full_inventory:boolean;message:string};review_queue?:{resource_key:string;resource_id:string;rule_id:string;review_priority:string;risk_check_codes:string[];evidence_gap_codes:string[]}[];services:{provider:string;service_category:string;findings:number;protected_findings:number;risk_findings:number;unknown_price_findings:number;known_retail_subtotal_usd:number|null}[]};
const label=(value:string)=>value.replaceAll('_',' ').toLowerCase();
export function ServiceAnalysis(){
  const {scan,token}=useWorkspace();
  const router=useRouter();
  const [data,setData]=useState<Services|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    setData(null);setError('');const request=new AbortController();
    if(scan&&scan.status==='completed'&&scan.data_origin!=='legacy_synthetic')api<Services>(`/scans/${scan.scan_id}/analysis`,token,{signal:request.signal}).then(result=>{if(!request.signal.aborted)setData(result);}).catch(cause=>{if(!request.signal.aborted)setError((cause as Error).message);});
    return()=>request.abort();
  },[scan?.scan_id,token,scan?.status,scan?.data_origin]);
  return <section className="panel service-analysis"><SectionTitle title="Service architecture analysis">Five-pillar review signals across the complete selected snapshot · independent of page filters</SectionTitle>{data?.coverage&&<Notice tone="info">{data.coverage.message} {data.coverage.finding_observations} finding observations · {data.coverage.unique_resources_with_findings} resources with findings.</Notice>}{error?<Notice tone="error">{error}</Notice>:!scan||scan.data_origin==='legacy_synthetic'?<EmptyState icon={BarChart3} title="A live scan is required">Service analysis uses saved resource observations.</EmptyState>:!data?<Loading label="Analyzing saved service evidence…"/>:!data.services.length?<p className="inline-empty">No findings in this snapshot. This does not certify the full estate.</p>:<div className="summary-table-scroll"><table className="summary-table"><thead><tr><th>Service category</th><th>Provider</th><th>Findings</th><th>Protected</th><th>Observed risks</th><th>Unpriced</th><th>Known retail portion</th></tr></thead><tbody>{data.services.map(row=><tr key={row.provider+row.service_category}><td>{sentence(row.service_category)}</td><td><ProviderBadge provider={row.provider}/></td><td>{row.findings}</td><td>{row.protected_findings}</td><td>{row.risk_findings}</td><td>{row.unknown_price_findings}</td><td>{money(row.known_retail_subtotal_usd)}</td></tr>)}</tbody></table></div>}<p className="analysis-footnote">Finding observations cover a subset of your inventory. Counts overlap across protected and risk columns. Open a resource in Resources to inspect its evidence; billed spend and realizable savings remain unknown.</p></section>;
}
export function ArchitecturalAssessment({finding,embedded=false}:{finding:Finding;embedded?:boolean}){
  const {scan,token,canAdmin,setOverlay}=useWorkspace();
  const router=useRouter();
  const sectionId=useId();
  async function openResourceAnalysis(){const key=await resourceKeyOf(finding);setOverlay(null);router.push(`/resources?resource=${key}`);}
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
    if(!ack||!target||!data?.assessment.evidence_digest||!scan||busy)return;
    const version=fingerprint,request=new AbortController();controller.current?.abort();controller.current=request;
    if(!attempt.current.has(target))attempt.current.set(target,crypto.randomUUID());
    setBusy(true);setAIError('');setResult(null);
    try{
      const review=await api<Review>(`/scans/${scan.scan_id}/ai-risk-evaluation`,token,{body:{resource_id:finding.resource_id,rule_id:finding.rule_id,target_id:target,evidence_digest:data.assessment.evidence_digest,idempotency_key:attempt.current.get(target),acknowledge_external_processing:true},signal:request.signal});
      if(!request.signal.aborted&&current.current===version)setResult(review);
    }catch(cause){if(!request.signal.aborted&&current.current===version)setAIError((cause as Error).message);}
    finally{if(!request.signal.aborted&&current.current===version)setBusy(false);}
  }
  if(error)return <Notice tone="error">{error}</Notice>;
  if(!data)return <Loading label="Building five-pillar assessment…"/>;
  const assessment=data.assessment;
  const selectedTarget=targets?.targets.find(item=>item.target_id===target);
  const sourceAllowed=!selectedTarget?.allowed_source_providers||selectedTarget.allowed_source_providers.includes(finding.cloud_provider||'azure');
  return <div className="architecture-assessment"><div className="assessment-intro"><ShieldCheck size={23}/><div><span className="eyebrow">360° SERVICE ANALYSIS</span><h3>{assessment.disposition==='protected'?'Protected resource':'Independent review required'}</h3><p>{assessment.evidence_coverage.observed} of {assessment.evidence_coverage.total} checks have observed evidence. An observed setting is not a safety certification.</p>{!embedded&&<button className="button secondary" onClick={openResourceAnalysis}><BrainCircuit size={15}/>Open full resource details</button>}</div></div>
    {assessment.policy_version&&<div className="drawer-section"><h3>Assessment provenance</h3><p className="inline-help">Policy {assessment.policy_version} · Review priority: {label(assessment.review_priority||'evidence_required')} · {assessment.evidence_gap_codes?.length??0} evidence gaps</p><p className="inline-help">Observation: {sentence(assessment.observation?.status??'unknown')}{assessment.observation?.observed_at?` · ${dateTime(assessment.observation.observed_at)}`:''}. A recent observation is still a saved snapshot.</p>{assessment.evidence_digest&&<p className="inline-help" title={assessment.evidence_digest}>Evidence fingerprint: {assessment.evidence_digest.slice(0,16)}</p>}{assessment.observation?.status!=='recent'&&<Notice tone="warning">Refresh the scan before planning a change. This observation exceeds the {assessment.observation?.max_age_hours??24}-hour review window or its timestamp cannot be verified.</Notice>}</div>}
    {!!assessment.protected_reasons.length&&<Notice tone="warning">Recovery or retention intent detected: {assessment.protected_reasons.map(label).join(', ')}. Destructive script generation is blocked.</Notice>}
    {!embedded&&<><EvidenceRadar pillars={assessment.pillars} onInspect={pillar=>{const element=document.getElementById(`${sectionId}-${pillar}`) as HTMLDetailsElement|null;if(element){element.open=true;element.querySelector('summary')?.focus({preventScroll:true});const pane=element.closest<HTMLElement>('.drawer-tab-content');if(pane)pane.scrollBy({top:element.getBoundingClientRect().top-pane.getBoundingClientRect().top-12,behavior:'instant'});}}}/>
    <div className="pillar-list">{assessment.pillars.map(pillar=><details key={pillar.pillar} id={`${sectionId}-${pillar.pillar}`} open={pillar.status==='risk'}><summary><strong className="capitalize">{pillar.pillar}</strong><span className={`assessment-state ${pillar.status}`}>{pillar.status==='risk'?'Risk observed':pillar.status==='observed'?'Evidence observed':'Evidence incomplete'}</span></summary><div>{pillar.checks.map(check=><article key={check.code}><span className={`assessment-dot ${check.status}`}/><div><h4>{label(check.code)}</h4><p>{check.explanation}</p>{check.evidence_fields?.length?<small>Evidence fields: {check.evidence_fields.map(label).join(', ')}</small>:null}<small>{check.status==='unknown'?'Unknown — needs verification':check.status==='risk'?'Observed risk':'Observed setting'}</small></div></article>)}</div></details>)}</div>
    <div className="drawer-section"><h3>Required guardrails</h3><ul className="assessment-guardrails">{assessment.guardrails.map(code=><li key={code}>{label(code)}</li>)}</ul></div></>}
    <section className="ai-advisory"><div className="ai-advisory-heading"><BrainCircuit size={21}/><div><h3>AI risk advisory</h3><p>Optional cloud model review · no action approval or generated code</p></div></div>
      {!targets?.enabled||!targets.targets.length?<p className="inline-empty">No approved AI target is enabled for this workspace. Your platform operator can configure a workspace-bound Azure AI Foundry, Amazon Bedrock, or Google Vertex AI target.</p>:<><label className="ai-target-label">Approved model target<select value={target} disabled={busy} onChange={e=>{setTarget(e.target.value);setAck(false);setResult(null);setAIError('');}}>{targets.targets.map(item=><option key={item.target_id} value={item.target_id}>{item.target_id} · {item.provider} · {item.model}</option>)}</select></label><details className="raw-evidence"><summary>Inspect the exact evidence sent to the model</summary><pre className="evidence-json" tabIndex={0} aria-label="Sanitized AI context">{JSON.stringify(data.ai_context,null,2)}</pre></details>{selectedTarget?.max_output_tokens&&<p className="inline-help">Output ceiling: {selectedTarget.max_output_tokens} tokens per attempt. Actual provider usage is shown after a completed advisory; charges require billing reconciliation.</p>}{!sourceAllowed&&<Notice tone="warning">This target’s policy does not permit the selected resource provider.</Notice>}<p className="inline-help">Only the displayed facts and a fixed review instruction are sent. Resource names, resource IDs, raw tags, and free-text scan details are excluded. The selected cloud provider processes the request; operator retention and regional policies apply. Limit: {targets.hourly_attempt_limit} attempts per workspace per UTC hour.</p><label className="checkbox-row ai-ack"><input type="checkbox" checked={ack} disabled={busy||!canAdmin} onChange={e=>setAck(e.target.checked)}/>I acknowledge external processing of this sanitized evidence.</label><button className="button primary" disabled={!canAdmin||!ack||!target||busy||!sourceAllowed||!assessment.evidence_digest} onClick={evaluate}><BrainCircuit size={16}/>{busy?'Requesting advisory…':result?'Read cached advisory':'Request AI advisory'}</button>{!canAdmin&&<p className="inline-help">A workspace administrator can request AI inference.</p>}<p className="inline-help">Repeated submissions for this target reuse the attempt key. Pending or uncertain requests are not automatically invoked again; inference can incur provider charges.</p></>}
      {aiError&&<Notice tone="error">{aiError}</Notice>}{result&&<div className="ai-result" aria-live="polite"><span className="eyebrow">Unverified model advice{result.cached?' · saved copy':''}</span><Notice tone="warning">{result.warning}</Notice>{result.usage&&<p className="inline-help">Provider-reported usage: {result.usage.input_tokens??'Unknown'} input tokens · {result.usage.output_tokens??'Unknown'} output tokens. Billed cost is unavailable.{result.cached?' This is the original attempt’s usage; reading the cache did not invoke a model.':''}</p>}<h4>Suggested risk: {sentence(result.advice.risk_level)}</h4><p>{result.advice.summary}</p>{result.advice.pillars.map(p=><article key={p.pillar}><h4 className="capitalize">{p.pillar}</h4><p>{p.observation}</p><small>Saved check references: {p.evidence_codes.map(label).join(', ')||'None — evidence gap'}</small></article>)}<h4>Questions for independent review</h4><ul>{result.advice.review_questions.map((q,i)=><li key={i}>{q}</li>)}</ul><p className="inline-help">The guardrails above still apply regardless of model text.</p></div>}
    </section>
  </div>;
}
