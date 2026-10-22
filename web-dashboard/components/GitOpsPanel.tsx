'use client';
import {useEffect,useRef,useState} from 'react';

async function api<T>(path:string,token:string,body?:unknown):Promise<T>{
  const response=await fetch(`/api/v1${path}`,{method:body?'POST':'GET',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,cache:'no-store'});
  const data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:`Request failed (${response.status})`);
  return data;
}
type PolicyResult={decision:string;issues:{code:string;address:string;message:string}[];resources_checked:number;cost:{status:string;monthly_increase_usd:number|null}};

export function PlanPolicyPanel({token}:{token:string}){
  const [plan,setPlan]=useState<File|null>(null),[cost,setCost]=useState<File|null>(null);
  const [result,setResult]=useState<PolicyResult|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  async function evaluate(){
    setBusy(true);setError('');setResult(null);
    try{
      if((plan?.size||0)+(cost?.size||0)>1900000)throw new Error('Combined files must be smaller than 1.9 MB.');
      if(!plan)throw new Error('Choose a Terraform plan JSON file.');
      const body={plan:JSON.parse(await plan.text()),...(cost?{infracost:JSON.parse(await cost.text())}:{})};
      setResult(await api<PolicyResult>('/policies/terraform/evaluate',token,body));
    }catch(e){setError(e instanceof Error?e.message:'Policy check failed');}finally{setBusy(false);}
  }
  return <section className="panel gitops-panel" id="policy-checks">
    <div className="section-title"><div><h2>Terraform pre-merge checks</h2><p>Check a complete saved plan for supported orphan relationships, destructive changes and operator policies.</p></div></div>
    <p>Plan JSON can contain secrets. This request sends it to your CloudSaver server for analysis; raw values are not stored or included in the result. CI must protect its policy and input provenance.</p>
    <div className="gitops-inputs">
      <label>Terraform plan JSON<input type="file" accept=".json,application/json" disabled={busy} onChange={e=>setPlan(e.target.files?.[0]||null)}/></label>
      <label>Infracost JSON (optional)<input type="file" accept=".json,application/json" disabled={busy} onChange={e=>setCost(e.target.files?.[0]||null)}/></label>
    </div>
    <div className="actions"><button className="primary" disabled={busy||!plan} onClick={()=>evaluate()}>Check plan</button></div>
    {busy&&<p role="status">Evaluating plan…</p>}{error&&<p role="alert" className="error">{error}</p>}
    {result&&<div aria-live="polite"><h3>Policy decision: {result.decision.toUpperCase()}</h3><p>{result.resources_checked} managed resources checked. Cost evidence: {result.cost.status}{result.cost.monthly_increase_usd!==null?` · estimated increase $${result.cost.monthly_increase_usd.toFixed(2)}/month`:''}. Estimates are not verified billing.</p>
      {result.issues.length?<ul>{result.issues.map((issue,i)=><li key={i}><strong>{issue.code}</strong> · <code>{issue.address}</code><p>{issue.message}</p></li>)}</ul>:<p>No configured policy violations were found. Unsupported external relationships and merge protection still need independent review.</p>}
    </div>}
  </section>;
}

type Target={target_id:string;repository:string;base_branch:string};
type Review={id:string;repository:string;branch:string;status:string;attempts:number;result:{pr_url:string;draft:boolean;state:string}|null};
type Preview={review_id:string;fingerprint:string;files:Record<string,string>;repository:string;title:string;body:string;branch:string};
type Scan={scan_id:string;mode:string;data_origin?:string;findings:{resource_id:string;resource_name:string;rule_id:string}[]};
const supported=new Set(['ORPHANED_DISK','UNASSOCIATED_PUBLIC_IP','ORPHANED_NIC','ORPHANED_NSG','IDLE_APP_GATEWAY','AWS_UNATTACHED_EBS','AWS_UNASSOCIATED_EIP','AWS_IDLE_RDS','GCP_UNATTACHED_DISK','GCP_UNASSIGNED_ADDRESS','GCP_IDLE_CLOUD_SQL']);

export function GitOpsPanel({token,scan,canPublish}:{token:string;scan:Scan|undefined;canPublish:boolean}){
  const [targets,setTargets]=useState<Target[]>([]),[enabled,setEnabled]=useState(false),[target,setTarget]=useState('');
  const [selection,setSelection]=useState<string[]>([]),[preview,setPreview]=useState<Preview|null>(null),[history,setHistory]=useState<Review[]>([]);
  const [busy,setBusy]=useState(''),[error,setError]=useState('');
  const requestKey=useRef<string|null>(null);
  useEffect(()=>{let active=true;Promise.all([api<{targets:Target[];publishing_enabled:boolean}>('/gitops/targets',token),api<Review[]>('/gitops/requests',token)])
    .then(([config,rows])=>{if(active){setTargets(config.targets);setEnabled(config.publishing_enabled);setTarget(config.targets[0]?.target_id||'');setHistory(rows);}})
    .catch(()=>{if(active)setError('GitOps configuration or history could not be loaded.');});return()=>{active=false;};},[token]);
  function clearPreview(){setPreview(null);requestKey.current=null;}
  const payload={scan_id:scan?.scan_id,target_id:target,resource_ids:selection};
  async function prepare(){setBusy('preview');setError('');clearPreview();try{setPreview(await api<Preview>('/gitops/preview',token,payload));}catch(e){setError(e instanceof Error?e.message:'Preview failed');}finally{setBusy('');}}
  async function publish(){setBusy('publish');setError('');try{const row=await api<Review>('/gitops/requests',token,{...payload,idempotency_key:(requestKey.current ||= crypto.randomUUID())});setHistory(previous=>[row,...previous.filter(p=>p.id!==row.id)]);}catch(e){setError(e instanceof Error?e.message:'Publishing failed');setHistory(await api<Review[]>('/gitops/requests',token).catch(()=>history));}finally{setBusy('');}}
  return <section className="panel gitops-panel" id="gitops">
    <div className="section-title"><div><h2>GitOps review packages</h2><p>Preview isolated Terraform imports and explicitly open a draft PR in an approved repository.</p></div><span>{enabled?'Publishing configured':'Publishing disabled'}</span></div>
    {!targets.length&&<p>Your operator has not configured any GitHub targets for this workspace.</p>}
    {scan?.data_origin==='legacy_synthetic'&&<p>Historical synthetic snapshots cannot be exported or published. Select a current live scan.</p>}
    {targets.length>0&&<>
      <div className="gitops-inputs"><label>Approved repository<select disabled={!!busy} value={target} onChange={e=>{setTarget(e.target.value);clearPreview();}}>{targets.map(t=><option key={t.target_id} value={t.target_id}>{t.repository} → {t.base_branch}</option>)}</select></label>
      <label>Resources to review (up to 50)<select multiple size={5} value={selection} disabled={!!busy||!canPublish||scan?.data_origin==='legacy_synthetic'} onChange={e=>{setSelection(Array.from(e.target.selectedOptions,o=>o.value).slice(0,50));clearPreview();}}>{scan?.findings.filter(f=>supported.has(f.rule_id)).map(f=><option key={f.resource_id} value={f.resource_id}>{f.resource_name} · {f.rule_id}</option>)}</select></label></div>
      <button className="secondary" disabled={!!busy||!canPublish||!scan||scan.data_origin==='legacy_synthetic'||!selection.length} onClick={prepare}>Preview review package</button>
    </>}
    {error&&<p role="alert" className="error">{error}</p>}{busy&&<p role="status">{busy==='preview'?'Preparing import review…':'Publishing draft PR…'}</p>}
    {preview&&<div><h3>{preview.title}</h3><p>{preview.repository} · {preview.branch}</p><p>Only the files below will be added. CloudSaver executes no cloud action. The repository may run its own CI on the draft PR; review those rules before publishing.</p>
      {Object.entries(preview.files).map(([path,content])=><details key={path}><summary>{path}</summary><pre className="evidence-json">{content}</pre></details>)}
      <button className="primary" disabled={!!busy||!enabled||!canPublish} onClick={publish}>Open draft PR in {preview.repository}</button></div>}
    <h3>Request history</h3>{history.length?<ul>{history.slice(0,10).map(row=><li key={row.id}><strong>{row.repository}</strong> · {row.status} · {row.attempts} attempts{row.result&&<> · <a href={row.result.pr_url} target="_blank" rel="noopener noreferrer">View {row.result.state} PR</a></>}<small className="mono"> {row.id}</small></li>)}</ul>:<p>No GitOps publish requests yet.</p>}
  </section>;
}
