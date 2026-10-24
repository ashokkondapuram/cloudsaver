'use client';

import Link from 'next/link';
import {usePathname, useRouter} from 'next/navigation';
import {useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {AlertCircle, BrainCircuit, Database, Activity, ArrowDown, ArrowRight, Bell, Blocks, Check, ChevronDown, ChevronsLeft, ChevronsRight, Cloud, Command, ExternalLink, FileCode2, Filter, LayoutDashboard, Loader2, LockKeyhole, LogOut, Menu, Plus, Search, Settings2, ShieldCheck, Sparkles, Wallet, X} from 'lucide-react';
import {api} from '../lib/api';
import {dateTime, providerNames, scopeOf, ruleLabel, shortDate} from '../lib/finops';
import {billingBanner} from '../lib/plan';
import type {Reliability} from '../lib/types';
import {useWorkspace} from './WorkspaceProvider';
import {ThemeToggle} from './ThemeProvider';
import {matchesQuery} from '../lib/resource-insights';
import {Dialog} from './ui/dialog';
import {Notice, ProviderBadge} from './ui/shared';
import {FindingDrawer, ReviewDrawer} from './drawer/FindingDrawer';
import {ClaimView} from './ClaimView';

export const navigation = [
  {href: '/', label: 'Overview', icon: LayoutDashboard, group: 'WORKSPACE', shortcut: 'G D'},
  {href: '/findings', label: 'Inventory & findings', icon: Blocks, group: '', shortcut: 'G F'},
  {href: '/resources', label: 'Resource analysis', icon: BrainCircuit, group: '', shortcut: 'G R'},
  {href: '/kubernetes', label: 'Kubernetes & containers', icon: Blocks, group: ''},
  {href: '/services/disks', label: 'Service analysis', icon: Database, group: ''},
  {href: '/allocation', label: 'Cost allocation', icon: Wallet, group: ''},
  {href: '/automation', label: 'Automation', icon: FileCode2, group: 'GOVERNANCE'},
  {href: '/activity', label: 'Activity & delivery', icon: Activity, group: ''},
  {href: '/settings', label: 'Settings & integrations', icon: Settings2, group: 'MANAGE'},
  {href: '/settings/rules', label: 'Analysis rules', icon: ShieldCheck, group: ''},
  {href: '/settings/organization', label: 'People & access', icon: LockKeyhole, group: ''},
];

function Brand({compact = false}: {compact?: boolean}) {
  return <Link href="/" className="brand" aria-label={compact ? 'CloudSaver overview' : undefined}><span className="brand-symbol"><Cloud size={22}/><span/></span>{!compact && <span>CloudSaver<small aria-hidden="true">FINOPS WORKSPACE</small></span>}</Link>;
}

function ConnectionForm({switching = false}: {switching?: boolean}) {
  const {connect, busy} = useWorkspace();
  const [credential, setCredential] = useState('');
  const [error, setError] = useState('');
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setError('');
    try {await connect(credential); setCredential('');} catch (cause) {setCredential(''); setError((cause as Error).message);}
  }
  return <form onSubmit={submit} className="connection-form">
    {!switching && <><span className="pretitle">YOUR CLOUD. A CLEARER PICTURE.</span><h1>Connect your workspace</h1><p>Bring your cloud resources, cost evidence, and review workflows into focus.</p></>}
    {switching && <p>Connect with another authorized workspace credential. Your current workspace stays open until the new connection is verified.</p>}
    {error && <Notice tone="error">{error}</Notice>}
    <label htmlFor={switching ? 'switch-key' : 'access-key'}>Workspace access key or Entra Bearer token</label>
    <div className="credential-input"><LockKeyhole size={17}/><input id={switching ? 'switch-key' : 'access-key'} type="password" autoComplete="off" value={credential} onChange={event => setCredential(event.target.value)} placeholder="Paste your workspace credential" required disabled={!!busy}/></div>
    <button className="button primary connection-submit" type="submit" disabled={!!busy || !credential.trim()}>{busy ? <><Loader2 className="spin" size={17}/>Verifying workspace…</> : <>Connect workspace<ArrowRight size={17}/></>}</button>
    <div className="connection-security"><ShieldCheck size={16}/><span>Your session stays signed in across reloads in this tab and signs out automatically after 30 minutes of inactivity.</span></div>
    <details className="connection-help"><summary>Where do I get a credential?</summary><p>Use the key issued by your workspace administrator, or a delegated access token from your organization’s configured Microsoft Entra application.</p>{!switching && <p>Setting up your organization for the first time? <Link className="text-link" href="/claim">Claim your account</Link> with the onboarding key from your platform operator.</p>}</details>
  </form>;
}

function Login() {
  return <div className="login-page"><section className="login-story"><Brand/><div className="login-story-content"><span className="login-kicker"><span/>CLOUD COST INTELLIGENCE</span><h2>Less cloud waste.<br/>More clarity.</h2><p>A focused workspace to discover idle resources, understand the evidence, and move confidently from finding to review.</p><div className="login-flow"><div><span>01</span><Cloud size={20}/><strong>Connect</strong><small>Your authorized cloud scopes</small></div><ArrowRight size={18}/><div><span>02</span><Search size={20}/><strong>Discover</strong><small>Resource signals & cost evidence</small></div><ArrowRight size={18}/><div><span>03</span><ShieldCheck size={20}/><strong>Review</strong><small>Code you can inspect first</small></div></div><div className="login-providers">{['azure','aws','gcp','kubernetes'].map(p => <ProviderBadge key={p} provider={p}/>)}</div></div><div className="login-story-footer"><ShieldCheck size={15}/> Read-only discovery <span/> Workspace-scoped access</div></section><section className="login-connect"><div className="login-theme"><ThemeToggle/></div><div className="mobile-brand"><Brand/></div><ConnectionForm/><div className="login-footer">CloudSaver <span>·</span> Multi-cloud FinOps workspace</div></section></div>;
}

function CommandPalette() {
  const {overlay, setOverlay, scan, openFinding, canAdmin} = useWorkspace();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {if (overlay === 'command') {setQuery(''); setActive(0);}}, [overlay]);
  const commands = useMemo(() => {
    const links = navigation.map(item => ({id: item.href, label: item.label, note: 'Navigate', icon: item.icon, action: () => {setOverlay(null); router.push(item.href);}}));
    const explorers = [{id:'storage-view',label:'Explore storage findings',note:'Quick view · disks & volumes',icon:Database,action:()=>{setOverlay(null);router.push('/findings?category=storage');}},{id:'protected-view',label:'Inspect protected resources',note:'Quick view · recovery & retention',icon:ShieldCheck,action:()=>{setOverlay(null);router.push('/findings?intent=protected');}},{id:'unpriced-view',label:'Find missing price evidence',note:'Quick view · unknown costs',icon:Wallet,action:()=>{setOverlay(null);router.push('/findings?pricing=unknown');}}];
    const actions = canAdmin ? [{id:'new-scan',label:'Run a new scan',note:'Action',icon:Plus,action:()=>setOverlay('scan')}] : [];
    const resources = query.trim().length >= 2 ? (scan?.findings || []).filter(f => matchesQuery(`${f.resource_name} ${ruleLabel(f.rule_id)} ${f.resource_id} ${f.resource_group} ${scopeOf(f)}`,query)).slice(0,7).map(f => ({id: f.resource_id + f.rule_id, label:f.resource_name,note:ruleLabel(f.rule_id),icon:Blocks,action:()=>openFinding(f)})) : [];
    return [...links, ...explorers, ...actions].filter(c => matchesQuery(c.label,query)).concat(resources);
  }, [query, scan, canAdmin, router, setOverlay, openFinding]);
  return <Dialog open={overlay === 'command'} onClose={() => setOverlay(null)} title="Search & commands" className="command-dialog">
    <div className="command-search"><Search size={20}/><input ref={input} autoFocus placeholder="Search pages, actions, or resources…" aria-label="Search commands and resources" role="combobox" aria-expanded="true" aria-controls="command-results" aria-activedescendant={commands[active] ? `command-${active}` : undefined} value={query} onChange={e => {setQuery(e.target.value); setActive(0);}} onKeyDown={e => {if (e.key === 'ArrowDown') {e.preventDefault(); setActive(i => Math.min(i + 1,commands.length - 1));} else if(e.key === 'ArrowUp') {e.preventDefault(); setActive(i => Math.max(0,i - 1));} else if(e.key === 'Enter') {e.preventDefault(); commands[active]?.action();}}}/><kbd>esc</kbd></div>
    <div className="command-results" id="command-results" role="listbox" aria-label="Commands">{commands.map((command,index) => <button type="button" role="option" aria-selected={index === active} id={`command-${index}`} key={command.id} className={index === active ? 'selected' : ''} onMouseEnter={() => setActive(index)} onClick={command.action}><command.icon size={18}/><span>{command.label}<small>{command.note}</small></span><ArrowRight size={15}/></button>)}{!commands.length && <p className="command-empty">No matching pages or resources.</p>}</div>
    <div className="command-footer"><span><kbd>↑</kbd><kbd>↓</kbd> to navigate</span><span><kbd>↵</kbd> to open</span><span><kbd>esc</kbd> to close</span></div>
  </Dialog>;
}

const NO_PROVIDERS = "This workspace key doesn't include any cloud providers. Ask your administrator for a new key.";
const EXPIRY_WARNING_DAYS = 14;

function KeyNotices() {
  const {workspace} = useWorkspace();
  if (!workspace) return null;
  const expires = workspace.key_expires_at ? new Date(workspace.key_expires_at) : null;
  const soon = expires && !Number.isNaN(expires.valueOf()) && expires.getTime() - Date.now() <= EXPIRY_WARNING_DAYS * 86400000;
  return <>
    <BillingBanner/>
    {soon && <Notice tone="warning">This workspace key expires on {shortDate(workspace.key_expires_at!)}. Ask your administrator for a new key.</Notice>}
    {workspace.allowed_providers && !workspace.allowed_providers.length && <Notice tone="warning">{NO_PROVIDERS}</Notice>}
  </>;
}

function BillingBanner() {
  const {entitlements} = useWorkspace();
  const text = billingBanner(entitlements);
  const key = text && entitlements ? `cloudsaver:billing-banner:${entitlements.tenant_id}:${text}` : '';
  const [dismissed,setDismissed] = useState('');
  useEffect(() => {try {setDismissed(key && sessionStorage.getItem(key) ? key : '');} catch {}}, [key]);
  if (!text || dismissed === key) return null;
  return <div className="notice notice-warning billing-banner" role="status"><AlertCircle size={17}/><div>{text}</div><button className="icon-button" aria-label="Dismiss billing notice" onClick={() => {setDismissed(key); try {sessionStorage.setItem(key,'1');} catch {}}}><X size={16}/></button></div>;
}

function ScanDialog() {
  const {overlay,setOverlay,workspace,runScan,busy,entitlements,planName,planProviders} = useWorkspace();
  const [providers,setProviders] = useState<string[]>([]);
  const allowed = planProviders(workspace?.allowed_providers ?? workspace?.providers ?? ['azure']);
  const allowedKey = allowed.join();
  useEffect(() => {if (overlay === 'scan') setProviders(allowedKey ? allowedKey.split(',') : []);}, [overlay,allowedKey]);
  return <Dialog open={overlay === 'scan'} onClose={() => setOverlay(null)} title="Run a resource scan">
    <div className="dialog-content"><p>Choose the cloud providers to scan. CloudSaver reads resources within your authorized workspace scopes.</p>{!allowed.length && <Notice tone="warning">{NO_PROVIDERS}</Notice>}<div className="scan-provider-options">{allowed.map(provider => <label key={provider} className={providers.includes(provider) ? 'chosen' : ''}><input type="checkbox" checked={providers.includes(provider)} onChange={() => setProviders(previous => previous.includes(provider) ? previous.filter(p => p !== provider) : [...previous,provider])}/><ProviderBadge provider={provider}/><span>Read-only inventory</span></label>)}</div><div className="scan-scope-summary"><ShieldCheck size={18}/><div><strong>{workspace?.configured_scope_count ?? workspace?.subscription_ids.length} configured scopes</strong><small>{workspace?.max_scopes_per_scan || entitlements?.max_subscriptions || 'Plan-limited'} scopes per scan · {planName} plan</small></div></div><Notice>Scanning can take a few minutes. Results are saved when the scan completes.</Notice></div>
    <div className="dialog-actions"><button className="button secondary" onClick={() => setOverlay(null)}>Cancel</button><button className="button primary" disabled={!!busy || !providers.length} onClick={() => runScan(providers)}><Search size={16}/>Start scan</button></div>
  </Dialog>;
}

export function AppShell({children}: {children: ReactNode}) {
  const context = useWorkspace();
  const {workspace,scan,scans,scope,setScope,token,canAdmin,overlay,setOverlay,selection,openReview,busy,disconnect,selectScan,notice,clearNotice} = context;
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed,setCollapsed] = useState(false), [mobileOpen,setMobileOpen] = useState(false);
  const [reliability,setReliability] = useState<Reliability | null>(null);
  const prefix = useRef({key:'',at:0});
  useEffect(() => {try {setCollapsed(localStorage.getItem('cloudsaver:ui:sidebar') === 'collapsed');} catch {}}, []);
  useEffect(() => {setMobileOpen(false);}, [pathname]);
  useLayoutEffect(() => {
    if (!workspace) return;
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {e.preventDefault(); if (!overlay || overlay === 'command') setOverlay(overlay ? null : 'command'); return;}
      if (overlay || (e.target as HTMLElement).closest('input:not([type="checkbox"]):not([type="radio"]),textarea,select,[contenteditable="true"]')) return;
      if (e.shiftKey && e.key.toLowerCase() === 'r' && selection.length) {e.preventDefault(); openReview(selection); return;}
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const key = e.key.toLowerCase();
      if (prefix.current.key === 'g' && Date.now() - prefix.current.at < 900) {const target = ({d: '/', f: '/findings', r: '/resources'} as Record<string, string>)[key]; if (target) {e.preventDefault(); router.push(target);} prefix.current.key = '';}
      else prefix.current = {key,at:Date.now()};
    };
    document.addEventListener('keydown',handler);return () => document.removeEventListener('keydown',handler);
  }, [workspace,overlay,selection,openReview,setOverlay,router]);
  useEffect(() => {
    if (!token) {setReliability(null); return;}
    const controller = new AbortController();
    const load = () => {if (!document.hidden) api<Reliability>('/operations/reliability',token,{signal:controller.signal}).then(setReliability).catch(() => {});};
    load(); const timer = setInterval(load,30000);
    return () => {controller.abort();clearInterval(timer);};
  }, [token]);
  if (!workspace) return pathname === '/claim' ? <ClaimView/> : <Login/>;
  const active = navigation.find(item => item.href === pathname) || navigation[0];
  const scopes = [...new Set((scan?.findings || []).map(scopeOf))];
  const failures = reliability?.counts.filter(c => c.status === 'dead_letter').reduce((sum,c) => sum + c.count,0) || 0;
  const nav = <><Brand compact={collapsed}/><nav aria-label="Primary navigation">{navigation.map(item => <div key={item.href}>{item.group && !collapsed && <div className="nav-group">{item.group}</div>}<Link href={item.href} aria-label={collapsed ? item.label : undefined} className={`nav-link ${pathname === item.href ? 'active' : ''}`} aria-current={pathname === item.href ? 'page' : undefined} title={collapsed ? item.label : undefined}><item.icon size={19}/>{!collapsed && <><span>{item.label}</span>{item.href === '/findings' && !!scan?.total_items_found && <small aria-hidden="true">{scan.total_items_found}</small>}</>}</Link></div>)}</nav><div className="sidebar-bottom">{!collapsed && <div className="sidebar-safety"><ShieldCheck size={18}/><div><strong>Read-only discovery</strong><p>Every change starts with review.</p></div></div>}<button className="collapse-control" onClick={() => {const value = !collapsed;setCollapsed(value);try {localStorage.setItem('cloudsaver:ui:sidebar',value ? 'collapsed' : 'expanded');} catch {}}} aria-label={collapsed ? 'Expand navigation' : undefined}>{collapsed ? <ChevronsRight size={17}/> : <><ChevronsLeft size={17}/><span>Collapse sidebar</span><small aria-hidden="true">v1.3.0</small></>}</button></div></>;
  return <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
    <a href="#main-content" className="skip-link">Skip to content</a>
    <aside className="sidebar">{nav}</aside>
    <div className="app-main"><header className="topbar"><div className="topbar-left"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Menu size={20}/></button><details className="workspace-menu"><summary><span className="workspace-avatar">{workspace.name.slice(0,1).toUpperCase()}</span><span>{workspace.name}<small>{context.planName} plan</small></span><ChevronDown size={14}/></summary><div className="menu-surface"><span className="menu-label">CURRENT WORKSPACE</span><strong>{workspace.name}</strong><code>{workspace.tenant_id}</code><button onClick={() => setOverlay('workspace')}><Cloud size={16}/>Connect another workspace</button><button onClick={disconnect}><LogOut size={16}/>Disconnect</button></div></details><span className="topbar-divider"/><span className="current-page">{active.label}</span></div><div className="topbar-actions"><span className="session-role" title={workspace.roles.join(', ')}><ShieldCheck size={13}/>{canAdmin?'Administrator':workspace.roles.includes('BillingAdmin')?'Billing admin':'Viewer'}</span><ThemeToggle/><button className="command-trigger" onClick={() => setOverlay('command')} ><Search size={16}/><span>Search anything…</span><kbd aria-hidden="true">⌘ K</kbd></button><button className="icon-button notification-trigger" aria-label={`Notifications${failures ? `, ${failures} deliveries need attention` : ''}`} onClick={() => setOverlay('notifications')}><Bell size={19}/>{failures > 0 && <span className="notification-dot"/>}</button><details className="profile-menu"><summary aria-label={`Workspace profile ${workspace.name.slice(0,2).toUpperCase()}`}><span className="profile-avatar" aria-hidden="true">{workspace.name.slice(0,2).toUpperCase()}</span></summary><div className="menu-surface"><strong>{workspace.name}</strong><span>{workspace.roles.join(' · ')}</span><Link href="/settings">Workspace settings<ArrowRight size={14}/></Link><button onClick={disconnect}><LogOut size={16}/>Disconnect</button></div></details></div></header>
      <div className="scope-toolbar"><div className="scope-context"><span className="scope-dot"/>Isolated workspace<span className="scope-separator">/</span><details className="scope-picker"><summary><Filter size={13}/>{scope.length ? `${scope.length} selected scope${scope.length > 1 ? 's' : ''}` : 'All scan scopes'}<ChevronDown size={13}/></summary><div className="menu-surface"><div className="section-title"><strong>Filter visible resources</strong><button className="text-button" onClick={() => setScope([])}>Reset</button></div>{scopes.length ? scopes.map(id => <label key={id}><input type="checkbox" checked={scope.includes(id)} onChange={() => setScope(scope.includes(id) ? scope.filter(s => s !== id) : [...scope,id])}/><span title={id}>{id}</span></label>) : <p>No resource scopes in this scan.</p>}</div></details></div><div className="snapshot-selector"><span>Snapshot</span><select aria-label="Selected scan snapshot" value={scan?.scan_id || ''} disabled={!scans.length || !!busy} onChange={e => selectScan(e.target.value)}>{!scans.length && <option value="">No scans yet</option>}{scans.map(s => <option key={s.scan_id} value={s.scan_id}>{dateTime(s.timestamp)} · {s.scan_id.slice(0,8)}</option>)}</select></div></div>
      <main id="main-content" tabIndex={-1} className="page-content"><KeyNotices/>{scan?.data_origin === 'legacy_synthetic' && <Notice tone="warning">Historical synthetic snapshot. Illustrative prices are hidden and code export is unavailable.</Notice>}{!!busy && <div className="workspace-progress" role="status"><Loader2 size={15} className="spin"/>{busy}<span>Keep this workspace open while the request completes.</span></div>}{children}</main>
      <footer className="app-footer"><span><span className="footer-brand">CloudSaver</span>Multi-cloud FinOps</span><span><ShieldCheck size={13}/>Evidence before action</span></footer>
    </div>
    <CommandPalette/><ScanDialog/>
    <Dialog open={overlay === 'workspace'} onClose={() => setOverlay(null)} title="Connect another workspace"><div className="dialog-content"><ConnectionForm switching/></div></Dialog>
    <Dialog open={overlay === 'notifications'} onClose={() => setOverlay(null)} title="Workspace notifications" drawer><div className="dialog-content">{failures ? <><Notice tone="warning">{failures} delivery event{failures === 1 ? '' : 's'} need attention.</Notice><p>Inspect delivery failures and their audit history before choosing a replay.</p></> : <div className="notifications-empty"><Bell size={28}/><h3>{reliability ? 'No failed deliveries' : 'Status not available'}</h3><p>{reliability ? 'No dead-letter deliveries were reported at the last refresh.' : 'Open Activity & delivery to inspect operational state.'}</p></div>}<Link className="button secondary" href="/activity" onClick={() => setOverlay(null)}>Open activity & delivery<ArrowRight size={16}/></Link></div></Dialog>
    <Dialog open={mobileOpen} onClose={() => setMobileOpen(false)} title="Navigation" className="mobile-navigation"><nav aria-label="Mobile navigation">{navigation.map(item => <Link key={item.href} href={item.href} aria-current={pathname === item.href ? 'page' : undefined} onClick={() => setMobileOpen(false)}><item.icon size={20}/>{item.label}</Link>)}</nav></Dialog>
    <FindingDrawer/><ReviewDrawer/>
    {notice && <div className={`toast toast-${notice.tone}`} role={notice.tone === 'error' ? 'alert' : 'status'}><span>{notice.tone === 'success' ? <Check size={17}/> : <Bell size={17}/>}</span><p>{notice.text}</p><button className="icon-button" aria-label="Dismiss notification" onClick={clearNotice}><X size={16}/></button></div>}
  </div>;
}
