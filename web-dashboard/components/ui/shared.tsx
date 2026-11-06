import {Database, SpinnerGap, WarningCircle, ShieldCheck, type Icon} from '@phosphor-icons/react';
import type {ReactNode} from 'react';
import {providerNames} from '../../lib/finops';

export function ProviderBadge({provider}: {provider: string}) {
  return <span className={`provider-badge provider-${provider}`}><span aria-hidden="true"/>{providerNames[provider] || provider}</span>;
}
export function PriorityBadge({severity}: {severity: string}) {
  return <span className={`priority-badge priority-${severity.toLowerCase()}`}><span aria-hidden="true"/>{severity.charAt(0) + severity.slice(1).toLowerCase()}</span>;
}
export function EmptyState({icon: Icon = Database, title, children, action}: {icon?: Icon; title: string; children?: ReactNode; action?: ReactNode}) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={24} weight="regular"/></div><h3>{title}</h3><p>{children}</p>{action}</div>;
}
export function Notice({children, tone = 'info'}: {children: ReactNode; tone?: 'info' | 'warning' | 'error' | 'success'}) {
  const Icon = tone === 'success' ? ShieldCheck : WarningCircle;
  return <div className={`notice notice-${tone}`} role={tone === 'error' ? 'alert' : undefined}><Icon size={17} weight="regular"/><div>{children}</div></div>;
}
export function Loading({label = 'Loading workspace data…'}: {label?: string}) {
  return <div className="loading-state" role="status"><SpinnerGap className="spin" size={20} weight="regular"/>{label}</div>;
}
export function SectionTitle({eyebrow, title, children, action}: {eyebrow?: string; title: string; children?: ReactNode; action?: ReactNode}) {
  return <div className="section-title"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2>{title}</h2>{children && <p>{children}</p>}</div>{action}</div>;
}
