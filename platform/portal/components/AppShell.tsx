'use client';

import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {useEffect, type ReactNode} from 'react';
import {Activity, BookOpen, Building2, Cloud, CreditCard, Layers, LayoutGrid, LogOut, Settings2, ShieldAlert, ShieldCheck} from 'lucide-react';
import {environmentDisplayLabel, operatorRoleLabel} from '../lib/labels';
import {useSession} from './SessionProvider';
import {ThemeToggle} from './ThemeProvider';
import {Loading} from './ui/shared';

export const VERSION = '1.0.0';

const navigation = [
  {href: '/customers', label: 'Customers', icon: Building2, group: 'DIRECTORY'},
  {href: '/workspaces', label: 'Workspaces', icon: LayoutGrid, group: ''},
  {href: '/billing', label: 'Billing', icon: CreditCard, group: 'BILLING'},
  {href: '/plans', label: 'Plans', icon: Layers, group: ''},
  {href: '/activity', label: 'Activity', icon: Activity, group: 'OVERSIGHT'},
  {href: '/security', label: 'Security', icon: ShieldAlert, group: ''},
  {href: '/knowledge', label: 'Knowledge', icon: BookOpen, group: ''},
  {href: '/settings', label: 'Platform settings', icon: Settings2, group: 'PLATFORM'},
];

export function Brand() {
  return <Link href="/customers" className="brand"><span className="brand-symbol"><Cloud size={22}/><span/></span><span>CloudSaver<small aria-hidden="true">PLATFORM PORTAL</small></span></Link>;
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]?.toUpperCase()).join('') || 'OP';
}

export function AppShell({children}: {children: ReactNode}) {
  const pathname = usePathname();
  const {session, loading, canWrite, signOut} = useSession();
  const signInPage = pathname === '/sign-in';
  useEffect(() => {
    if (!signInPage && !loading && !session) window.location.assign(`/sign-in?return_to=${encodeURIComponent(pathname)}`);
  }, [signInPage, loading, session, pathname]);

  if (signInPage) return <>{children}</>;
  if (!session) return <main className="signin-page"><Loading label={loading ? 'Checking your session…' : 'Redirecting to sign in…'}/></main>;

  const active = navigation.find(item => pathname === item.href || pathname.startsWith(`${item.href}/`));
  const role = operatorRoleLabel(session);
  return <div className="app-shell">
    <a href="#main-content" className="skip-link">Skip to content</a>
    <aside className="sidebar">
      <Brand/>
      <nav aria-label="Primary navigation">{navigation.map(item => <div key={item.href}>
        {item.group && <div className="nav-group">{item.group}</div>}
        <Link href={item.href} className={`nav-link ${active?.href === item.href ? 'active' : ''}`} aria-current={active?.href === item.href ? 'page' : undefined} title={item.label}><item.icon size={19}/><span>{item.label}</span></Link>
      </div>)}</nav>
      <div className="sidebar-bottom">
        <div className="sidebar-safety"><ShieldCheck size={18}/><div><strong>{canWrite ? 'Operator access' : 'Read-only access'}</strong><p>{canWrite ? 'Every change is recorded in the activity log.' : 'You can view directory, key and billing details.'}</p></div></div>
        <div className="sidebar-version"><span>Platform portal</span><small>v{VERSION}</small></div>
      </div>
    </aside>
    <div className="app-main">
      <header className="topbar">
        <div className="topbar-left"><span className="current-page">{active?.label || 'Platform portal'}</span>{session.environment !== 'production' && <span className="environment-badge" title="Non-production environment (test workspace keys)">{environmentDisplayLabel(session.environment)}</span>}</div>
        <div className="topbar-actions">
          <span className="session-role" title={session.roles.join(', ')}><ShieldCheck size={13}/>{role}</span>
          <div className="operator-identity"><span className="profile-avatar" aria-hidden="true">{initials(session.display_name || session.actor)}</span><div><strong>{session.display_name || session.actor}</strong><small>{role}</small></div></div>
          <ThemeToggle/>
          <button type="button" className="button secondary small" onClick={() => void signOut()}><LogOut size={15}/>Sign out</button>
        </div>
      </header>
      <main id="main-content" tabIndex={-1} className="page-content">{children}</main>
      <footer className="app-footer"><span><span className="footer-brand">CloudSaver</span>Platform portal</span><span><ShieldCheck size={13}/>Every change is audited</span></footer>
    </div>
  </div>;
}
