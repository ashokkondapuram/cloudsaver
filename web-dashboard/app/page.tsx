'use client';

import {useEffect,useMemo,useRef,useState} from 'react';
import {ColumnDef,flexRender,getCoreRowModel,getSortedRowModel,SortingState,useReactTable} from '@tanstack/react-table';
import {useVirtualizer} from '@tanstack/react-virtual';
import {Button} from '../components/ui/button';

type Finding={rule_id:string;severity:string;resource_name:string;resource_type:string;resource_group:string;subscription_id:string;resource_id:string;estimated_monthly_waste_usd:number|null;details:string};
type Scan={scan_id:string;timestamp:string;mode:string;subscriptions_scanned:number;total_items_found:number;total_monthly_waste_usd:number|null;findings:Finding[];status:string};
type Workspace={name:string;tenant_id:string;subscription_ids:string[];mode:string};
const rules:Record<string,string>={ORPHANED_DISK:'Unattached disk',UNASSOCIATED_PUBLIC_IP:'Unassociated public IP',STOPPED_VM:'Stopped virtual machine',EMPTY_APP_SERVICE_PLAN:'Empty App Service plan',UNDERUTILIZED_APP_SERVICE_PLAN:'App Service review'};
const label=(rule:string)=>rules[rule]||rule.replaceAll('_',' ').toLowerCase();
const money=(value:number|null)=>value===null?'Not estimated':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(value);
const date=(value:string)=>new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});
async function request<T>(path:string,key:string,method='GET',body?:unknown):Promise<T>{
  const response=await fetch(`/api/v1${path}`,{method,headers:{Authorization:`Bearer ${key}`,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined,cache:'no-store'});
  if(!response.ok){let message=`Request failed (${response.status})`;try{const body=await response.json();if(typeof body.detail==='string')message=body.detail;}catch{}throw new Error(message);}
  return response.json();
}

function Inventory({findings,onSelect}:{findings:Finding[];onSelect:(f:Finding)=>void}){
  const [query,setQuery]=useState('');const [rule,setRule]=useState('');const [severity,setSeverity]=useState('');const [sorting,setSorting]=useState<SortingState>([]);
  const filtered=useMemo(()=>findings.filter(f=>(!rule||f.rule_id===rule)&&(!severity||f.severity===severity)&&`${f.resource_name} ${f.resource_group} ${f.subscription_id} ${label(f.rule_id)}`.toLowerCase().includes(query.toLowerCase())),[findings,query,rule,severity]);
  const columns=useMemo<ColumnDef<Finding>[]>(()=>[
    {accessorKey:'resource_name',header:'Resource',cell:({row})=><button className="resource-name" onClick={()=>onSelect(row.original)}><span>{row.original.resource_name}</span><small>{row.original.resource_type.split('/').slice(-1)[0]}</small></button>},
    {accessorKey:'rule_id',header:'Finding',cell:({row})=><div><span>{label(row.original.rule_id)}</span><small className={`severity ${row.original.severity.toLowerCase()}`}>{row.original.severity}</small></div>},
    {accessorKey:'resource_group',header:'Resource group',cell:({row})=><div><span>{row.original.resource_group}</span><small className="mono">{row.original.subscription_id.slice(0,12)}…</small></div>},
    {accessorKey:'estimated_monthly_waste_usd',header:'Monthly potential',cell:({row})=><span className="amount">{money(row.original.estimated_monthly_waste_usd)}</span>},
  ],[onSelect]);
  const table=useReactTable({data:filtered,columns,state:{sorting},onSortingChange:setSorting,getCoreRowModel:getCoreRowModel(),getSortedRowModel:getSortedRowModel()});
  const scroll=useRef<HTMLDivElement>(null);const {rows}=table.getRowModel();
  const virtual=useVirtualizer({count:rows.length,getScrollElement:()=>scroll.current,estimateSize:()=>82,overscan:8});
  const items=virtual.getVirtualItems();
  return <section className="panel inventory" id="findings" aria-labelledby="findings-title"><div className="section-title"><div><h2 id="findings-title">Resource findings <span className="count">{findings.length.toLocaleString()}</span></h2><p>Review the evidence before making changes to your cloud.</p></div></div>
    <div className="filters"><label className="search"><span className="sr-only">Search resources</span><input type="search" placeholder="Search resource, group or subscription…" value={query} onChange={e=>setQuery(e.target.value)}/></label><label><span className="sr-only">Filter by finding</span><select value={rule} onChange={e=>setRule(e.target.value)}><option value="">All findings</option>{[...new Set(findings.map(f=>f.rule_id))].sort().map(r=><option key={r} value={r}>{label(r)}</option>)}</select></label><label><span className="sr-only">Filter by severity</span><select value={severity} onChange={e=>setSeverity(e.target.value)}><option value="">All severities</option>{[...new Set(findings.map(f=>f.severity))].sort().map(s=><option key={s}>{s}</option>)}</select></label></div>
    <div ref={scroll} className="table-scroll"><table><thead>{table.getHeaderGroups().map(group=><tr key={group.id}>{group.headers.map(header=><th key={header.id}><button onClick={header.column.getToggleSortingHandler()}>{flexRender(header.column.columnDef.header,header.getContext())} <span aria-hidden="true">{header.column.getIsSorted()==='asc'?'↑':header.column.getIsSorted()==='desc'?'↓':'↕'}</span></button></th>)}</tr>)}</thead><tbody>
      {items.length>0&&<tr aria-hidden="true"><td colSpan={4} style={{height:items[0].start,padding:0,border:0}}/></tr>}
      {items.map(item=>{const row=rows[item.index];return <tr key={row.id} style={{height:82}}>{row.getVisibleCells().map(cell=><td key={cell.id}>{flexRender(cell.column.columnDef.cell,cell.getContext())}</td>)}</tr>;})}
      {items.length>0&&<tr aria-hidden="true"><td colSpan={4} style={{height:virtual.getTotalSize()-items[items.length-1].end,padding:0,border:0}}/></tr>}
      {!filtered.length&&<tr><td colSpan={4} className="empty">{findings.length?'No resources match these filters.':'No findings in this scan.'}</td></tr>}
    </tbody></table></div><div className="table-footer">{filtered.length.toLocaleString()} matching resources <span>Virtualized inventory · sort by column</span></div>
  </section>;
}

export default function Dashboard(){
  const [accessKey,setAccessKey]=useState('');const [key,setKey]=useState('');const [workspace,setWorkspace]=useState<Workspace|null>(null);const [scans,setScans]=useState<Scan[]>([]);const [selected,setSelected]=useState<string>('');const [error,setError]=useState('');const [busy,setBusy]=useState('');const [detail,setDetail]=useState<Finding|null>(null);
  useEffect(()=>{
    if(!detail)return;
    const previous=document.activeElement as HTMLElement|null;
    const handler=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){event.preventDefault();setDetail(null);}
      if(event.key==='Tab'){
        const controls=Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"] button:not([disabled]), [role="dialog"] a[href], [role="dialog"] input:not([disabled])'));
        const first=controls[0],last=controls[controls.length-1];
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
      }
    };
    document.addEventListener('keydown',handler);
    return()=>{document.removeEventListener('keydown',handler);previous?.focus();};
  },[detail]);
  const scan=scans.find(s=>s.scan_id===selected)||scans[0];
  const distribution=useMemo(()=>{const counts:Record<string,number>={};for(const f of scan?.findings||[])counts[f.rule_id]=(counts[f.rule_id]||0)+1;return Object.entries(counts).sort((a,b)=>b[1]-a[1]);},[scan]);
  async function connect(event:React.FormEvent){event.preventDefault();setBusy('Connecting');setError('');try{const me=await request<Workspace>('/me',accessKey.trim());const history=await request<Scan[]>('/scans',accessKey.trim());setWorkspace(me);setKey(accessKey.trim());setAccessKey('');setScans(history);setSelected(history[0]?.scan_id||'');}catch(e){setError(e instanceof Error?e.message:'Unable to connect');}finally{setBusy('');}}
  async function run(){setBusy('Scanning Azure');setError('');setDetail(null);try{const result=await request<Scan>('/scans',key,'POST');setScans(previous=>[result,...previous]);setSelected(result.scan_id);}catch(e){setError(e instanceof Error?e.message:'Scan failed');}finally{setBusy('');}}
  async function refresh(){setBusy('Refreshing');setError('');try{const history=await request<Scan[]>('/scans',key);setScans(history);setSelected(history[0]?.scan_id||'');setDetail(null);}catch(e){setError(e instanceof Error?e.message:'Refresh failed');}finally{setBusy('');}}
  function signout(){setWorkspace(null);setKey('');setScans([]);setSelected('');setDetail(null);setError('');}
  function download(){if(!scan)return;const url=URL.createObjectURL(new Blob([JSON.stringify(scan,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`cloudsaver-${scan.scan_id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function downloadCSV(){
    if(!scan)return;
    const fields=['rule_id','severity','resource_name','resource_type','resource_group','subscription_id','resource_id','estimated_monthly_waste_usd','details'] as const;
    const cell=(value:unknown)=>{let text=String(value??'');if(/^[\s]*[=+@\-]|^[\t\r\n]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';};
    const csv=[fields.join(','),...scan.findings.map(f=>fields.map(field=>cell(f[field])).join(','))].join('\r\n');
    const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`cloudsaver-${scan.scan_id}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function remediation(){
    if(!scan||!detail)return;
    setBusy('Generating script');setError('');
    try{const result=await request<{script:string;filename:string}>(`/scans/${scan.scan_id}/remediation`,key,'POST',{resource_ids:[detail.resource_id]});const url=URL.createObjectURL(new Blob([result.script],{type:'text/plain'}));const a=document.createElement('a');a.href=url;a.download=result.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){setError(e instanceof Error?e.message:'Script generation failed');setDetail(null);}finally{setBusy('');}
  }
  return <div className="shell"><aside className="sidebar"><a className="brand" href="#overview"><span className="brand-mark">C<span>↗</span></span>CloudSaver</a><div className="workspace-label">AZURE INTELLIGENCE</div><nav aria-label="Primary"><a className="active" href="#overview"><span>◫</span>Overview</a><a href="#findings"><span>▤</span>Resource findings</a><a href="#history"><span>↺</span>Scan history</a></nav><div className="sidebar-bottom"><div className="shield">✓</div><strong>Read-only by design</strong><p>Find opportunities. Keep your infrastructure in your control.</p><div className="version">ENGINEERING MVP <span>v0.1</span></div></div></aside>
    <main id="overview"><header className="topbar"><span>Workspace <span className="slash">/</span> <strong>{workspace?.name||'Connect your workspace'}</strong></span><span className={`mode ${workspace?.mode==='azure'?'live':''}`}>{workspace?(workspace.mode==='demo'?'Demo data':'Azure live mode'):'Local workspace'}</span>{workspace&&<button className="text-button" onClick={signout} disabled={!!busy}>Disconnect</button>}</header>
    <div className="content"><div className="heading"><div><div className="eyebrow">CLOUD COST INTELLIGENCE</div><h1>Less waste.<br className="mobile-break"/> More possibility.</h1><p>A clear view of the Azure resources worth a closer look.</p></div>{workspace&&<Button onClick={run} disabled={!!busy} className="primary">{busy==='Scanning Azure'?'Scanning…':'+ Run new scan'}</Button>}</div>
    {error&&<div role="alert" className="error"><strong>Something needs attention.</strong> {error}</div>}
    <div className="sr-only" role="status" aria-live="polite">{busy}</div>
    {!workspace?<section className="connect-grid"><div className="connect-copy"><span className="pill">YOUR AZURE, IN FOCUS</span><h2>Turn cloud clutter<br/>into a clear next step.</h2><p>Connect to your configured workspace to scan for unattached storage, unused IPs and other review signals.</p><ul><li><span>01</span>Inspect your Azure resources</li><li><span>02</span>Review findings and evidence</li><li><span>03</span>Export a scan for your team</li></ul><div className="connect-decoration" aria-hidden="true"><span>RESOURCES</span><div/><div/><div/><i>↗</i></div></div><form onSubmit={connect} className="connect-form panel"><div className="icon-box">↗</div><h2>Open your workspace</h2><p>Use the access key generated during server setup.</p><label htmlFor="access-key">Workspace access key</label><input id="access-key" type="password" autoComplete="off" placeholder="Paste your access key" value={accessKey} onChange={e=>setAccessKey(e.target.value)} required disabled={!!busy}/><Button className="primary" type="submit" disabled={!!busy||!accessKey.trim()}>{busy?'Connecting…':'Connect workspace →'}</Button><p className="security-note">Your key stays in memory for this session. Use localhost or HTTPS. Setup instructions are in the project README.</p></form></section>:<>
      {workspace.mode==='demo'&&<div className="demo-notice"><span>DEMO WORKSPACE</span> Findings and dollar amounts are illustrative fixtures. No Azure request is made.</div>}
      <section className="stats" aria-label="Scan metrics"><article className="stat featured"><div className="stat-label">{scan?.mode==='demo'?'Illustrative monthly potential':'Monthly savings estimate'}<span>↗</span></div><strong>{scan?money(scan.total_monthly_waste_usd):'—'}</strong><p>{scan?.mode==='demo'?'Demo amounts · USD per month':'Requires billing and usage validation'}</p></article><article className="stat"><div className="stat-label">Resources to review<span>▤</span></div><strong>{scan?scan.total_items_found.toLocaleString():'—'}</strong><p>{scan?'Potential waste signals detected':'Run your first scan to get started'}</p></article><article className="stat"><div className="stat-label">Subscriptions<span>◈</span></div><strong>{scan?.subscriptions_scanned??workspace.subscription_ids.length}</strong><p>{scan?'Included in the selected scan':'Configured for this workspace'}</p></article></section>
      <div className="overview-grid"><section className="panel breakdown"><div className="section-title"><div><h2>Where to look first</h2><p>Findings by resource signal</p></div><span className="small-label">{scan?'SELECTED SCAN':'AWAITING SCAN'}</span></div>{distribution.length?distribution.map(([rule,count])=><div className="breakdown-row" key={rule}><div><span>{label(rule)}</span><strong>{count.toLocaleString()}</strong></div><div className="bar"><i style={{width:`${count/(scan?.total_items_found||1)*100}%`}}/></div></div>):<div className="empty">{scan?'No waste signals detected in this scan.':'Your resource breakdown will appear after a scan.'}</div>}</section><section className="panel scan-info"><div className="section-title"><h2>Scan snapshot</h2><span className="status-dot"/></div><dl><div><dt>Status</dt><dd>{busy==='Scanning Azure'?'Scanning…':scan?'Completed':'Ready to scan'}</dd></div><div><dt>Finished</dt><dd>{scan?date(scan.timestamp):'No scans yet'}</dd></div><div><dt>Data source</dt><dd>{scan?.mode==='demo'?'Illustrative fixtures':workspace.mode==='demo'?'Demo fixtures':'Azure Resource Graph'}</dd></div><div><dt>Scan reference</dt><dd className="mono">{scan?scan.scan_id.slice(0,8):'—'}</dd></div></dl><p>Signals are a starting point for investigation. A flagged resource may still be needed.</p></section></div>
      {scan?<Inventory key={scan.scan_id} findings={scan.findings} onSelect={setDetail}/>:<section className="panel empty first-scan" id="findings"><div className="icon-box">◫</div><h2>Your next opportunity starts with a scan</h2><p>Scan your configured subscriptions to see resource findings here.</p><Button onClick={run} className="primary" disabled={!!busy}>Run first scan</Button></section>}
      <section className="panel history" id="history"><div className="section-title"><div><h2>Scan history</h2><p>Saved results for this workspace</p></div><div className="actions"><Button className="secondary" onClick={refresh} disabled={!!busy}>Refresh</Button><Button className="secondary" onClick={download} disabled={!scan||!!busy}>Export JSON ↓</Button><Button className="secondary" onClick={downloadCSV} disabled={!scan||!!busy}>Export CSV ↓</Button></div></div>{scans.length?<div className="history-list">{scans.map(item=><button className={`history-item ${item.scan_id===scan?.scan_id?'selected':''}`} key={item.scan_id} onClick={()=>{setSelected(item.scan_id);setDetail(null);}}><span><strong>{date(item.timestamp)}</strong><small className="mono">{item.scan_id.slice(0,8)} · {item.mode}</small></span><span>{item.total_items_found.toLocaleString()} findings</span><span>{item.subscriptions_scanned} subscriptions</span><span className="history-view">{item.scan_id===scan?.scan_id?'Viewing':'View scan →'}</span></button>)}</div>:<p className="empty">No saved scans yet.</p>}</section>
    </>}
    <footer><span>CloudSaver <b>·</b> Azure FinOps workspace</span><span>Evidence first. Decisions stay with you.</span></footer></div></main>
    {detail&&<div className="modal-backdrop" onClick={()=>setDetail(null)}><section className="detail panel" role="dialog" aria-modal="true" aria-labelledby="detail-title" onClick={e=>e.stopPropagation()}><div className="section-title"><h2 id="detail-title">Resource evidence</h2><Button className="secondary" onClick={()=>setDetail(null)} autoFocus>Close ×</Button></div><h3>{detail.resource_name}</h3><span className={`severity ${detail.severity.toLowerCase()}`}>{detail.severity}</span><p>{detail.details}</p><dl>{[['Finding',label(detail.rule_id)],['Resource group',detail.resource_group],['Subscription',detail.subscription_id],['Resource ID',detail.resource_id],['Monthly potential',money(detail.estimated_monthly_waste_usd)]].map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl><p className="security-note">Confirm ownership, backups and dependencies before changing a resource. This application performs no remediation.</p>{scan?.mode==='azure'&&['ORPHANED_DISK','UNASSOCIATED_PUBLIC_IP'].includes(detail.rule_id)&&<div className="script-action"><p>Generate a script to review offline. Downloading it does not execute any Azure changes.</p><Button className="secondary" disabled={!!busy} onClick={remediation}>{busy==='Generating script'?'Generating…':'Generate review script ↓'}</Button></div>}</section></div>}
  </div>;
}
