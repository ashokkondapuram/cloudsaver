'use client';

import {useCallback,useEffect,useState} from 'react';
import {Button} from './ui/button';

type Delivery={id:string;kind:string;status:string;target_id:string|null;job_id:string|null;scan_id:string|null;attempts:number;replay_count:number;error_code:string|null;created_at:string;updated_at:string};
type Audit={id:string;action:string;actor:string;status:string;attempts:number;error_code:string|null;created_at:string};
type Summary={available:boolean;dispatcher_enabled:boolean;targets:{target_id:string;channel:string}[];counts:{kind:string;status:string;count:number}[];oldest_due_seconds:number|null;dispatcher:{last_poll_at:string;last_success_at:string|null;last_error_at:string|null}|null};
const timestamp=(value:string|null|undefined)=>value?new Date(value).toLocaleString():'Not observed';
const labels:Record<string,string>={pending:'Waiting',leased:'In flight',published:'Broker accepted',delivered:'Acknowledged',dead_letter:'Needs intervention'};

async function api<T>(token:string,path:string,body?:unknown):Promise<T>{
  const response=await fetch('/api/v1/operations/'+path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+token,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined,cache:'no-store'});
  if(!response.ok)throw new Error(`Operational request failed (${response.status}). Refresh or contact your operator.`);
  return response.json();
}

export function ReliabilityPanel({token,canAdmin}:{token:string;canAdmin:boolean}){
  const [statusFilter,setStatusFilter]=useState(''),[listCursor,setListCursor]=useState<string|null>(null);
  const [summary,setSummary]=useState<Summary|null>(null),[rows,setRows]=useState<Delivery[]>([]);
  const [selected,setSelected]=useState<Delivery|null>(null),[audit,setAudit]=useState<Audit[]>([]),[cursor,setCursor]=useState<string|null>(null);
  const [acknowledged,setAcknowledged]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const refresh=useCallback(async()=>{
    const next=await api<Summary>(token,'reliability');setSummary(next);
    if(next.available){const page=await api<{items:Delivery[];next_cursor:string|null}>(token,'deliveries?limit=50'+(statusFilter?'&status='+statusFilter:''));setRows(page.items);setListCursor(page.next_cursor);}
  },[token,statusFilter]);
  useEffect(()=>{let active=true;
    // Poll only while visible; credentials and integration state stay in memory.
    async function poll(){if(!document.hidden&&active){try{await refresh();}catch{if(active)setError('Delivery status could not be refreshed.');}}}
    poll();const timer=setInterval(poll,30000);return()=>{active=false;clearInterval(timer);};
  },[refresh]);
  async function moreDeliveries(){
    if(!listCursor)return;setBusy(true);
    try{const page=await api<{items:Delivery[];next_cursor:string|null}>(token,`deliveries?limit=50&before=${listCursor}${statusFilter?'&status='+statusFilter:''}`);setRows(previous=>[...previous,...page.items]);setListCursor(page.next_cursor);}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function inspect(row:Delivery){
    setSelected(row);setAudit([]);setCursor(null);setAcknowledged(false);setError('');setBusy(true);
    try{const page=await api<{items:Audit[];next_cursor:string|null}>(token,`deliveries/${row.id}/audit`);setAudit(page.items);setCursor(page.next_cursor);}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function more(){
    if(!selected||!cursor)return;setBusy(true);
    try{const page=await api<{items:Audit[];next_cursor:string|null}>(token,`deliveries/${selected.id}/audit?before=${encodeURIComponent(cursor)}`);setAudit(previous=>[...previous,...page.items]);setCursor(page.next_cursor);}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function replay(){
    if(!selected)return;setBusy(true);setError('');
    try{await api(token,`deliveries/${selected.id}/retry`,{acknowledge_duplicate_risk:acknowledged});await refresh();await inspect({...selected,status:'pending',attempts:0,replay_count:selected.replay_count+1});}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  const count=(status:string)=>summary?.counts.filter(c=>c.status===status).reduce((sum,c)=>sum+c.count,0)||0;
  return <section className="panel reliability-panel" id="reliability" aria-labelledby="reliability-title">
    <div className="section-title"><div><h2 id="reliability-title">Delivery reliability</h2><p>Durable scan handoff and workspace integration delivery · refreshes every 30 seconds</p></div><Button className="secondary" disabled={busy} onClick={()=>refresh().catch(()=>setError('Delivery status could not be refreshed.'))}>Refresh status</Button></div>
    {error&&<p role="alert" className="error">{error}</p>}
    {!summary?<p role="status">Loading delivery state…</p>:!summary.available?<p>Configure PostgreSQL to enable durable delivery and its audit history.</p>:<>
      <div className="reliability-metrics">{['pending','leased','published','dead_letter'].map(status=><div key={status}><span>{labels[status]}</span><strong>{count(status)}</strong></div>)}</div>
      <dl className="ops-grid"><div><dt>Operator switch</dt><dd>{summary.dispatcher_enabled?'Enabled':'Disabled'}</dd></div><div><dt>Last dispatcher poll</dt><dd>{timestamp(summary.dispatcher?.last_poll_at)}</dd></div><div><dt>Last successful cycle</dt><dd>{timestamp(summary.dispatcher?.last_success_at)}</dd></div><div><dt>Oldest due item</dt><dd>{summary.oldest_due_seconds===null?'No due backlog':`${Math.floor(summary.oldest_due_seconds/60)} min overdue`}</dd></div><div><dt>Approved integrations</dt><dd>{summary.targets.length?summary.targets.map(t=>`${t.target_id} (${t.channel})`).join(', '):'None configured'}</dd></div></dl>
      <p className="security-note">Broker acceptance is followed by execution reconciliation. Webhook acknowledgment means the provider returned success; it does not prove a person received it. Delivery can repeat after a lost response.</p>
      <label className="delivery-filter">Delivery state <select value={statusFilter} disabled={busy} onChange={e=>{setStatusFilter(e.target.value);setSelected(null);setListCursor(null);}}><option value="">All states</option>{Object.entries(labels).map(([key,value])=><option key={key} value={key}>{value}</option>)}</select></label>
      {rows.length?<div className="delivery-list">{rows.map(row=><button type="button" disabled={busy} key={row.id} className={`delivery-row ${selected?.id===row.id?'selected':''}`} onClick={()=>inspect(row)}><span><strong>{row.kind==='scan'?'Scheduled scan':row.target_id}</strong><small>{timestamp(row.updated_at)}</small></span><span className={`delivery-status ${row.status}`}>{labels[row.status]||row.status}</span><span>{row.attempts}/8 attempts</span><span aria-hidden="true">→</span></button>)}</div>:<div className="empty">No delivery intents have been recorded. Configure an approved workspace integration or turn on scheduled scans to begin.</div>}
      {listCursor&&<Button className="secondary" disabled={busy} onClick={moreDeliveries}>Load earlier deliveries</Button>}
      {selected&&<div className="delivery-audit" aria-live="polite"><div className="section-title"><div><h3>Delivery audit</h3><code>{selected.id}</code></div><Button className="secondary" onClick={()=>{setSelected(null);setAudit([]);}} disabled={busy}>Close audit</Button></div>
        <ol>{audit.map(entry=><li key={entry.id}><div><strong>{entry.action.replaceAll('_',' ')}</strong><time dateTime={entry.created_at}>{timestamp(entry.created_at)}</time></div><span>{labels[entry.status]||entry.status} · attempt {entry.attempts}{entry.error_code?` · ${entry.error_code.replaceAll('_',' ')}`:''}</span><small>Actor: {entry.actor}</small></li>)}</ol>
        {cursor&&<Button className="secondary" disabled={busy} onClick={more}>Load earlier events</Button>}
        {selected.status==='dead_letter'&&selected.kind==='notification'&&canAdmin&&<div className="delivery-replay"><h3>Retry this notification</h3><p>Inspect the failure and fix its cause first. A previous attempt may have reached the provider. Up to three manual replays are permitted; changing the destination requires a new notification intent.</p><label><input type="checkbox" checked={acknowledged} onChange={e=>setAcknowledged(e.target.checked)} disabled={busy}/> I understand this may send a duplicate notification.</label><Button className="primary" disabled={!acknowledged||busy||!summary.dispatcher_enabled||selected.replay_count>=3} onClick={replay}>Queue retry ({selected.replay_count}/3 used)</Button></div>}
      </div>}
    </>}
  </section>;
}
