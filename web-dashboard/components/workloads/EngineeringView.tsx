'use client';
import Link from 'next/link';
import {useEffect,useRef,useState,type FormEvent,type ReactNode} from 'react';
import {api,ApiError} from '../../lib/api';
import {dateTime} from '../../lib/finops';
import {sentence} from '../../lib/resources';
import {useWorkspace} from '../WorkspaceProvider';
import {Loading,Notice} from '../ui/shared';
import css from './Engineering.module.css';

type Page<T>={items:T[];next_cursor:string|null};
type Workload={id:string;name:string;environment:string;owner:string;team:string;scope_id:string;version:number;requirements:Record<string,string|null>};
type Member={id:string;resource_name:string;resource_id:string;resource_type:string;resource_key:string;scan_id:string};
type Check={code:string;status:string;reason:string;coverage_ratio?:number;p95?:number|null};
type Version={id:string;plan_id:string;version:number;identity_digest:string;context_changed:boolean;parameters:{objective:string;action:string;candidate_sku:string|null;member_id:string;scan_id:string;readiness:{decision:string;evaluated_at:string;checks:Check[]}}};
type Plan={id:string;latest:Version};
type Event={id:string;kind:string;created_at:string};
type Capabilities={stage:string;scopes:{scope_id:string}[];actions:{id:string;mode:string}[];acceptance_required:string[]};
type Resource={resource_key:string;resource_name:string;resource_type:string;scope_id:string};

function useRead<T>(path:string|null,token:string,revision=0){
  const [value,setValue]=useState<T|null>(null),[error,setError]=useState('');
  useEffect(()=>{const controller=new AbortController();setValue(null);setError('');
    if(path)api<T>(path,token,{signal:controller.signal}).then(v=>{if(!controller.signal.aborted)setValue(v);}).catch(e=>{if(!controller.signal.aborted)setError(e.message);});
    return()=>controller.abort();
  },[path,token,revision]);
  return {value,error};
}

function Pages({cursor,next,onChange,label}:{cursor:string|null;next?:string|null;onChange:(s:string|null)=>void;label:string}){
  return <nav className={css.pager} aria-label={label}><button className="button secondary" disabled={!cursor} onClick={()=>onChange(null)}>First page</button><button className="button secondary" disabled={!next} onClick={()=>onChange(next!)}>Next page</button></nav>;
}
const query=(cursor:string|null)=>'?limit=20'+(cursor?'&cursor='+encodeURIComponent(cursor):'');

function Command({token,path,version,method='POST',label,children,body,done}:{token:string;path:string;version?:number;method?:'POST'|'PATCH';label:string;children:ReactNode;body:(data:FormData)=>unknown;done:()=>void}){
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[uncertain,setUncertain]=useState(false);
  const pending=useRef<{body:unknown;key:string}|null>(null);
  const form=useRef<HTMLFormElement>(null);
  async function submit(event?:FormEvent){
    event?.preventDefault();if(busy)return;
    if(!pending.current)pending.current={body:body(new FormData(form.current!)),key:crypto.randomUUID()};
    setBusy(true);setError('');
    try{await api(path,token,{body:pending.current.body,idempotencyKey:pending.current.key,version,method});pending.current=null;setUncertain(false);done();}
    catch(e){const unknown=e instanceof ApiError&&e.uncertain;setUncertain(unknown);setError(e instanceof Error?e.message:'Unable to save');if(!unknown)pending.current=null;}
    finally{setBusy(false);}
  }
  return <form ref={form} className={css.form} onSubmit={submit}>
    <fieldset className={css.fields} disabled={busy||uncertain}>{children}</fieldset>
    {error&&<Notice tone="error">{error}{uncertain&&' Retry the same request below to recover its result without creating a second record.'}</Notice>}
    <div className={css.actions}>{uncertain?<button type="button" className="button primary" disabled={busy} onClick={()=>submit()}>Retry same request</button>:<button className="button primary" disabled={busy} type="submit">{busy?'Saving…':label}</button>}</div>
  </form>;
}

function WorkloadFields({workload,scopes=[]}:{workload?:Workload;scopes?:{scope_id:string}[]}){
  return <>
    <label>Name<input required name="name" maxLength={80} defaultValue={workload?.name}/></label>
    <label>Environment<input required name="environment" maxLength={40} defaultValue={workload?.environment||'nonproduction'}/></label>
    <label>Owner<input required name="owner" maxLength={80} defaultValue={workload?.owner}/></label>
    <label>Team<input required name="team" maxLength={80} defaultValue={workload?.team}/></label>
    {!workload&&<label className={css.wide}>Authorized Azure subscription<select required name="scope_id" defaultValue=""><option value="" disabled>Select a subscription</option>{scopes.map(s=><option key={s.scope_id}>{s.scope_id}</option>)}</select></label>}
    {(['slo_reference','peak_reference','recovery_reference'] as const).map((field,i)=><label key={field} className={css.wide}>{['Application SLO reference','Peak demand reference','Recovery requirements reference'][i]}<input name={field} maxLength={200} minLength={3} defaultValue={workload?.requirements[field]||''}/></label>)}
    <p className={css.wide+' '+css.muted}>Use non-sensitive reference names. These declarations identify evidence to collect; they do not confirm that a control passed.</p>
  </>;
}
function workloadBody(data:FormData){return Object.fromEntries([...data.entries()].map(([k,v])=>[k,k.endsWith('_reference')&&!v?null:v]));}

function History({token,planId}:{token:string;planId:string}){
  const [cursor,setCursor]=useState<string|null>(null);
  const {value,error}=useRead<Page<Version>>(`/engineering/plans/${planId}/versions${query(cursor)}`,token);
  return <>{error?<Notice tone="error">{error}</Notice>:!value?<Loading label="Loading plan history…"/>:<><ol>{[...value.items].sort((a,b)=>b.version-a.version).map(v=><li key={v.id}>Version {v.version}: {v.parameters.candidate_sku||'Disk review'} · {dateTime(v.parameters.readiness.evaluated_at)}<p className={css.wrap}>Manifest: {v.identity_digest}</p></li>)}</ol><Pages cursor={cursor} next={value.next_cursor} onChange={setCursor} label="Plan history pages"/></>}</>;
}

function PlanCard({plan,token,w,canAdmin,scanId,done}:{plan:Plan;token:string;w:Workload;canAdmin:boolean;scanId?:string;done:()=>void}){
  const [history,setHistory]=useState(false);
  const v=plan.latest,p=v.parameters,r=p.readiness;
  return <article className={css.card}>
    <h3>{p.objective}</h3><p>{sentence(r.decision)} · Version {v.version} · {p.candidate_sku||'Disk review'}</p>
    {v.context_changed&&<Notice>The workload changed after this review. Create a new version to assess the current declarations.</Notice>}
    <p className={css.muted}>Assessed {dateTime(r.evaluated_at)}. Saved results describe that evidence window. Reassess with a recent observation before planning a change.</p>
    <details className={css.details}><summary>Evidence checks ({r.checks.length})</summary><ul className={css.checks}>{r.checks.map(check=><li key={check.code}><span className={css.status}>{sentence(check.status)}</span><div><strong>{sentence(check.code)}</strong><p>{check.reason}</p>{check.coverage_ratio!==undefined&&<p>Sample coverage: {(check.coverage_ratio*100).toFixed(1)}%{check.p95!=null?` · p95: ${check.p95}%`:''}</p>}</div></li>)}</ul></details>
    <p className={css.wrap+' '+css.muted}>Manifest: {v.identity_digest}</p>
    <p className={css.muted}>Estimated opportunity, validated run rate and reconciled benefit are unavailable until their supporting evidence is accepted.</p>
    <button className="button secondary" aria-expanded={history} onClick={()=>setHistory(!history)}>{history?'Hide version history':'View version history'}</button>
    {history&&<History token={token} planId={plan.id}/>}
    {canAdmin&&<details className={css.details}><summary>Create a new review version</summary><Command token={token} path={`/engineering/workloads/${w.id}/plans/${plan.id}/versions`} version={w.version} label="Save new version" done={done} body={data=>({member_id:p.member_id,objective:String(data.get('objective')),action:p.action,candidate_sku:p.action==='azure.vm.rightsize'?String(data.get('candidate_sku')):null,parent_version:v.version,scan_id:data.get('latest')?scanId:p.scan_id})}>
      <label className={css.wide}>Objective<textarea name="objective" required minLength={10} maxLength={500} defaultValue={p.objective}/></label>
      {p.action==='azure.vm.rightsize'&&<label>Candidate SKU<input name="candidate_sku" required defaultValue={p.candidate_sku||''} maxLength={80}/></label>}
      {scanId&&<label className={css.wide}><span><input type="checkbox" name="latest"/> Use the currently selected saved observation</span></label>}
    </Command></details>}
  </article>;
}

function Detail({id,token,revision,refresh,canAdmin,scanId}:{id:string;token:string;revision:number;refresh:()=>void;canAdmin:boolean;scanId?:string}){
  const [memberCursor,setMemberCursor]=useState<string|null>(null),[planCursor,setPlanCursor]=useState<string|null>(null),[eventCursor,setEventCursor]=useState<string|null>(null);
  const [offset,setOffset]=useState(0),[selected,setSelected]=useState('');
  const w=useRead<Workload>(`/engineering/workloads/${id}`,token,revision);
  const members=useRead<Page<Member>>(`/engineering/workloads/${id}/members${query(memberCursor)}`,token,revision);
  const plans=useRead<Page<Plan>>(`/engineering/workloads/${id}/plans${query(planCursor)}`,token,revision);
  const events=useRead<Page<Event>>(`/engineering/workloads/${id}/events${query(eventCursor)}`,token,revision);
  const resources=useRead<{items:Resource[];total:number}>(canAdmin&&scanId?`/scans/${scanId}/resources?provider=azure&limit=20&offset=${offset}`:null,token);
  const refreshDetail=()=>{setMemberCursor(null);setPlanCursor(null);setEventCursor(null);setSelected('');refresh();};
  if(w.error)return <Notice tone="error">{w.error}</Notice>;
  if(!w.value)return <Loading label="Loading workload…"/>;
  const workload=w.value;
  const member=members.value?.items.find(m=>m.id===selected);
  const action=member?.resource_type.toLowerCase()==='microsoft.compute/disks'?'azure.disk.review':'azure.vm.rightsize';
  return <div className={css.stack}>
    <section className={'panel '+css.panel}><h2>{workload.name}</h2><p>{workload.environment} · Owner: {workload.owner} · Team: {workload.team}</p><p className={css.wrap+' '+css.muted}>{workload.scope_id} · Workload version {workload.version}</p>
      {canAdmin&&<details className={css.details}><summary>Edit ownership and evidence references</summary><Command key={workload.version} token={token} path={`/engineering/workloads/${id}`} version={workload.version} method="PATCH" label="Save workload" body={workloadBody} done={refreshDetail}><WorkloadFields workload={workload}/></Command></details>}
    </section>
    <section className={'panel '+css.panel}><h2>Resources and observations</h2>
      {members.error?<Notice tone="error">{members.error}</Notice>:!members.value?<Loading label="Loading workload resources…"/>:<><ul className={css.list}>{members.value.items.map(m=><li key={m.id} className={css.wrap}>{m.resource_name} · <Link href={`/resources?resource=${m.resource_key}`}>Inspect evidence</Link><p className={css.muted}>Observation {m.scan_id}</p></li>)}</ul>{!members.value.items.length&&<p className={css.empty}>Attach a resource from a saved observation to start a review.</p>}<Pages label="Membership pages" cursor={memberCursor} next={members.value.next_cursor} onChange={setMemberCursor}/></>}
      {canAdmin&&(!scanId?<Notice>Select a completed live observation to add resources.</Notice>:<details className={css.details}><summary>Attach resource from selected observation</summary>{resources.error?<Notice tone="error">{resources.error}</Notice>:!resources.value?<Loading label="Loading saved resources…"/>:<>
        <Command token={token} key={`${revision}:${scanId}:${offset}`} path={`/engineering/workloads/${id}/members`} version={workload.version} label="Attach resource" done={refreshDetail} body={data=>({scan_id:scanId,resource_key:data.get('resource_key')})}>
          <label className={css.wide}>Resource<select name="resource_key" required defaultValue=""><option value="" disabled>Select a resource</option>{resources.value.items.filter(r=>r.scope_id===workload.scope_id).map(r=><option value={r.resource_key} key={r.resource_key}>{r.resource_name} · {r.resource_type}</option>)}</select></label>
        </Command><nav className={css.pager} aria-label="Observation resource pages"><button className="button secondary" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-20))}>Previous resources</button><button className="button secondary" disabled={offset+20>=resources.value.total} onClick={()=>setOffset(offset+20)}>Next resources</button></nav>
      </>}</details>)}
    </section>
    <section className={'panel '+css.panel}><h2>Improvement plans</h2><p className={css.muted}>Create review alternatives for Azure VMs and managed disks. Every version retains its evidence and policy digests. Execution requires the remaining acceptance gates.</p>
      {canAdmin&&!!members.value?.items.length&&<details className={css.details}><summary>Prepare an improvement plan</summary>
        <label>Workload resource<select value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Select a resource</option>{members.value.items.filter(m=>['microsoft.compute/virtualmachines','microsoft.compute/disks'].includes(m.resource_type.toLowerCase())).map(m=><option key={m.id} value={m.id}>{m.resource_name}</option>)}</select></label>
        {member&&<Command key={selected+':'+revision} token={token} path={`/engineering/workloads/${id}/plans`} version={workload.version} label="Save evidence review" done={refreshDetail} body={data=>({member_id:selected,objective:data.get('objective'),action,candidate_sku:action==='azure.vm.rightsize'?data.get('candidate_sku'):null})}>
          <label className={css.wide}>Objective<textarea name="objective" required minLength={10} maxLength={500}/></label>
          {action==='azure.vm.rightsize'&&<label className={css.wide}>Candidate SKU<input name="candidate_sku" required maxLength={80} placeholder="Standard_D2s_v5"/><span className={css.muted}>A candidate for investigation; compatibility has not been verified.</span></label>}
        </Command>}
      </details>}
      {plans.error?<Notice tone="error">{plans.error}</Notice>:!plans.value?<Loading label="Loading improvement plans…"/>:<div className={css.stack}>{!plans.value.items.length&&<p className={css.empty}>No saved improvement plans yet.</p>}{plans.value.items.map(p=><PlanCard key={p.latest.id} plan={p} token={token} w={workload} canAdmin={canAdmin} scanId={scanId} done={refreshDetail}/>)}<Pages label="Improvement plan pages" cursor={planCursor} next={plans.value.next_cursor} onChange={setPlanCursor}/></div>}
    </section>
    <section className={'panel '+css.panel}><h2>Activity</h2>{events.error?<Notice tone="error">{events.error}</Notice>:!events.value?<Loading label="Loading activity…"/>:<><ul>{events.value.items.map(e=><li key={e.id}>{sentence(e.kind.replaceAll('.','_'))} · {dateTime(e.created_at)}</li>)}</ul><Pages label="Activity pages" cursor={eventCursor} next={events.value.next_cursor} onChange={setEventCursor}/></>}</section>
  </div>;
}

export function EngineeringView(){
  const {token,workspace,canAdmin,scan}=useWorkspace();
  const [revision,setRevision]=useState(0),[cursor,setCursor]=useState<string|null>(null),[selected,setSelected]=useState('');
  const capabilities=useRead<Capabilities>('/engineering/capabilities',token,revision);
  const workloads=useRead<Page<Workload>>('/engineering/workloads'+query(cursor),token,revision);
  const [capabilityDetails,setCapabilityDetails]=useState(false);
  const refresh=()=>setRevision(n=>n+1);
  const live=scan?.status==='completed'&&scan?.data_origin!=='legacy_synthetic'&&scan?.mode!=='demo';
  if(!workspace)return <Notice>Connect a workspace to continue.</Notice>;
  return <section className={css.root} aria-label="Engineering plans">
    <div className={css.intro}><div><strong>1. Define the workload</strong><p>Assign an owner and explain its service, peak demand and recovery needs.</p></div><div><strong>2. Review the evidence</strong><p>Attach saved observations and compare a candidate against the evidence requirements.</p></div><div><strong>3. Prepare the change</strong><p>Resolve blockers before a reviewed Terraform change. Track verified results in <Link href="/outcomes">Outcomes</Link>.</p></div></div>
    <div className={css.actions}><button className="button secondary" onClick={refresh}>Refresh engineering records</button><button className="button secondary" aria-expanded={capabilityDetails} onClick={()=>setCapabilityDetails(!capabilityDetails)}>Pilot capabilities</button></div>
    {capabilities.error&&<Notice tone="error">{capabilities.error}</Notice>}
    {capabilityDetails&&capabilities.value&&<section className={'panel '+css.panel}><h2>Azure pilot capabilities</h2><p>Workload declarations and evidence reviews are available. Infrastructure execution is disabled.</p><ul>{capabilities.value.actions.map(a=><li key={a.id}>{sentence(a.id)} · {sentence(a.mode)}</li>)}</ul><h3>Required before live execution</h3><ul>{capabilities.value.acceptance_required.map(a=><li key={a}>{sentence(a)}</li>)}</ul></section>}
    {canAdmin&&!!capabilities.value?.scopes.length&&<details className={'panel '+css.panel+' '+css.details}><summary>Create a workload</summary><Command key={revision} token={token} path="/engineering/workloads" label="Create workload" body={workloadBody} done={()=>{setCursor(null);refresh();}}><WorkloadFields scopes={capabilities.value.scopes}/></Command></details>}
    {capabilities.value&&!capabilities.value.scopes.length&&<Notice>No authorized Azure subscription is available. Review cloud access in Settings.</Notice>}
    {!canAdmin&&<Notice>You can inspect engineering records. A workspace administrator can change workloads and prepare plans.</Notice>}
    <div className={css.layout}><section className={'panel '+css.panel}><h2>Workloads</h2>{workloads.error?<Notice tone="error">{workloads.error}</Notice>:!workloads.value?<Loading label="Loading engineering workloads…"/>:<><ul className={css.list}>{workloads.value.items.map(w=><li key={w.id}><button className="button secondary" aria-pressed={selected===w.id} onClick={()=>setSelected(w.id)}>{w.name} · {w.environment}</button></li>)}</ul>{!workloads.value.items.length&&<p className={css.empty}>No workloads on this page.</p>}<Pages label="Engineering workload pages" cursor={cursor} next={workloads.value.next_cursor} onChange={setCursor}/></>}</section>
      {selected?<Detail key={selected+':'+(scan?.scan_id||'')} id={selected} token={token} revision={revision} refresh={refresh} canAdmin={canAdmin} scanId={live?scan?.scan_id:undefined}/>:<section className={'panel '+css.panel}><h2>Select a workload</h2><p className={css.empty}>Open a workload to inspect its resources, prepare a versioned plan and review activity.</p></section>}
    </div>
  </section>;
}
