'use client';

import {useEffect,useMemo,useRef,useState} from 'react';
import {ColumnDef,flexRender,getCoreRowModel,getSortedRowModel,SortingState,useReactTable} from '@tanstack/react-table';
import {useVirtualizer} from '@tanstack/react-virtual';
import {Button} from '../components/ui/button';

type CostAttribution={
  monthly_waste_usd:number|null;
  currency:string;
  confidence:'HIGH'|'UNKNOWN';
  calculation_basis:string;
  potential_waste_usd:number|null;
  realizable_savings_usd:number|null;
  unit_price?:number;
  unit_of_measure?:string;
};

type Finding={
  rule_id:string;
  severity:string;
  resource_name:string;
  resource_type:string;
  resource_group:string;
  subscription_id:string;
  resource_id:string;
  estimated_monthly_waste_usd:number|null;
  details:string;
  cost_attribution?:CostAttribution;
};

type Scan={
  scan_id:string;
  timestamp:string;
  mode:string;
  subscriptions_scanned:number;
  total_items_found:number;
  total_monthly_waste_usd:number|null;
  realizable_monthly_savings_usd?:number|null;
  findings:Finding[];
  status:string;
};

type Workspace={
  name:string;
  tenant_id:string;
  subscription_ids:string[];
  mode:string;
  plan_tier?:string;
  max_subscriptions?:number;
  can_export_terraform?:boolean;
  roles?:string[];
};

const rules:Record<string,string>={
  ORPHANED_DISK:'Unattached disk',
  ORPHANED_DISKS:'Unattached disk',
  UNASSOCIATED_PUBLIC_IP:'Unassociated public IP',
  UNASSOCIATED_PUBLIC_IPS:'Unassociated public IP',
  STOPPED_VM:'Stopped virtual machine',
  STOPPED_VMS:'Stopped virtual machine',
  EMPTY_APP_SERVICE_PLAN:'Empty App Service plan',
  EMPTY_APP_SERVICE:'Empty App Service plan',
  UNDERUTILIZED_APP_SERVICE_PLAN:'App Service review'
};

const label=(rule:string)=>rules[rule]||rule.replaceAll('_',' ').toLowerCase();
const money=(value:number|null|undefined)=>value===null||value===undefined?'Not estimated':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(value);
const date=(value:string)=>new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});

async function request<T>(path:string,key:string,method='GET',body?:unknown):Promise<T>{
  const response=await fetch(`/api/v1${path}`,{
    method,
    headers:{
      Authorization:`Bearer ${key}`,
      ...(body?{'Content-Type':'application/json'}:{})
    },
    body:body?JSON.stringify(body):undefined,
    cache:'no-store'
  });
  if(!response.ok){
    let message=`Request failed (${response.status})`;
    try{
      const resBody=await response.json();
      if(typeof resBody.detail==='string')message=resBody.detail;
      else if(Array.isArray(resBody.detail))message=resBody.detail.map((d:any)=>d.msg||d).join('; ');
    }catch{}
    throw new Error(message);
  }
  return response.json();
}

function Inventory({findings,onSelect}:{findings:Finding[];onSelect:(f:Finding)=>void}){
  const [query,setQuery]=useState('');
  const [rule,setRule]=useState('');
  const [severity,setSeverity]=useState('');
  const [sorting,setSorting]=useState<SortingState>([]);

  const filtered=useMemo(()=>findings.filter(f=>(!rule||f.rule_id===rule)&&(!severity||f.severity===severity)&&`${f.resource_name} ${f.resource_group} ${f.subscription_id} ${label(f.rule_id)}`.toLowerCase().includes(query.toLowerCase())),[findings,query,rule,severity]);

  const columns=useMemo<ColumnDef<Finding>[]>(()=>[
    {
      accessorKey:'resource_name',
      header:'Resource',
      cell:({row})=><button className="resource-name" onClick={()=>onSelect(row.original)}><span>{row.original.resource_name}</span><small>{row.original.resource_type.split('/').slice(-1)[0]}</small></button>
    },
    {
      accessorKey:'rule_id',
      header:'Finding',
      cell:({row})=><div><span>{label(row.original.rule_id)}</span><small className={`severity ${row.original.severity.toLowerCase()}`}>{row.original.severity}</small></div>
    },
    {
      accessorKey:'resource_group',
      header:'Resource group',
      cell:({row})=><div><span>{row.original.resource_group}</span><small className="mono">{row.original.subscription_id.slice(0,12)}…</small></div>
    },
    {
      accessorKey:'estimated_monthly_waste_usd',
      header:'Monthly waste',
      cell:({row})=>{
        const conf=row.original.cost_attribution?.confidence||'UNKNOWN';
        return <div>
          <span className="amount">{money(row.original.estimated_monthly_waste_usd)}</span>
          <span className={`confidence-badge ${conf.toLowerCase()}`} title={`Pricing confidence: ${conf}`}>{conf}</span>
        </div>;
      }
    },
    {
      id:'realizable_savings',
      header:'Net realizable',
      cell:({row})=>{
        const realizable=row.original.cost_attribution?.realizable_savings_usd;
        return <span className="realizable-val">{money(realizable)}</span>;
      }
    }
  ],[onSelect]);

  const table=useReactTable({data:filtered,columns,state:{sorting},onSortingChange:setSorting,getCoreRowModel:getCoreRowModel(),getSortedRowModel:getSortedRowModel()});
  const scroll=useRef<HTMLDivElement>(null);
  const {rows}=table.getRowModel();
  const virtual=useVirtualizer({count:rows.length,getScrollElement:()=>scroll.current,estimateSize:()=>82,overscan:8});
  const items=virtual.getVirtualItems();

  return <section className="panel inventory" id="findings" aria-labelledby="findings-title">
    <div className="section-title">
      <div>
        <h2 id="findings-title">Resource findings <span className="count">{findings.length.toLocaleString()}</span></h2>
        <p>Resource signals for review. Missing pricing evidence remains unknown.</p>
      </div>
    </div>
    <div className="filters">
      <label className="search">
        <span className="sr-only">Search resources</span>
        <input type="search" placeholder="Search resource, group or subscription…" value={query} onChange={e=>setQuery(e.target.value)}/>
      </label>
      <label>
        <span className="sr-only">Filter by finding</span>
        <select value={rule} onChange={e=>setRule(e.target.value)}>
          <option value="">All findings</option>
          {[...new Set(findings.map(f=>f.rule_id))].sort().map(r=><option key={r} value={r}>{label(r)}</option>)}
        </select>
      </label>
      <label>
        <span className="sr-only">Filter by severity</span>
        <select value={severity} onChange={e=>setSeverity(e.target.value)}>
          <option value="">All severities</option>
          {[...new Set(findings.map(f=>f.severity))].sort().map(s=><option key={s}>{s}</option>)}
        </select>
      </label>
    </div>
    <div ref={scroll} className="table-scroll">
      <table>
        <thead>
          {table.getHeaderGroups().map(group=><tr key={group.id}>{group.headers.map(header=><th key={header.id}><button onClick={header.column.getToggleSortingHandler()}>{flexRender(header.column.columnDef.header,header.getContext())} <span aria-hidden="true">{header.column.getIsSorted()==='asc'?'↑':header.column.getIsSorted()==='desc'?'↓':'↕'}</span></button></th>)}</tr>)}
        </thead>
        <tbody>
          {items.length>0&&<tr aria-hidden="true"><td colSpan={5} style={{height:items[0].start,padding:0,border:0}}/></tr>}
          {items.map(item=>{const row=rows[item.index];return <tr key={row.id} style={{height:82}}>{row.getVisibleCells().map(cell=><td key={cell.id}>{flexRender(cell.column.columnDef.cell,cell.getContext())}</td>)}</tr>;})}
          {items.length>0&&<tr aria-hidden="true"><td colSpan={5} style={{height:virtual.getTotalSize()-items[items.length-1].end,padding:0,border:0}}/></tr>}
          {!filtered.length&&<tr><td colSpan={5} className="empty">{findings.length?'No resources match these filters.':'No findings in this scan.'}</td></tr>}
        </tbody>
      </table>
    </div>
    <div className="table-footer">{filtered.length.toLocaleString()} matching resources <span>Virtualized inventory · pricing evidence status</span></div>
  </section>;
}

export default function Dashboard(){
  const [accessKey,setAccessKey]=useState('');
  const checkoutKey=useRef<string|null>(null);
  const [key,setKey]=useState('');
  const [workspace,setWorkspace]=useState<Workspace|null>(null);
  const [scans,setScans]=useState<Scan[]>([]);
  const [selected,setSelected]=useState<string>('');
  const [error,setError]=useState('');
  const [busy,setBusy]=useState('');
  const [detail,setDetail]=useState<Finding|null>(null);

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
  const distribution=useMemo(()=>{
    const counts:Record<string,number>={};
    for(const f of scan?.findings||[])counts[f.rule_id]=(counts[f.rule_id]||0)+1;
    return Object.entries(counts).sort((a,b)=>b[1]-a[1]);
  },[scan]);

  async function connect(event:React.FormEvent){
    event.preventDefault();
    setBusy('Connecting');
    setError('');
    try{
      const token=accessKey.trim();
      const me=await request<Workspace>('/me',token);
      const history=await request<Scan[]>('/scans',token);
      setWorkspace(me);
      setKey(token);
      setAccessKey('');
      setScans(history);
      setSelected(history[0]?.scan_id||'');
    }catch(e){
      setError(e instanceof Error?e.message:'Unable to connect');
    }finally{
      setBusy('');
    }
  }

  async function run(){
    setBusy('Scanning Azure');
    setError('');
    setDetail(null);
    try{
      const result=await request<Scan>('/scans',key,'POST');
      setScans(previous=>[result,...previous]);
      setSelected(result.scan_id);
    }catch(e){
      setError(e instanceof Error?e.message:'Scan failed');
    }finally{
      setBusy('');
    }
  }

  async function refresh(){
    setBusy('Refreshing');
    setError('');
    try{
      const history=await request<Scan[]>('/scans',key);
      setScans(history);
      setSelected(history[0]?.scan_id||'');
      setDetail(null);
    }catch(e){
      setError(e instanceof Error?e.message:'Refresh failed');
    }finally{
      setBusy('');
    }
  }

  async function upgradePlan(){
    setBusy('Initiating Stripe checkout');
    setError('');
    try{
      const result=await request<{checkout_url:string}>('/billing/checkout',key,'POST',{
        target_tier:'GROWTH',
        idempotency_key:(checkoutKey.current ||= crypto.randomUUID())
      });
      if(result.checkout_url)window.open(result.checkout_url,'_blank');
    }catch(e){
      setError(e instanceof Error?e.message:'Checkout initiation failed');
    }finally{
      setBusy('');
    }
  }

  function signout(){
    checkoutKey.current=null;
    setWorkspace(null);
    setKey('');
    setScans([]);
    setSelected('');
    setDetail(null);
    setError('');
  }

  function download(){
    if(!scan)return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(scan,null,2)],{type:'application/json'}));
    const a=document.createElement('a');
    a.href=url;
    a.download=`cloudsaver-${scan.scan_id}.json`;
    a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

  function downloadCSV(){
    if(!scan)return;
    const fields=['rule_id','severity','resource_name','resource_type','resource_group','subscription_id','resource_id','estimated_monthly_waste_usd','details'] as const;
    const cell=(value:unknown)=>{let text=String(value??'');if(/^[\s]*[=+@\-]|^[\t\r\n]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';};
    const csv=[fields.join(','),...scan.findings.map(f=>fields.map(field=>cell(f[field])).join(','))].join('\r\n');
    const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));
    const a=document.createElement('a');
    a.href=url;
    a.download=`cloudsaver-${scan.scan_id}.csv`;
    a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

  async function remediationBash(){
    if(!scan||!detail)return;
    setBusy('Generating bash script');
    setError('');
    try{
      const result=await request<{script:string;filename:string}>(`/scans/${scan.scan_id}/remediation`,key,'POST',{resource_ids:[detail.resource_id]});
      const url=URL.createObjectURL(new Blob([result.script],{type:'text/plain'}));
      const a=document.createElement('a');
      a.href=url;
      a.download=result.filename;
      a.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(e){
      setError(e instanceof Error?e.message:'Bash script generation failed');
    }finally{
      setBusy('');
    }
  }

  async function remediationTerraform(){
    if(!scan||!detail)return;
    setBusy('Generating Terraform IaC');
    setError('');
    try{
      const result=await request<{hcl:string;filename:string}>(`/scans/${scan.scan_id}/remediation-terraform`,key,'POST',{resource_ids:[detail.resource_id]});
      const url=URL.createObjectURL(new Blob([result.hcl],{type:'text/plain'}));
      const a=document.createElement('a');
      a.href=url;
      a.download=result.filename;
      a.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(e){
      setError(e instanceof Error?e.message:'Terraform export failed');
    }finally{
      setBusy('');
    }
  }

  const currentTier=(workspace?.plan_tier||'STARTER').toUpperCase();
  const canAdmin=workspace?.roles?.includes('TenantAdmin');
  const canBill=canAdmin||workspace?.roles?.includes('BillingAdmin');

  return <div className="shell">
    <aside className="sidebar">
      <a className="brand" href="#overview"><span className="brand-mark">C<span>↗</span></span>CloudSaver</a>
      <div className="workspace-label">ENTERPRISE FINOPS</div>
      <nav aria-label="Primary">
        <a className="active" href="#overview"><span>◫</span>Overview</a>
        <a href="#findings"><span>▤</span>Resource findings</a>
        <a href="#history"><span>↺</span>Scan history</a>
      </nav>
      <div className="sidebar-bottom">
        <div className="shield">✓</div>
        <strong>Read-only by design</strong>
        <p>Declarative Terraform & Bash exports. Zero automatic destruction.</p>
        <div className="version">DEVELOPMENT RELEASE <span>v0.4.1</span></div>
      </div>
    </aside>

    <main id="overview">
      <header className="topbar">
        <span>Workspace <span className="slash">/</span> <strong>{workspace?.name||'Connect your workspace'}</strong></span>
        {workspace&&<span className={`tier-badge ${currentTier.toLowerCase()}`}>{currentTier} PLAN</span>}
        {workspace&&<span className="quota-tag">{workspace.subscription_ids.length} / {workspace.max_subscriptions||2} Subscriptions</span>}
        {workspace&&canBill&&currentTier==='STARTER'&&<button className="btn-upgrade" onClick={upgradePlan} disabled={!!busy}>Upgrade to Growth ↗</button>}
        <span className={`mode ${workspace?.mode==='azure'?'live':''}`}>{workspace?(workspace.mode==='demo'?'Demo data':'Azure live mode'):'Local workspace'}</span>
        {workspace&&<button className="text-button" onClick={signout} disabled={!!busy}>Disconnect</button>}
      </header>

      <div className="content">
        <div className="heading">
          <div>
            <div className="eyebrow">AZURE RESOURCE REVIEW</div>
            <h1>Understand cloud waste.<br className="mobile-break"/> Review the evidence.</h1>
            <p>Review resource signals, available retail price evidence and export scripts for independent review.</p>
          </div>
          {workspace&&canAdmin&&<div className="actions">
            <Button onClick={run} disabled={!!busy} className="primary">{busy==='Scanning Azure'?'Scanning…':'+ Run new scan'}</Button>
          </div>}
        </div>

        {error&&<div role="alert" className="error"><strong>Something needs attention.</strong> {error}</div>}
        <div className="sr-only" role="status" aria-live="polite">{busy}</div>

        {!workspace?<section className="connect-grid">
          <div className="connect-copy">
            <span className="pill">AUTHENTICATED WORKSPACE</span>
            <h2>Enterprise Cloud Waste<br/>Remediation at Scale.</h2>
            <p>Access subscriptions provisioned by your operator to review unattached disks, idle public IPs and stopped VMs.</p>
            <ul>
              <li><span>01</span>Azure Resource Graph (ARG) high-speed query</li>
              <li><span>02</span>Exact retail meter evidence where available</li>
              <li><span>03</span>Terraform 1.5+ import review exports</li>
            </ul>
            <div className="connect-decoration" aria-hidden="true"><span>RESOURCES</span><div/><div/><div/><i>↗</i></div>
          </div>

          <form onSubmit={connect} className="connect-form panel">
            <div className="icon-box">↗</div>
            <h2>Connect your workspace</h2>
            <p>Use the authentication mode configured by your operator.</p>

            <p>Use an operator-issued workspace key, or an access token from your configured Entra application. Interactive sign-in is not configured here.</p>

            <label htmlFor="access-key">Workspace access key or Entra Bearer token</label>
            <input id="access-key" type="password" autoComplete="off" placeholder="Paste access key or JWT token" value={accessKey} onChange={e=>setAccessKey(e.target.value)} required disabled={!!busy}/>
            <Button className="primary" type="submit" disabled={!!busy||!accessKey.trim()}>{busy?'Connecting…':'Connect workspace →'}</Button>
            <p className="security-note">Credentials remain in browser memory and clear when you disconnect or reload.</p>
          </form>
        </section>:<>
          {workspace.mode==='demo'&&<div className="demo-notice"><span>DEMO WORKSPACE</span> Findings and dollar amounts are illustrative fixtures. They do not call Azure.</div>}

          <section className="stats" aria-label="Scan metrics">
            <article className="stat featured">
              <div className="stat-label">Monthly retail estimate<span>↗</span></div>
              <strong>{scan?money(scan.total_monthly_waste_usd):'—'}</strong>
              <p>{scan?.mode==='demo'?'Illustrative demo amounts · USD / month':'Retail estimates where supported'}</p>
            </article>

            <article className="stat savings">
              <div className="stat-label">Net savings estimate<span>✓</span></div>
              <strong className="realizable-val">{scan?money(scan.realizable_monthly_savings_usd):'—'}</strong>
              <p>Requires billing, retention and remediation evidence</p>
            </article>

            <article className="stat">
              <div className="stat-label">Resources to review<span>▤</span></div>
              <strong>{scan?scan.total_items_found.toLocaleString():'—'}</strong>
              <p>{scan?'Identified waste signals':'Run a scan to get started'}</p>
            </article>

            <article className="stat">
              <div className="stat-label">Subscriptions & Tier<span>◈</span></div>
              <strong>{workspace.subscription_ids.length} <small style={{fontSize:14,color:'#888'}}>/ {workspace.max_subscriptions||2}</small></strong>
              <p>{currentTier} plan · {workspace.mode==='demo'?'Demo Mode':'Azure Live'}</p>
            </article>
          </section>

          <div className="overview-grid">
            <section className="panel breakdown">
              <div className="section-title">
                <div><h2>Where to look first</h2><p>Findings by resource signal</p></div>
                <span className="small-label">{scan?'SELECTED SCAN':'AWAITING SCAN'}</span>
              </div>
              {distribution.length?distribution.map(([rule,count])=><div className="breakdown-row" key={rule}>
                <div><span>{label(rule)}</span><strong>{count.toLocaleString()}</strong></div>
                <div className="bar"><i style={{width:`${count/(scan?.total_items_found||1)*100}%`}}/></div>
              </div>):<div className="empty">{scan?'No waste signals detected in this scan.':'Your resource breakdown will appear after a scan.'}</div>}
            </section>

            <section className="panel scan-info">
              <div className="section-title"><h2>Scan snapshot & status</h2><span className="status-dot"/></div>
              <dl>
                <div><dt>Status</dt><dd>{busy==='Scanning Azure'?'Scanning…':scan?scan.status||'Completed':'Ready to scan'}</dd></div>
                <div><dt>Finished</dt><dd>{scan?date(scan.timestamp):'No scans yet'}</dd></div>
                <div><dt>Pricing source</dt><dd>{scan?.mode==='demo'?'Illustrative fixtures':'Exact retail meter where available'}</dd></div>
                <div><dt>Scan ID</dt><dd className="mono">{scan?scan.scan_id.slice(0,8):'—'}</dd></div>
              </dl>
              <p>All remediation actions produce reviewable code artifacts. CloudSaver never destroys infrastructure automatically.</p>
            </section>
          </div>

          {scan?<Inventory key={scan.scan_id} findings={scan.findings} onSelect={setDetail}/>:<section className="panel empty first-scan" id="findings">
            <div className="icon-box">◫</div>
            <h2>Start your FinOps review</h2>
            <p>Scan your configured subscriptions to see resource findings and available pricing evidence.</p>
            <Button onClick={run} className="primary" disabled={!!busy}>Run first scan</Button>
          </section>}

          <section className="panel history" id="history">
            <div className="section-title">
              <div><h2>Scan history</h2><p>Saved results for this workspace</p></div>
              <div className="actions">
                <Button className="secondary" onClick={refresh} disabled={!!busy}>Refresh</Button>
                <Button className="secondary" onClick={download} disabled={!scan||!!busy}>Export JSON ↓</Button>
                <Button className="secondary" onClick={downloadCSV} disabled={!scan||!!busy}>Export CSV ↓</Button>
              </div>
            </div>
            {scans.length?<div className="history-list">{scans.map(item=><button className={`history-item ${item.scan_id===scan?.scan_id?'selected':''}`} key={item.scan_id} onClick={()=>{setSelected(item.scan_id);setDetail(null);}}>
              <span><strong>{date(item.timestamp)}</strong><small className="mono">{item.scan_id.slice(0,8)} · {item.mode}</small></span>
              <span>{item.total_items_found.toLocaleString()} findings</span>
              <span>{item.subscriptions_scanned} subscriptions</span>
              <span className="history-view">{item.scan_id===scan?.scan_id?'Viewing':'View scan →'}</span>
            </button>)}</div>:<p className="empty">No saved scans yet.</p>}
          </section>
        </>}

        <footer>
          <span>CloudSaver <b>·</b> Enterprise Azure FinOps SaaS</span>
          <span>Resource review · Tenant-scoped access · Pricing evidence</span>
        </footer>
      </div>
    </main>

    {detail&&<div className="modal-backdrop" onClick={()=>setDetail(null)}>
      <section className="detail panel" role="dialog" aria-modal="true" aria-labelledby="detail-title" onClick={e=>e.stopPropagation()}>
        <div className="section-title">
          <h2 id="detail-title">Resource evidence & cost attribution</h2>
          <Button className="secondary" onClick={()=>setDetail(null)} autoFocus>Close ×</Button>
        </div>
        <h3>{detail.resource_name}</h3>
        <div>
          <span className={`severity ${detail.severity.toLowerCase()}`}>{detail.severity}</span>
          {detail.cost_attribution&&<span className={`confidence-badge ${detail.cost_attribution.confidence.toLowerCase()}`}>
            CONFIDENCE: {detail.cost_attribution.confidence}
          </span>}
        </div>
        <p>{detail.details}</p>

        <dl>
          {[
            ['Finding',label(detail.rule_id)],
            ['Resource group',detail.resource_group],
            ['Subscription',detail.subscription_id],
            ['Resource ID',detail.resource_id],
            ['Monthly waste',money(detail.estimated_monthly_waste_usd)],
            ['Net savings estimate',money(detail.cost_attribution?.realizable_savings_usd)],
            ['Calculation basis',detail.cost_attribution?.calculation_basis||'No verified price evidence']
          ].map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}
        </dl>

        <p className="security-note">Terraform exports contain import declarations for review. Independently verify backups and retention before planning any deletion.</p>

        <div className="script-action">
          <p>Download reviewable remediation code to inspect before executing. CloudSaver never runs commands against your cloud.</p>
          <div className="dual-remediation">
            <Button className="secondary" disabled={!!busy||!canAdmin||scan?.mode!=='azure'||!['ORPHANED_DISK','UNASSOCIATED_PUBLIC_IP'].includes(detail.rule_id)} onClick={remediationBash}>
              {busy==='Generating bash script'?'Generating…':'Review Bash Script (.sh) ↓'}
            </Button>
            <Button className="primary" disabled={!!busy||!canAdmin||!workspace?.can_export_terraform||scan?.mode!=='azure'||!['ORPHANED_DISK','UNASSOCIATED_PUBLIC_IP'].includes(detail.rule_id)} onClick={remediationTerraform}>
              {busy==='Generating Terraform IaC'?'Generating…':'Export Terraform import review (.tf) ↓'}
            </Button>
          </div>
        </div>
      </section>
    </div>}
  </div>;
}
