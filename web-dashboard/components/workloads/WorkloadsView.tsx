'use client';
import Link from 'next/link';
import {useEffect,useState} from 'react';
import {api} from '../../lib/api';
import {loadWorkloadInputs,type Projection} from '../../lib/workloads.mjs';
import {Layers} from 'lucide-react';
import {dateTime} from '../../lib/finops';
import {sentence} from '../../lib/resources';
import {useWorkspace} from '../WorkspaceProvider';
import {EmptyState,Loading,Notice,SectionTitle} from '../ui/shared';
import {EngineeringView} from './EngineeringView';
import css from './Engineering.module.css';

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
    {loading&&<Loading label="Loading authorized ownership and resource assessments…"/>}
    {error&&<Notice tone="error">{error} No partial workload totals are displayed.</Notice>}
    {projection&&<>
      <section className="panel workload-card"><SectionTitle title="Assessment summary" action={<button className="button secondary" disabled={loading} onClick={()=>setRevision(value=>value+1)}>Refresh saved assessments</button>}>Observed {result?.observed_at?dateTime(result.observed_at):'at an unknown time'}</SectionTitle>
        <dl className="settings-key-values"><div><dt>Visible resources</dt><dd>{projection.total.toLocaleString('en-US')}</dd></div><div><dt>Unassigned resources</dt><dd>{projection.unassigned.toLocaleString('en-US')}</dd></div><div><dt>Ambiguous mappings</dt><dd>{projection.ambiguous.toLocaleString('en-US')}</dd></div></dl>
        <p className="inline-help">Membership uses current explicit ownership, not historical ownership. Dependency coverage is unknown. Observed is not a compliance pass, and unknown evidence is not a healthy result.</p>
      </section>
      {!projection.workloads.length&&<section className="panel workload-card"><EmptyState icon={Layers} title="No mapped workloads in this observation">Assign application ownership in <Link href="/outcomes">Savings & investigations</Link> to group resources into workloads.</EmptyState></section>}
      {projection.workloads.slice(offset,offset+SIZE).map(item=><article className="panel workload-card" key={item.id}>
        <h2><button className="button secondary" aria-expanded={selected===item.id} onClick={()=>{setSelected(item.id);setResourceOffset(0);}}>{item.application} / {item.environment}</button></h2>
        <p>{item.members.length} resources</p>
        <ul>{item.pillars.map(p=><li key={p.pillar}>{`${sentence(p.pillar)}: ${p.counts.risk} at risk · ${p.counts.unknown} unknown · ${p.counts.observed} observed`}</li>)}</ul>
      </article>)}
      {!!projection.workloads.length&&<nav className="workload-pager" aria-label="Workload pages"><button disabled={!offset} onClick={()=>{setOffset(Math.max(0,offset-SIZE));setSelected('');}}>Previous workloads</button><span> {offset+1}–{Math.min(offset+SIZE,projection.workloads.length)} of {projection.workloads.length} </span><button disabled={offset+SIZE>=projection.workloads.length} onClick={()=>{setOffset(offset+SIZE);setSelected('');}}>Next workloads</button></nav>}
      {workload&&<section aria-label="Workload improvement preview"><h2>{workload.application} / {workload.environment}: improvement preview</h2>
        <p>Review only. Current evidence, compatibility, exceptions and exact approval must be checked through existing workflows before any change.</p>
        {workload.members.slice(resourceOffset,resourceOffset+SIZE).map(member=><article className="panel workload-card" key={member.identity}>
          <h3>{member.resource_name}</h3><p>{member.provider} · {member.scope_id} · Owner: {member.owner||'Unassigned'} · Team: {member.team||'Unassigned'}</p>
          <p style={{overflowWrap:'anywhere'}}>{member.resource_id}</p>
          <Link href={`/resources?resource=${encodeURIComponent(member.resource_key)}`}>Inspect resource evidence</Link>
          {!!member.evidence_gap_codes.length&&<p>Evidence gaps: {member.evidence_gap_codes.map(sentence).join(', ')}</p>}
          {!!member.preview.protected_reasons.length&&<p>Existing protections remain in force: {member.preview.protected_reasons.map(sentence).join(', ')}</p>}
          {!member.preview.actions.length&&<p>No supported remediation template for these findings.</p>}
          {member.preview.actions.map(action=><details key={action.id}><summary>{action.title} — needs live checks and approval</summary>
            <h4>Prerequisites</h4><ul>{action.prerequisites.map(value=><li key={value}>{value}</li>)}</ul>
            <h4>Proposed steps</h4><ol>{action.steps.map(value=><li key={value}>{value}</li>)}</ol>
            <h4>Verification</h4><ul>{action.verification.map(value=><li key={value}>{value}</li>)}</ul>
            <p>{action.recovery}</p>
          </details>)}
        </article>)}
        <nav className="workload-pager" aria-label="Resource pages"><button disabled={!resourceOffset} onClick={()=>setResourceOffset(Math.max(0,resourceOffset-SIZE))}>Previous resources</button><span> {resourceOffset+1}–{Math.min(resourceOffset+SIZE,workload.members.length)} of {workload.members.length} </span><button disabled={resourceOffset+SIZE>=workload.members.length} onClick={()=>setResourceOffset(resourceOffset+SIZE)}>Next resources</button></nav>
      </section>}
    </>}
  </>;
}
export function WorkloadsView(){
  const {workspace,token,scan,scans,selectScan,canBill}=useWorkspace();
  const [view,setView]=useState<'assessments'|'engineering'>('assessments');
  const live=!!scan&&scan.status==='completed'&&scan.data_origin!=='legacy_synthetic'&&scan.mode!=='demo';
  return <section aria-label="Workload assessments"><div className="page-heading"><div><div className="eyebrow">DISCOVER & ANALYZE</div><h1>Workload assessments</h1><p>Review mapped applications, saved evidence and guided improvement steps. No cloud changes are made here.</p></div></div>
    <div className={css.tabs} aria-label="Workload views"><button className="button secondary" aria-pressed={view==='assessments'} onClick={()=>setView('assessments')}>Saved assessments</button><button className="button secondary" aria-pressed={view==='engineering'} onClick={()=>setView('engineering')}>Engineering plans</button></div>
    {view==='engineering'?(workspace?<EngineeringView key={JSON.stringify([workspace.tenant_id,token])}/>:<Notice>Connect a workspace to continue.</Notice>):!workspace?<Notice>Connect a workspace to continue.</Notice>:!canBill?<section className="panel"><EmptyState icon={Layers} title="Finance access required">A billing or workspace administrator can review workload assessments.</EmptyState></section>:<>
      <section className="panel workload-toolbar"><label>Saved observation<select aria-label="Saved observation" value={scan?.scan_id||''} onChange={event=>selectScan(event.target.value)}><option value="" disabled>Select a scan</option>{scans.map(item=><option key={item.scan_id} value={item.scan_id}>{dateTime(item.timestamp)} · {item.scan_id.slice(0,8)}</option>)}</select></label>
      <p className="workload-links"><Link href="/outcomes">Manage application ownership</Link><Link href="/resources">Resource evidence</Link><Link href="/governance">Risk & compliance</Link><Link href="/automation">Reviewed remediation</Link></p></section>
      {!live?<Notice>Select a completed live scan. Synthetic and demo observations aren’t eligible.</Notice>:<Assessment key={JSON.stringify([workspace.tenant_id,token,scan.scan_id])} token={token} scanId={scan.scan_id}/>}
    </>}
  </section>;
}
