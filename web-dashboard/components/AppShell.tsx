'use client';

import Link from 'next/link';
import {usePathname, useRouter} from 'next/navigation';
import {useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {
  Bell,
  CaretDoubleLeft,
  CaretDoubleRight,
  CaretDown,
  Check,
  ClipboardText,
  Cloud,
  Database,
  FileCode,
  Funnel,
  Eye,
  EyeSlash,
  Gear,
  Layout,
  List,
  Kanban,
  LockKey,
  MagnifyingGlass,
  Pulse,
  SealCheck,
  SignOut,
  SpinnerGap,
  Sparkle,
  SquaresFour,
  Stack,
  Wallet,
  WarningCircle,
  X,
  ArrowRight,
} from '@phosphor-icons/react';
import {api} from '../lib/api';
import {dateTime, providerNames, providerOf, scopeOf, ruleLabel, shortDate} from '../lib/finops';
import {scopeFilterOptions} from '../lib/workspace-scopes';
import {workspaceAtlasNotices} from '../lib/atlas-workspace-notices';
import {atlasNoticeToToast} from '../lib/notices';
import type {Reliability} from '../lib/types';
import {useWorkspace} from './WorkspaceProvider';
import {ThemeToggle, useUiThemePreset} from './ThemeProvider';
import {matchesQuery} from '../lib/resource-insights';
import {Dialog} from './ui/dialog';
import {Notice, ProviderBadge} from './ui/shared';
import {FindingDrawer, ReviewDrawer} from './drawer/FindingDrawer';
import {ClaimView} from './ClaimView';
import {AtlasRouteBoundary} from './atlas/AtlasRouteBoundary';

export const navigation = [
  {href:'/',label:'Overview',icon:Layout,group:'WORKSPACE',shortcut:'G D'},
  {href:'/actions',label:'Action center',icon:Kanban,group:'WORKSPACE'},
  {href:'/resources',label:'Resources',icon:SquaresFour,group:'',shortcut:'G R'},
  {href:'/workloads',label:'Workload assessments',icon:Stack,group:''},
  {href:'/allocation',label:'Cost allocation',icon:Wallet,group:'FINANCE'},
  {href:'/outcomes',label:'Savings & investigations',icon:ClipboardText,group:''},
  {href:'/governance',label:'Risk & compliance',icon:SealCheck,group:'CHANGE & GOVERN'},
  {href:'/automation',label:'Automation & GitOps',icon:FileCode,group:''},
  {href:'/services/disks',label:'Services',icon:Database,group:''},
  {href:'/kubernetes',label:'Kubernetes',icon:SquaresFour,group:'',shortcut:'G K'},
  {href:'/optimization',label:'Optimization evidence',icon:Wallet,group:''},
  {href:'/agents',label:'Agent worker',icon:Sparkle,group:''},
  {href:'/activity',label:'Activity & delivery',icon:Pulse,group:'MANAGE'},
  {href:'/settings',label:'Settings',icon:Gear,group:'',shortcut:'G S'},
];

const specialistHrefs = new Set(['/services/disks', '/kubernetes', '/optimization', '/agents']);
const managementHrefs = new Set(['/activity', '/settings']);
const isCurrentPage = (href: string, pathname: string) =>
  pathname === href
  || (href === '/services/disks' && pathname.startsWith('/services/'))
  || (href === '/resources' && pathname.startsWith('/resources'));

function WorkspaceNavigation({collapsed = false, mobile = false, onNavigate}: {collapsed?: boolean; mobile?: boolean; onNavigate?: () => void}) {
  const pathname = usePathname();
  const activeSpecialist = navigation.some(item => specialistHrefs.has(item.href) && isCurrentPage(item.href, pathname));
  const [toolsOpen, setToolsOpen] = useState(activeSpecialist);
  useEffect(() => {setToolsOpen(activeSpecialist);}, [pathname, activeSpecialist]);
  const toolsId = mobile ? 'mobile-specialist-links' : 'sidebar-specialist-links';
  const link = (item: typeof navigation[number]) => <div key={item.href}>
    {item.group && !collapsed && <div className="nav-group">{item.group}</div>}
    <Link href={item.href} aria-label={item.label} className={`nav-link ${isCurrentPage(item.href, pathname) ? 'active' : ''}`} aria-current={isCurrentPage(item.href, pathname) ? 'page' : undefined} title={collapsed ? item.label : undefined} onClick={onNavigate}>
      <item.icon size={19} weight="regular"/>{!collapsed && <span>{item.label}</span>}
    </Link>
  </div>;
  return <nav aria-label={mobile ? 'Mobile navigation' : 'Primary navigation'}>
    {navigation.filter(item => !specialistHrefs.has(item.href) && !managementHrefs.has(item.href)).map(link)}
    <div className="specialist-navigation">
      <button type="button" className={`nav-link specialist-toggle ${activeSpecialist ? 'specialist-active' : ''}`} aria-label="Specialist tools" title={collapsed ? 'Specialist tools' : undefined} aria-expanded={toolsOpen} aria-controls={toolsId} onClick={() => setToolsOpen(value => !value)}>
        <Stack size={19} weight="regular"/>{!collapsed && <><span>Specialist tools</span><CaretDown size={14} weight="regular" className="specialist-chevron"/></>}
      </button>
      <div id={toolsId} hidden={!toolsOpen}>{navigation.filter(item => specialistHrefs.has(item.href)).map(link)}</div>
    </div>
    {navigation.filter(item => managementHrefs.has(item.href)).map(link)}
  </nav>;
}

function Brand({compact = false}: {compact?: boolean}) {
  return (
    <Link
      href="/"
      className="brand"
      data-atlas-brand=""
      aria-label="CloudSaver overview"
      style={{display: 'inline-flex', alignItems: 'center', gap: '10px', textDecoration: 'none'}}
    >
      <svg className="brand-mark" width="34" height="34" viewBox="0 0 64 64" fill="none" aria-hidden="true" style={{flexShrink: 0}}>
        <rect className="brand-mark-bg" x="2" y="2" width="60" height="60" rx="16" />
        <path
          d="M21 44H18C12.5 44 8 39.5 8 34C8 29.1 11.5 25 16.2 24.1C18.1 17.2 24.4 12 32 12C39.2 12 45.3 16.7 47.4 23.2C52.3 24 56 28.2 56 33.5C56 39.3 51.3 44 45.5 44H31"
          stroke="#FFFFFF"
          strokeWidth="4.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M29 19L31.2 25.8L38 28L31.2 30.2L29 37L26.8 30.2L20 28L26.8 25.8L29 19Z"
          fill="#FFFFFF"
        />
        <path
          d="M21 46L31 35L36.5 40.5L47 29M47 29H39.5M47 29V36.5"
          stroke="#10B981"
          strokeWidth="4.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {!compact && (
        <span style={{fontSize: '18px', fontWeight: 700, letterSpacing: '-0.02em', lineHeight: 1}} className="brand-wordmark">
          <span className="brand-accent">C</span>
          <span className="brand-rest">loud</span>
          <span className="brand-char-accent">S</span>
          <span className="brand-rest">aver</span>
        </span>
      )}
    </Link>
  );
}

function ConnectionForm({switching = false}: {switching?: boolean}) {
  const {connect, busy,error:sessionError} = useWorkspace();
  const [credential, setCredential] = useState('');
  const [credentialVisible, setCredentialVisible] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setError(''); setCredentialVisible(false);
    try {await connect(credential); setCredential('');} catch (cause) {setCredential(''); setError((cause as Error).message);}
  }
  return <form onSubmit={submit} className="connection-form">
    {!switching && <><h1>Connect your workspace</h1><p>Paste your workspace credential to load resources, cost evidence, and reviews.</p></>}
    {switching && <p>Paste another authorized credential. Your current session stays open until the new one is verified.</p>}
    {(error||(!switching&&sessionError)) && <Notice tone="error">{error||sessionError}</Notice>}
    <label htmlFor={switching ? 'switch-key' : 'access-key'}>Workspace credential</label>
    <div className="credential-input"><LockKey size={17} weight="regular"/><input id={switching ? 'switch-key' : 'access-key'} type={credentialVisible ? "text" : "password"} autoComplete="off" autoCapitalize="none" spellCheck={false} value={credential} onChange={event => setCredential(event.target.value)} placeholder="Paste your key or access token" required disabled={!!busy}/><button type="button" className="icon-button credential-visibility" aria-label={credentialVisible ? "Hide credential" : "Show credential"} aria-pressed={credentialVisible} onClick={() => setCredentialVisible(value => !value)} disabled={!!busy}>{credentialVisible ? <EyeSlash size={18}/> : <Eye size={18}/>}</button></div>
    <button className="button primary connection-submit" type="submit" disabled={!!busy || !credential.trim()}>{busy ? <><SpinnerGap className="spin" size={17} weight="regular"/>Verifying…</> : <>Connect workspace<ArrowRight size={17} weight="regular"/></>}</button>
    <div className="connection-security"><SealCheck size={16} weight="regular"/><span>After connecting, your session stays in this tab and signs out after 30 minutes of inactivity.</span></div>
    <details className="connection-help"><summary>Where do I get a credential?</summary><p>Use the key from your workspace administrator, or a delegated token from Microsoft Entra or Keycloak.</p>{!switching && <p>First time? <Link className="text-link" href="/claim">Claim your account</Link> with your onboarding key.</p>}</details>
  </form>;
}

function Login() {
  return <main className="login-page"><section className="login-story"><Brand/><div className="login-story-content"><div><span className="login-kicker"><span/>Cloud cost intelligence</span><h2><span className="login-headline-line">Less cloud waste.</span><span className="login-headline-line">More clarity.</span></h2><p>Discover idle resources, read the evidence, and move from finding to review with confidence.</p><div className="login-providers">{['azure','aws','gcp','kubernetes'].map(p => <ProviderBadge key={p} provider={p}/>)}</div></div></div><div className="login-story-footer"><SealCheck size={15} weight="regular"/> Read-only discovery · Workspace-scoped access</div></section><section className="login-connect"><div className="login-theme"><ThemeToggle/></div><div className="mobile-brand"><Brand/></div><ConnectionForm/><div className="login-footer">CloudSaver · Multi-cloud FinOps workspace</div></section></main>;
}

function CommandPalette() {
  const {overlay, setOverlay, scan} = useWorkspace();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {if (overlay === 'command') {setQuery(''); setActive(0);}}, [overlay]);
  const commands = useMemo(() => {
    const links = navigation.map(item => ({id: item.href, label: item.label, note: 'Navigate', icon: item.icon, action: () => {setOverlay(null); router.push(item.href);}}));
    const explorers = [{id:'storage-view',label:'Explore storage findings',note:'Quick view · disks & volumes',icon:Database,action:()=>{setOverlay(null);router.push('/resources?category=storage');}},{id:'protected-view',label:'Inspect protected resources',note:'Quick view · recovery & retention',icon:SealCheck,action:()=>{setOverlay(null);router.push('/resources?intent=protected');}},{id:'unpriced-view',label:'Find missing price evidence',note:'Quick view · unknown costs',icon:Wallet,action:()=>{setOverlay(null);router.push('/resources?pricing=unknown');}}];
    const resources = query.trim().length >= 2 ? (scan?.findings || []).filter(f => matchesQuery(`${f.resource_name} ${ruleLabel(f.rule_id)} ${f.resource_id} ${f.resource_group} ${scopeOf(f)}`,query)).slice(0,7).map(f => ({id: f.resource_id + f.rule_id, label:f.resource_name,note:ruleLabel(f.rule_id),icon:SquaresFour,action:()=>{setOverlay(null);router.push(`/resources?provider=${providerOf(f)}&resource_id=${encodeURIComponent(f.resource_id)}`);}})) : [];
    return [...links, ...explorers].filter(c => matchesQuery(c.label,query)).concat(resources);
  }, [query, scan, router, setOverlay]);
  useEffect(() => {
    setActive(index => {
      if (!commands.length) return 0;
      return Math.min(index, commands.length - 1);
    });
  }, [commands]);
  useEffect(() => {
    if (!commands.length) return;
    document.getElementById(`command-${active}`)?.scrollIntoView({block: 'nearest'});
  }, [active, commands.length]);
  return <Dialog open={overlay === 'command'} onClose={() => setOverlay(null)} title="Search & commands" className="command-dialog">
    <div className="command-search"><MagnifyingGlass size={20} weight="regular"/><input ref={input} autoFocus placeholder="Search pages, actions, resources…" aria-label="Search commands and resources" role="combobox" aria-expanded="true" aria-controls="command-results" aria-activedescendant={commands[active] ? `command-${active}` : undefined} value={query} onChange={e => {setQuery(e.target.value); setActive(0);}} onKeyDown={e => {if (e.key === 'ArrowDown') {e.preventDefault(); setActive(i => Math.min(i + 1,commands.length - 1));} else if(e.key === 'ArrowUp') {e.preventDefault(); setActive(i => Math.max(0,i - 1));} else if(e.key === 'Enter') {e.preventDefault(); commands[active]?.action();}}}/><kbd>esc</kbd></div>
    <div className="command-results" id="command-results" role="listbox" aria-label="Commands" ref={resultsRef}>{commands.map((command,index) => <button type="button" role="option" aria-selected={index === active} id={`command-${index}`} key={command.id} className={index === active ? 'selected' : ''} onMouseEnter={() => setActive(index)} onClick={command.action}><command.icon size={18} weight="regular"/><span>{command.label}<small>{command.note}</small></span><ArrowRight size={15} weight="regular"/></button>)}{!commands.length && <p className="command-empty">No matching pages or resources.</p>}</div>
    <div className="command-footer"><span><kbd>↑</kbd><kbd>↓</kbd> to navigate</span><span><kbd>↵</kbd> to open</span><span><kbd>esc</kbd> to close</span></div>
  </Dialog>;
}

function KeyNotices() {
  const {workspace, entitlements} = useWorkspace();
  const [dismissed, setDismissed] = useState('');
  const notices = workspace ? workspaceAtlasNotices(workspace, entitlements) : [];
  const billing = notices.find(n => n.id.startsWith('billing:'));
  const dismissKey = billing ? `cloudsaver:billing-banner:${billing.id}` : '';

  useEffect(() => {
    try {
      setDismissed(dismissKey && sessionStorage.getItem(dismissKey) ? dismissKey : '');
    } catch {}
  }, [dismissKey]);

  if (!workspace) return null;

  return <>
    {billing && dismissed !== dismissKey && (
      <div className="notice notice-warning billing-banner atlas-notice-banner" role="status">
        <WarningCircle size={17} weight="regular"/>
        <div>{billing.description}</div>
        <button type="button"
          className="icon-button"
          aria-label="Dismiss billing notice"
          onClick={() => {
            setDismissed(dismissKey);
            try {
              sessionStorage.setItem(dismissKey, '1');
            } catch {}
          }}
        >
          <X size={16} weight="regular"/>
        </button>
      </div>
    )}
    {notices
      .filter(n => !n.id.startsWith('billing:'))
      .map(n => {
        const toast = atlasNoticeToToast(n);
        return <Notice key={n.id} tone={toast.tone}>{toast.text}</Notice>;
      })}
  </>;
}

export function AppShell({children}: {children: ReactNode}) {
  const context = useWorkspace();
  const {workspace,scan,scans,scope,setScope,token,canAdmin,overlay,setOverlay,selection,openReview,busy,scanActivity,disconnect,selectScan,notice,clearNotice} = context;
  const scopeOptions = useMemo(() => scopeFilterOptions(workspace, scan), [workspace, scan]);
  const uiPreset = useUiThemePreset();
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
      if (document.querySelector('dialog[open]') && overlay !== 'command') return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {e.preventDefault(); if (!overlay || overlay === 'command') setOverlay(overlay ? null : 'command'); return;}
      if (overlay || (e.target as HTMLElement).closest('input:not([type="checkbox"]):not([type="radio"]),textarea,select,[contenteditable="true"]')) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.shiftKey && e.key.toLowerCase() === 'r' && canAdmin && selection.length) {e.preventDefault(); openReview(selection); return;}
      const key = e.key.toLowerCase();
      if (prefix.current.key === 'g' && Date.now() - prefix.current.at < 900) {const target = ({d:'/',c:'/actions',r:'/resources',k:'/kubernetes',a:'/agents',s:'/settings'} as Record<string, string>)[key]; if (target) {e.preventDefault(); router.push(target);} prefix.current.key = '';}
      else prefix.current = {key,at:Date.now()};
    };
    document.addEventListener('keydown',handler);return () => document.removeEventListener('keydown',handler);
  }, [workspace,overlay,selection,openReview,setOverlay,router,canAdmin]);
  useEffect(() => {
    if (!token) {setReliability(null); return;}
    const controller = new AbortController();
    let active = true;
    setReliability(null);
    const load = () => {if (!document.hidden) api<Reliability>('/operations/reliability',token,{signal:controller.signal})
      .then(value => {if (active) setReliability(value);})
      .catch(() => {if (active && !controller.signal.aborted) setReliability(null);});};
    load(); const timer = setInterval(load,30000);
    return () => {active = false;controller.abort();clearInterval(timer);};
  }, [token]);
  if (!workspace) return pathname === '/claim' ? <ClaimView/> : <Login/>;
  const active = navigation.find(item => isCurrentPage(item.href, pathname)) || navigation[0];
  const failures = reliability?.counts.filter(c => c.status === 'dead_letter').reduce((sum,c) => sum + c.count,0) || 0;
  const sessionIsHuman = workspace.subject_type === 'user' && !workspace.key_id;
  const sessionLabel = sessionIsHuman ? 'Human session' : 'API key session';
  const sessionTitle = sessionIsHuman
    ? 'Signed in as a verified user. Human approval flows are available where your workspace permits them.'
    : 'Signed in with a read/scoped workspace key. Actions that require an interactive human approval step are not available for this credential type.';
  const nav = <><Brand compact={collapsed}/><WorkspaceNavigation collapsed={collapsed}/><div className="sidebar-bottom"><button type="button" className="collapse-control" onClick={() => {const value = !collapsed;setCollapsed(value);try {localStorage.setItem('cloudsaver:ui:sidebar',value ? 'collapsed' : 'expanded');} catch {}}} aria-label={collapsed ? 'Expand navigation' : 'Collapse sidebar'}>{collapsed ? <CaretDoubleRight size={17} weight="regular"/> : <><CaretDoubleLeft size={17} weight="regular"/><span>Collapse sidebar</span></>}</button></div></>;
  return <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''} ${uiPreset === 'atlas' ? 'ui-preset-atlas' : ''}`}>
    <a href="#main-content" className="skip-link">Skip to content</a>
    <aside className="sidebar">{nav}</aside>
    <div className="app-main"><header className="topbar"><div className="topbar-left"><button type="button" className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><List size={20} weight="regular"/></button><details className="workspace-menu"><summary><span className="workspace-avatar">{workspace.name.slice(0,1).toUpperCase()}</span><span>{workspace.name}<small>{context.planName} plan</small></span><CaretDown size={14} weight="regular"/></summary><div className="menu-surface"><Link href="/settings"><Gear size={16} weight="regular"/>Workspace settings</Link><button type="button" data-discard-policy-draft onClick={() => setOverlay('workspace')}><Cloud size={16} weight="regular"/>Connect another workspace</button><button type="button" onClick={disconnect}><SignOut size={16} weight="regular"/>Disconnect</button></div></details><span className="topbar-divider"/><span className="current-page">{active.label}</span></div><div className="topbar-actions"><span className="session-role" title={sessionTitle}>{sessionLabel}</span><ThemeToggle/><button type="button" className="command-trigger" aria-keyshortcuts="Control+k Meta+k" title="Search pages and findings" onClick={() => setOverlay('command')} ><MagnifyingGlass size={16} weight="regular"/><span>Search</span><kbd aria-hidden="true">Ctrl/⌘ K</kbd></button><button type="button" className="icon-button notification-trigger" aria-label={`Notifications${failures ? `, ${failures} deliveries need attention` : ''}`} onClick={() => setOverlay('notifications')}><Bell size={19} weight="regular"/>{failures > 0 && <span className="notification-dot"/>}</button></div>    </header>
      {uiPreset === 'atlas' && (
        <div className="atlas-workspace-strip" role="status">
          <span className="atlas-strip-label">Atlas enterprise</span>
          <span className="atlas-strip-divider" aria-hidden="true"/>
          <span>{workspace.name}</span>
          <span className="atlas-strip-muted">{context.planName} plan</span>
          <span className="atlas-strip-muted">{workspace.configured_scope_count ?? workspace.subscription_ids.length} authorized scopes</span>
        </div>
      )}
      <div className="scope-toolbar"><div className="scope-context"><details className="scope-picker"><summary><Funnel size={13} weight="regular"/>{scope.length ? `${scope.length} scope${scope.length > 1 ? 's' : ''}` : 'All scopes'}<CaretDown size={13} weight="regular"/></summary><div className="menu-surface"><div className="section-title"><strong>Filter resources by scope</strong><button type="button" className="text-button" onClick={() => setScope([])} disabled={!scope.length}>Clear scope filter</button></div>{scopeOptions.length ? scopeOptions.map(id => {const configuredOnly = (workspace.subscription_ids || []).includes(id) && !(scan?.findings || []).some(f => scopeOf(f) === id); return <label key={id}><input type="checkbox" aria-label={id} checked={scope.includes(id)} onChange={() => setScope(scope.includes(id) ? scope.filter(s => s !== id) : [...scope, id])}/><span title={id}>{id}{configuredOnly ? <small className="scope-awaiting-scan"> · awaiting inventory refresh</small> : null}</span></label>;}) : <p>No scopes configured yet. Add subscriptions in workspace settings; inventory refreshes automatically when evidence is stale.</p>}</div></details></div><div className="snapshot-selector"><span>Snapshot</span><select aria-label="Selected scan snapshot" value={scan?.scan_id || ''} disabled={!scans.length} onChange={e => selectScan(e.target.value)}>{!scans.length && <option value="">No scans yet</option>}{scans.map(s => <option key={s.scan_id} value={s.scan_id}>{dateTime(s.timestamp)} · {s.scan_id.slice(0,8)}</option>)}</select></div></div>
      <main id="main-content" tabIndex={-1} className="page-content"><KeyNotices/>{scan?.data_origin === 'legacy_synthetic' && <Notice tone="warning">Historical synthetic snapshot. Illustrative prices are hidden and code export is unavailable.</Notice>}{!!scanActivity && <div className="workspace-progress scan-activity" role="status"><SpinnerGap size={15} weight="regular" className="spin"/>{scanActivity}<span>Inventory saves as the scan runs. Other pages stay available.</span></div>}{!!busy && <div className="workspace-progress" role="status"><SpinnerGap size={15} weight="regular" className="spin"/>{busy}<span>Keep this workspace open while the request completes.</span></div>}<AtlasRouteBoundary>{children}</AtlasRouteBoundary></main>
      <footer className="app-footer"><span><span className="footer-brand">CloudSaver</span>Multi-cloud FinOps</span><span><SealCheck size={13} weight="regular"/>Evidence before action</span></footer>
    </div>
    <FindingDrawer/><ReviewDrawer/><CommandPalette/>
    <Dialog open={overlay === 'workspace'} onClose={() => setOverlay(null)} title="Connect another workspace"><div className="dialog-content"><ConnectionForm switching/></div></Dialog>
    <Dialog open={overlay === 'notifications'} onClose={() => setOverlay(null)} title="Workspace notifications" drawer><div className="dialog-content">{failures ? <><Notice tone="warning">{failures} delivery event{failures === 1 ? '' : 's'} need attention.</Notice><p>Inspect delivery failures and their audit history before choosing a replay.</p></> : <div className="notifications-empty"><Bell size={28} weight="regular"/><h3>{reliability ? 'No failed deliveries' : 'Status not available'}</h3><p>{reliability ? 'No failed deliveries were reported at the last refresh.' : 'Open Activity to inspect operational state.'}</p></div>}<Link className="button secondary" href="/activity" onClick={() => setOverlay(null)}>Open activity<ArrowRight size={16} weight="regular"/></Link></div></Dialog>
    <Dialog open={mobileOpen} onClose={() => setMobileOpen(false)} title="Navigation" className="mobile-navigation"><WorkspaceNavigation mobile onNavigate={() => setMobileOpen(false)}/></Dialog>
    {notice && <div className={`toast toast-${notice.tone}`} role={notice.tone === 'error' ? 'alert' : 'status'}><span>{notice.tone === 'success' ? <Check size={17} weight="regular"/> : <Bell size={17} weight="regular"/>}</span><p>{notice.text}</p><button type="button" className="icon-button" aria-label="Dismiss notification" onClick={clearNotice}><X size={16} weight="regular"/></button></div>}
  </div>;
}
