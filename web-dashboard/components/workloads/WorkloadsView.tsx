'use client';
import Link from 'next/link';
import {useEffect,useState} from 'react';
import {api} from '../../lib/api';
import {loadWorkloadInputs,type Projection} from '../../lib/workloads.mjs';
import {useWorkspace} from '../WorkspaceProvider';

const SIZE=20;
function Assessment({token,scanId}:{token:string;scanId:string}){
  const [result,setResult]=useState<{projection:Projection;observed_at:string|null}|null>(null);
  const [error,setError]=useState('');const [loading,setLoading]=useState(false);
  const [revision,setRevision]=useState(0);const [offset,setOffset]=useState(0);
  const [selected,setSelected]=useState('');const [resourceOffset,setResourceOffset]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    setResult(null);setError('');setLoading(true);setSelected('');setOffset(0);setResourceOffset(0);
    loadWorkloadInputs((path,options)=>api<unknown>(path,token,options),scanId,controller.signal)
      .then(value=>{if(!controller.signal.aborted)setResult(value);})
      .catch(cause=>{if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:'Workloads could not be loaded.');})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[token,scanId,revision]);
  const projection=result?.projection;
  const workload=projection?.workloads.find(item=>item.id===selected);
  return <>
    <button className="button secondary" disabled={loading} onClick={()=>setRevision(value=>value+1)}>Refresh saved assessments</button>
    {loading&&<p role="status">Loading authorized ownership and resource assessments…</p>}
    {error&&<p role="alert">{error} No partial workload totals are displayed.</p>}
    {projection&&<>
      <p>Observed: {result?.observed_at||'Unknown'}. Membership uses current explicit ownership, not historical ownership. Dependency coverage is unknown.</p>
      <p>Visible resources: {projection.total}. Unassigned resources: {projection.unassigned}. Ambiguous mappings: {projection.ambiguous}.</p>
      <p>Observed is not a compliance pass. Unknown evidence is not a healthy result. No verified savings or execution authority is asserted.</p>
      {!projection.workloads.length&&<p>No mapped workloads in this observation. Use the existing Application ownership controls in Outcomes.</p>}
      {projection.workloads.slice(offset,offset+SIZE).map(item=><article className="panel" key={item.id}>
        <h2><button className="button secondary" aria-expanded={selected===item.id} onClick={()=>{setSelected(item.id);setResourceOffset(0);}}>{item.application} / {item.environment}</button></h2>
        <p>{item.members.length} resources</p>
        <ul>{item.pillars.map(p=><li key={p.pillar}>{p.pillar}: risk {p.counts.risk}; unknown {p.counts.unknown}; observed {p.counts.observed}</li>)}</ul>
      </article>)}
      {!!projection.workloads.length&&<nav aria-label="Workload pages"><button disabled={!offset} onClick={()=>{setOffset(Math.max(0,offset-SIZE));setSelected('');}}>Previous workloads</button><span> {offset+1}–{Math.min(offset+SIZE,projection.workloads.length)} of {projection.workloads.length} </span><button disabled={offset+SIZE>=projection.workloads.length} onClick={()=>{setOffset(offset+SIZE);setSelected('');}}>Next workloads</button></nav>}
      {workload&&<section aria-label="Workload improvement preview"><h2>{workload.application} / {workload.environment}: improvement preview</h2>
        <p>Review only. Current evidence, compatibility, exceptions and exact approval must be checked through existing workflows before any change.</p>
        {workload.members.slice(resourceOffset,resourceOffset+SIZE).map(member=><article className="panel" key={member.identity}>
          <h3>{member.resource_name}</h3><p>{member.provider} · {member.scope_id} · Owner: {member.owner||'Unassigned'} · Team: {member.team||'Unassigned'}</p>
          <p style={{overflowWrap:'anywhere'}}>{member.resource_id}</p>
          <Link href={`/resources?resource=${encodeURIComponent(member.resource_key)}`}>Inspect resource evidence</Link>
          {!!member.evidence_gap_codes.length&&<p>Evidence gaps: {member.evidence_gap_codes.join(', ')}</p>}
          {!!member.preview.protected_reasons.length&&<p>Existing protections remain in force: {member.preview.protected_reasons.join(', ')}</p>}
          {!member.preview.actions.length&&<p>No supported remediation template for these findings.</p>}
          {member.preview.actions.map(action=><details key={action.id}><summary>{action.title} — blocked pending live checks and approval</summary>
            <h4>Prerequisites</h4><ul>{action.prerequisites.map(value=><li key={value}>{value}</li>)}</ul>
            <h4>Proposed steps</h4><ol>{action.steps.map(value=><li key={value}>{value}</li>)}</ol>
            <h4>Verification</h4><ul>{action.verification.map(value=><li key={value}>{value}</li>)}</ul>
            <p>{action.recovery}</p>
          </details>)}
        </article>)}
        <nav aria-label="Resource pages"><button disabled={!resourceOffset} onClick={()=>setResourceOffset(Math.max(0,resourceOffset-SIZE))}>Previous resources</button><span> {resourceOffset+1}–{Math.min(resourceOffset+SIZE,workload.members.length)} of {workload.members.length} </span><button disabled={resourceOffset+SIZE>=workload.members.length} onClick={()=>setResourceOffset(resourceOffset+SIZE)}>Next resources</button></nav>
      </section>}
    </>}
  </>;
}
export function WorkloadsView(){
  const {workspace,token,scan,scans,selectScan,canBill}=useWorkspace();
  const live=!!scan&&scan.status==='completed'&&scan.data_origin!=='legacy_synthetic'&&scan.mode!=='demo';
  return <section aria-label="Workload assessments"><div className="page-heading"><div><div className="eyebrow">WORKLOAD ASSESSMENTS</div><h1>Five pillars, one application view.</h1><p>Review mapped applications, saved evidence and guided improvement steps. No cloud changes are made here.</p></div></div>
    {!workspace?<p>Connect a workspace to continue.</p>:!canBill?<><h2>Finance access required</h2><p>BillingAdmin or TenantAdmin access is required, matching existing ownership permissions.</p></>:<>
      <label>Saved observation <select aria-label="Saved observation" value={scan?.scan_id||''} onChange={event=>selectScan(event.target.value)}><option value="" disabled>Select a scan</option>{scans.map(item=><option key={item.scan_id} value={item.scan_id}>{item.timestamp} — {item.scan_id}</option>)}</select></label>
      <p><Link href="/outcomes">Manage application ownership</Link> · <Link href="/resources">Resource evidence</Link> · <Link href="/governance">Existing governance</Link> · <Link href="/automation">Reviewed remediation</Link></p>
      {!live?<p>Select a completed live scan. Synthetic and demo observations are not eligible.</p>:<Assessment key={JSON.stringify([workspace.tenant_id,token,scan.scan_id])} token={token} scanId={scan.scan_id}/>}
    </>}
  </section>;
}
