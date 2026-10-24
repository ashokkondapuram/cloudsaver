'use client';
import {useEffect,useRef,useState} from 'react';
import {Database,ShieldCheck} from 'lucide-react';
import {api} from '../../lib/api';
import {dateTime} from '../../lib/finops';
import {useWorkspace} from '../WorkspaceProvider';
import {EmptyState,Loading,Notice,SectionTitle} from '../ui/shared';

type Processor={target_id:string;azure_resource_id:string;endpoint_url:string;deployment_name:string;purposes:string[];review_reference:string;review_expires_at:string};
type Record={attempt_id:string;purpose:string;expires_at:string;erased_at:string|null};
type View={policy:{status:string;policy_revision:number|null;environment_id:string|null;response_retention_days:number;processors:Processor[];provider_controls?:string};
  events:{id:string;purpose:string;decision:string;reason:string;created_at:string;actor_reference:string}[];
  records:Record[];active_holds:{attempt_id:string;hold_until:string;review_reference:string}[];counts:{[key:string]:number}};
const label=(value:string)=>value.replaceAll('_',' ').toLowerCase();

export function DataGovernanceWorkspace(){
  const {token,canAdmin}=useWorkspace();const [view,setView]=useState<View|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [selection,setSelection]=useState<{record:Record;decision:'erase'|'hold'}|null>(null),[reference,setReference]=useState(''),[until,setUntil]=useState(''),[ack,setAck]=useState(false);
  const action=useRef<AbortController|null>(null);
  useEffect(()=>{
    const request=new AbortController();setView(null);setSelection(null);setReference('');setAck(false);setError('');setBusy(false);
    api<View>('/ai/governance',token,{signal:request.signal}).then(v=>{if(!request.signal.aborted)setView(v);}).catch(cause=>{if(!request.signal.aborted)setError((cause as Error).message);});
    return()=>{request.abort();action.current?.abort();};
  },[token]);
  function choose(record:Record,decision:'erase'|'hold'){setSelection({record,decision});setReference('');setUntil('');setAck(false);setError('');}
  async function submit(event:React.FormEvent){
    event.preventDefault();if(!selection)return;setBusy(true);setError('');const request=new AbortController();action.current=request;
    try{
      await api('/ai/governance/records/'+selection.record.attempt_id+'/'+selection.decision,token,{signal:request.signal,body:{review_reference:reference,...(selection.decision==='hold'?{hold_until:new Date(until).toISOString()}:{})}});
      const updated=await api<View>('/ai/governance',token,{signal:request.signal});if(!request.signal.aborted){setView(updated);setSelection(null);}
    }catch(cause){if(!request.signal.aborted)setError((cause as Error).message);}finally{if(!request.signal.aborted)setBusy(false);}
  }
  return <><SectionTitle eyebrow="DATA OWNERSHIP & PURPOSE" title="AI data governance">Control which facts AI can process, where approved processors belong, and how long model content remains available.</SectionTitle>
    {error&&<Notice tone="error">{error}</Notice>}
    {!view?!error&&<Loading label="Loading data governance…"/>:<>
      <Notice tone={view.policy.status==='enforced'?'info':'warning'}>{view.policy.status==='enforced'?`Data-use policy enforced for ${view.policy.environment_id}.`:'AI processing is blocked until the owning environment and reviewed processors are registered.'} Workspace consent and task approval cannot override the data-use policy.</Notice>
      <section className="panel" style={{padding:24,margin:'20px 0'}}><h2><ShieldCheck size={20}/> Data-use boundaries</h2><dl className="settings-key-values" style={{padding:0}}>{[
        ['Permitted model data','Allowlisted operational facts and filtered instructions'],['Raw inventory, tags and credentials','Excluded from model context'],
        ['Training and cross-tenant reuse','Prohibited'],['Generic HTTP action transfers','Prohibited'],
        ['New model-content retention',`${view.policy.response_retention_days} days`],['Policy revision',String(view.policy.policy_revision??'Unavailable')],
      ].map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl><p className="inline-help">Identifier filtering reduces exposure; it is not proof of anonymization. Do not enter secrets or sensitive business text in free-text requests. Source inventory stays in its existing tenant-owned storage.</p></section>
      <section className="panel"><div className="grid-heading"><div><h2>Registered data processors</h2><p>Platform operators register an exact workspace, Azure account, endpoint, deployment, purpose and review expiry.</p></div></div>
        {!view.policy.processors.length?<EmptyState icon={ShieldCheck} title="No processing approvals">New model calls remain blocked. Ask the platform data owner to register a reviewed processor.</EmptyState>:<div className="grid-scroll" tabIndex={0} aria-label="Approved data processors"><table className="data-table"><thead><tr><th>Processor</th><th>Permitted purposes</th><th>Review</th></tr></thead><tbody>{view.policy.processors.map(p=><tr key={p.target_id}><td>{p.target_id}<small>{p.deployment_name}</small><small style={{overflowWrap:'anywhere'}}>{p.endpoint_url}</small></td><td>{p.purposes.map(label).join(' · ')}</td><td>{p.review_reference}<small>{dateTime(p.review_expires_at)}</small></td></tr>)}</tbody></table></div>}
        <p className="settings-notice">Provider retention, training and processing-location controls require a documented owner review. Registration records that review; CloudSaver does not independently certify the provider’s internal handling.</p>
      </section>
      <section className="panel" style={{marginTop:20}}><div className="grid-heading"><div><h2>Content retention & privacy requests</h2><p>Erase model responses and follow-up text while keeping usage counters and request replay fences.</p></div><Database size={20}/></div>
        {!view.records.length?<EmptyState icon={Database} title="No AI content records">Governed inference creates a tenant-owned retention record.</EmptyState>:<div className="grid-scroll" tabIndex={0} aria-label="AI content retention"><table className="data-table"><thead><tr><th>Attempt / purpose</th><th>Expiry / erasure</th><th>Legal preservation</th>{canAdmin&&<th>Privacy action</th>}</tr></thead><tbody>{view.records.map(r=>{
          const holds=view.active_holds.filter(h=>h.attempt_id===r.attempt_id);return <tr key={r.attempt_id}><td><code>{r.attempt_id}</code><small>{label(r.purpose)}</small></td><td>{r.erased_at?'Content erased':dateTime(r.expires_at)}{r.erased_at&&<small>{dateTime(r.erased_at)}</small>}</td><td>{holds.length?holds.map(h=><span key={h.hold_until}>{h.review_reference}<small>Until {dateTime(h.hold_until)}</small></span>):'No active hold'}</td>{canAdmin&&<td><button className="button secondary small" disabled={busy||!!r.erased_at||!!holds.length} onClick={()=>choose(r,'erase')}>Erase AI content</button> <button className="button secondary small" disabled={busy||!!r.erased_at} onClick={()=>choose(r,'hold')}>Place legal hold</button></td>}</tr>;
        })}</tbody></table></div>}
        {selection&&<form onSubmit={submit} className="drawer-section" style={{padding:24}} aria-label="Privacy action review"><h3>{selection.decision==='erase'?'Erase AI content':'Preserve AI content for legal review'}</h3><p style={{overflowWrap:'anywhere'}}>{selection.record.attempt_id}</p><label>Internal review reference<input required pattern="[A-Za-z0-9][A-Za-z0-9._/-]{2,119}" value={reference} onChange={e=>setReference(e.target.value)} placeholder="PRIVACY-42"/></label>
          {selection.decision==='hold'&&<label>Hold expiry (within 30 days)<input type="datetime-local" required value={until} onChange={e=>setUntil(e.target.value)}/></label>}
          <label className="checkbox-row"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/>I am authorized to make this privacy request. Usage and audit metadata remain; erasure cannot restore content or undo a provider request.</label><button className="button primary" disabled={busy||!ack}>{busy?'Recording…':selection.decision==='erase'?'Confirm content erasure':'Confirm legal hold'}</button> <button className="button secondary" type="button" disabled={busy} onClick={()=>setSelection(null)}>Cancel</button>
        </form>}
        <p className="settings-notice">A legal hold preserves stored evidence and blocks erasure; it does not authorize new model use. Backup and provider-side deletion follow their separately reviewed retention processes.</p>
      </section>
      <section className="panel" style={{marginTop:20}}><div className="grid-heading"><div><h2>Data-use audit</h2><p>{view.counts.allowed||0} approvals · {view.counts.blocked||0} blocked requests · {view.counts.erased||0} content erasures</p></div></div>
        {!view.events.length?<p className="settings-notice">No data-use decisions recorded yet.</p>:<div className="grid-scroll" tabIndex={0} aria-label="Data-use audit"><table className="data-table"><thead><tr><th>Decision</th><th>Purpose / reason</th><th>Recorded</th></tr></thead><tbody>{view.events.map(e=><tr key={e.id}><td>{label(e.decision)}</td><td>{label(e.purpose)}<small>{label(e.reason)}</small></td><td>{dateTime(e.created_at)}</td></tr>)}</tbody></table></div>}
      </section>
    </>}
  </>;
}
