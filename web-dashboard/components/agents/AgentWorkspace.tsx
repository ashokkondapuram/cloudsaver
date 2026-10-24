'use client';

import {useCallback,useEffect,useRef,useState} from 'react';
import {Bot,Check,Clock,FileCode2,RefreshCw,ShieldCheck} from 'lucide-react';
import {api} from '../../lib/api';
import {dateTime} from '../../lib/finops';
import {useWorkspace} from '../WorkspaceProvider';
import {EmptyState,Notice,SectionTitle} from '../ui/shared';
import './agents.css';

type Connector={id:string;provider:string;scope_id:string;kind:string;operations:string[];endpoint:string|null};
type Step={connector_id:string;operation:string;arguments:Record<string,unknown>;purpose:string;verification:string;rollback:string};
type Task={id:string;resource_id:string;state:string;version:number;created_at:string;payload:{intent:string;plan_hash:string|null;
  data_erased?:boolean;data_content_expired?:boolean;
  plan:{summary:string;steps:Step[]}|null;approval:{expires_at:string;actor:string}|null;
  connector_bindings?:Connector[];steps:{state:string;result?:{code:string}}[]};code?:string;
  events?:{version:number;action:string;created_at:string}[]};
type Resource={resource_id:string;resource_name:string;cloud_provider:string;scope_id?:string;subscription_id?:string};
const labels=(s:string)=>s.replaceAll('_',' ');
const active=new Set(['draft_queued','drafting','approved','running','cancel_requested']);

export function AgentWorkspace(){
  const {token,scan,canAdmin,workspace}=useWorkspace();
  const canApprove=canAdmin&&!workspace?.key_id&&workspace?.subject_type==='user';
  const [catalog,setCatalog]=useState<{enabled:boolean;connectors:Connector[]}|null>(null),[tasks,setTasks]=useState<Task[]>([]);
  const [resources,setResources]=useState<Resource[]>([]),[targets,setTargets]=useState<{target_id:string;provider:string}[]>([]);
  const [resource,setResource]=useState(''),[target,setTarget]=useState(''),[intent,setIntent]=useState(''),[selectedConnectors,setSelectedConnectors]=useState<string[]>([]);
  const [selected,setSelected]=useState<Task|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[confirmed,setConfirmed]=useState(false),[minutes,setMinutes]=useState(15);
  const pending=useRef<AbortController|null>(null),detail=useRef<AbortController|null>(null),mutation=useRef<AbortController|null>(null);
  const selection=useRef<string|null>(null);selection.current=selected?.id||null;
  const chosen=resources.find(r=>r.resource_id===resource);
  const connectors=(catalog?.connectors||[]).filter(c=>c.provider===chosen?.cloud_provider&&c.scope_id===(chosen.scope_id||chosen.subscription_id));
  const availableTargets=targets.filter(t=>t.provider===chosen?.cloud_provider);
  const refresh=useCallback(async(signal?:AbortSignal)=>{
    const [c,t,a]=await Promise.all([api<{enabled:boolean;connectors:Connector[]}>('/agents/catalog',token,{signal}),api<{items:Task[]}>('/agents/tasks',token,{signal}),api<{targets:{target_id:string;provider:string}[]}>('/ai/targets',token,{signal})]);
    if(!signal?.aborted){setCatalog(c);setTasks(t.items);setTargets(a.targets);}
  },[token]);
  useEffect(()=>{
    const request=new AbortController();pending.current=request;setCatalog(null);setTasks([]);setSelected(null);setError('');setIntent('');setConfirmed(false);setBusy(false);
    refresh(request.signal).catch(cause=>{if(!request.signal.aborted)setError((cause as Error).message);});
    return()=>{request.abort();detail.current?.abort();mutation.current?.abort();};
  },[refresh]);
  useEffect(()=>{
    const request=new AbortController();setResources([]);setResource('');setSelectedConnectors([]);setTarget('');
    if(scan?.status==='completed'&&scan.mode!=='demo')api<{items:{resource_id:string;resource_name:string;provider:string;scope_id:string}[]}>(`/scans/${scan.scan_id}/resources?limit=1000`,token,{signal:request.signal}).then(r=>{if(!request.signal.aborted){const rows=r.items.map(v=>({...v,cloud_provider:v.provider}));setResources(rows);const prefill=new URLSearchParams(window.location.search).get('resource');if(prefill&&rows.some(v=>v.resource_id===prefill))setResource(prefill);}}).catch(cause=>{if(!request.signal.aborted)setError((cause as Error).message);});
    return()=>request.abort();
  },[scan?.scan_id,scan?.status,scan?.mode,token]);
  useEffect(()=>{
    if(!tasks.some(t=>active.has(t.state)))return;
    const request=new AbortController();let fetching=false;
    const timer=setInterval(async()=>{
      if(fetching)return;fetching=true;
      try{
        const id=selection.current;
        const [value,updated]=await Promise.all([api<{items:Task[]}>('/agents/tasks',token,{signal:request.signal}),id?api<Task>('/agents/tasks/'+id,token,{signal:request.signal}):Promise.resolve(null)]);
        if(request.signal.aborted)return;setTasks(value.items);
        if(updated&&selection.current===id)setSelected(updated);
      }catch(cause){if(!request.signal.aborted)setError((cause as Error).message);}finally{fetching=false;}
    },5000);
    return()=>{request.abort();clearInterval(timer);};
  },[tasks.some(t=>active.has(t.state)),token]);
  useEffect(()=>{setConfirmed(false);},[selected?.id,selected?.version]);
  async function open(task:Task){
    detail.current?.abort();const request=new AbortController();detail.current=request;setSelected(task);setConfirmed(false);setError('');
    try{const value=await api<Task>('/agents/tasks/'+task.id,token,{signal:request.signal});if(!request.signal.aborted)setSelected(value);}
    catch(cause){if(!request.signal.aborted)setError((cause as Error).message);}
  }
  async function submit(event:React.FormEvent){
    event.preventDefault();if(!scan||!chosen)return;setBusy(true);setError('');const request=new AbortController();mutation.current=request;
    try{const task=await api<Task>('/agents/tasks',token,{signal:request.signal,body:{scan_id:scan.scan_id,resource_id:resource,request_key:crypto.randomUUID(),intent,target_id:target,connector_ids:selectedConnectors}});
      if(!request.signal.aborted){setIntent('');setTasks(old=>[task,...old]);setSelected(task);}}
    catch(cause){if(!request.signal.aborted)setError((cause as Error).message);}finally{if(!request.signal.aborted)setBusy(false);}
  }
  async function review(decision:string){
    if(!selected)return;setBusy(true);setError('');const request=new AbortController();mutation.current=request;
    try{const value=await api<Task>('/agents/tasks/'+selected.id+'/review',token,{signal:request.signal,body:{version:selected.version,decision,plan_hash:selected.payload.plan_hash,expires_in_minutes:minutes}});
      if(!request.signal.aborted){setTasks(old=>old.map(t=>t.id===value.id?value:t));if(selection.current===value.id)setSelected(value);setConfirmed(false);}}
    catch(cause){if(!request.signal.aborted)setError((cause as Error).message);}finally{if(!request.signal.aborted)setBusy(false);}
  }
  return <><SectionTitle eyebrow="HUMAN-GOVERNED EXECUTION" title="Agent workspace">Turn a resource task into an AI-drafted plan, review every connector call, and follow the worker’s execution.</SectionTitle>
    {error&&<Notice tone="error">{error}</Notice>}
    {catalog&&!catalog.enabled&&<Notice tone="warning">Agent execution is disabled. Your platform operator must configure worker and connector grants before enabling it.</Notice>}
    <div className="agent-process" aria-label="Agent task lifecycle">{[[Bot,'1. AI drafts'],[FileCode2,'2. You review'],[ShieldCheck,'3. You approve'],[Check,'4. Worker executes']].map(([Icon,label])=>{const I=Icon as typeof Bot;return <span key={String(label)}><I size={18}/>{String(label)}</span>;})}</div>
    <div className="agent-columns"><section className="panel agent-compose"><h2>Assign a resource task</h2><p>Choose the exact resource and connector permissions. Explicit instructions go to your approved AI Foundry model. Do not include credentials or personal information.</p>
      {!canAdmin?<Notice tone="info">A workspace administrator can assign and approve tasks. You can inspect the task history below.</Notice>:<form onSubmit={submit}>
        <label>Resource from selected scan<select required value={resource} onChange={e=>{setResource(e.target.value);setSelectedConnectors([]);setTarget('');}}><option value="">Choose a resource</option>{resources.map(r=><option key={r.resource_id} value={r.resource_id}>{r.resource_name} · {r.cloud_provider}</option>)}</select></label>
        {!resources.length&&<p className="inline-help">Select a recent completed live scan to assign a task.</p>}
        <label>Approved planning model<select required value={target} onChange={e=>setTarget(e.target.value)}><option value="">Choose a model</option>{availableTargets.map(t=><option key={t.target_id}>{t.target_id}</option>)}</select></label>
        {chosen&&!availableTargets.length&&<p className="inline-help">Configure an approved same-cloud model in Settings → AI & data governance.</p>}
        <fieldset><legend>Connector permissions</legend>{connectors.length?connectors.map(c=><label className="agent-check" key={c.id}><input type="checkbox" checked={selectedConnectors.includes(c.id)} onChange={e=>setSelectedConnectors(old=>e.target.checked?[...old,c.id]:old.filter(id=>id!==c.id))}/><span>{c.id}<small>{c.operations.join(' · ')}{c.endpoint&&<><br/>{c.endpoint}</>}</small></span></label>):<p className="inline-help">No connector grants match this resource.</p>}</fieldset>
        <label>Task instruction<textarea rows={4} minLength={5} maxLength={1500} required value={intent} onChange={e=>setIntent(e.target.value)} placeholder="Inspect the tags, then set CostCenter to FINOPS-42."/></label>
        <button className="button primary" disabled={busy||!catalog?.enabled||!selectedConnectors.length||!target||!resource} type="submit"><Bot size={16}/>{busy?'Submitting…':'Request AI execution plan'}</button>
      </form>}
    </section><section className="panel agent-queue"><div className="grid-heading"><div><h2>Task queue</h2><p>Active assignments refresh every five seconds.</p></div><button className="icon-button" aria-label="Refresh agent tasks" onClick={()=>refresh(pending.current?.signal).catch(cause=>setError((cause as Error).message))}><RefreshCw size={18}/></button></div>
      {!tasks.length?<EmptyState icon={Bot} title="No agent tasks yet">Assign a task to start a reviewable plan.</EmptyState>:<ul>{tasks.map(t=><li key={t.id}><button aria-pressed={selected?.id===t.id} onClick={()=>open(t)}><span>{t.payload.intent}<small>{dateTime(t.created_at)}</small></span><span className="status-tag">{labels(t.state)}</span></button></li>)}</ul>}
    </section></div>
    {selected&&<section className="panel agent-review" aria-label="Agent plan review"><div className="grid-heading"><div><h2>Plan & execution review</h2><p>{selected.id} · version {selected.version} · {labels(selected.state)}</p></div><span className="status-tag">{labels(selected.state)}</span></div><div className="agent-review-body">
      <p className="agent-resource">{selected.resource_id}</p><p>{selected.payload.intent}</p>
      {!selected.payload.plan?<Notice tone="info">{selected.payload.data_erased||selected.payload.data_content_expired?'AI task content is unavailable under the data-retention policy. Audit hashes and execution outcomes remain; expired instructions cannot be replayed.':selected.state==='failed'?'Planning stopped. Review AI Foundry policy, worker health and token budgets before requesting another draft.':'The gateway is waiting for a worker to draft the plan. No cloud action is approved.'}</Notice>:<>
        <h3>{selected.payload.plan.summary}</h3><ol className="agent-steps">{selected.payload.plan.steps.map((s,i)=><li key={i}><div><strong>{s.operation}</strong> <span className="status-tag">{labels(selected.payload.steps[i]?.state||'pending')}</span></div><p>{s.purpose}</p><p><strong>Connector:</strong> {s.connector_id}</p><pre>{JSON.stringify(s.arguments,null,2)}</pre><p><strong>Verify:</strong> {s.verification}</p><p><strong>Recovery:</strong> {s.rollback}</p>{selected.payload.steps[i]?.result&&<p>{selected.payload.steps[i].result?.code}</p>}</li>)}</ol>
        {!!selected.payload.connector_bindings?.length&&<details><summary>Approved connector destinations</summary><pre>{JSON.stringify(selected.payload.connector_bindings,null,2)}</pre></details>}
        <details><summary>TypeScript runCode program</summary><pre>{selected.code||'Open this task again to load its program.'}</pre><p className="inline-help">Connector arguments above are bound to the plan hash. The worker requests a single-use gateway permit before every call.</p></details>
        <p className="agent-hash">Plan SHA-256: {selected.payload.plan_hash}</p>
        {selected.payload.approval&&<p><Clock size={15}/> Approval expires {dateTime(selected.payload.approval.expires_at)}</p>}
      </>}
      {selected.state==='needs_reconciliation'&&<Notice tone="error">An action may have reached its connector. Inspect the provider’s audit trail and current state. This task will not replay automatically.</Notice>}
      {selected.state==='cancel_requested'&&<Notice tone="warning">Cancellation blocks subsequent steps. An in-flight connector request may still complete.</Notice>}
      {selected.state==='succeeded'&&<Notice tone="info">The connector program completed. Task success does not establish realized financial savings; use the verified savings workflow for billing proof.</Notice>}
      {canAdmin&&selected.state==='awaiting_approval'&&!canApprove&&<Notice tone="warning">Sign in with a verified human TenantAdmin session to approve this plan. API keys cannot approve execution.</Notice>}
      {canAdmin&&!selected.payload.data_erased&&!selected.payload.data_content_expired&&<div className="agent-actions">{selected.state==='awaiting_approval'&&canApprove&&<><label>Approval validity<select value={minutes} onChange={e=>setMinutes(Number(e.target.value))}>{[5,15,30,60].map(m=><option key={m} value={m}>{m} minutes</option>)}</select></label><label className="agent-check"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/><span>I reviewed the resource, connector destinations, exact arguments and recovery limits.</span></label><button className="button primary" disabled={busy||!confirmed||!catalog?.enabled} onClick={()=>review('approve')}><ShieldCheck size={16}/>Approve this plan</button><button className="button secondary" disabled={busy} onClick={()=>review('reject')}>Reject plan</button></>}
        {['awaiting_approval','rejected','failed','approval_expired'].includes(selected.state)&&<button className="button secondary" disabled={busy||!catalog?.enabled} onClick={()=>review('redraft')}>Request new AI draft</button>}
        {!['succeeded','failed','rejected','cancelled','needs_reconciliation','approval_expired'].includes(selected.state)&&<button className="button secondary" disabled={busy||selected.state==='cancel_requested'} onClick={()=>review('cancel')}>Cancel task</button>}
      </div>}
      {!!selected.events?.length&&<details><summary>Approval & execution audit</summary><ol>{selected.events.map(e=><li key={e.version}>{labels(e.action)} · {dateTime(e.created_at)} · version {e.version}</li>)}</ol></details>}
    </div></section>}
  </>;
}
