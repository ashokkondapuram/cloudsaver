import {AlertCircle, Database, Loader2, ShieldCheck, type LucideIcon} from 'lucide-react';
import type {ReactNode} from 'react';
import {billingBadgeKind, billingBadgeLabel, keyStatusLabel, paymentStatusLabel, providerLabel, statusLabel} from '../../lib/labels';
import type {ApiKey, BillingState, PaymentStatus, Provider, RecordStatus, SubscriptionStatus} from '../../lib/types';

export function ProviderBadge({provider}: {provider: Provider}) {
  return <span className={`provider-badge provider-${provider}`}><span aria-hidden="true"/>{providerLabel[provider] || provider}</span>;
}

export function ProviderList({providers, empty = 'None'}: {providers: Provider[]; empty?: string}) {
  if (!providers.length) return <span className="muted">{empty}</span>;
  return <span className="badge-row">{providers.map(provider => <ProviderBadge key={provider} provider={provider}/>)}</span>;
}

export function StatusBadge({status}: {status: RecordStatus}) {
  return <span className={`state-badge ${status}`}>{statusLabel[status] || status}</span>;
}

/** Active, Trial, Grace period, Lapsed, Canceled or No subscription. */
export function BillingStateBadge({state, status}: {state: BillingState | null | undefined; status?: SubscriptionStatus | null}) {
  const kind = billingBadgeKind(state, status);
  return <span className={`state-badge billing-${kind}`}>{billingBadgeLabel[kind]}</span>;
}

export function PaymentStatusBadge({status}: {status: PaymentStatus}) {
  return <span className={`state-badge payment-${status}`}>{paymentStatusLabel[status] || status}</span>;
}

export function KeyStatusBadges({apiKey}: {apiKey: Pick<ApiKey, 'status' | 'format'>}) {
  return <span className="badge-row">
    <span className={`state-badge ${apiKey.status}`}>{keyStatusLabel[apiKey.status] || apiKey.status}</span>
    {apiKey.format === 'legacy' && <span className="state-badge legacy">Legacy</span>}
  </span>;
}

export function EmptyState({icon: Icon = Database, title, children, action}: {icon?: LucideIcon; title: string; children?: ReactNode; action?: ReactNode}) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={24}/></div><h3>{title}</h3>{children && <p>{children}</p>}{action}</div>;
}

export function Notice({children, tone = 'info'}: {children: ReactNode; tone?: 'info' | 'warning' | 'error' | 'success'}) {
  const Icon = tone === 'success' ? ShieldCheck : AlertCircle;
  return <div className={`notice notice-${tone}`} role={tone === 'error' ? 'alert' : 'status'}><Icon size={17}/><div>{children}</div></div>;
}

export function Loading({label = 'Loading…'}: {label?: string}) {
  return <div className="loading-state" role="status"><Loader2 className="spin" size={20}/>{label}</div>;
}

export function SectionTitle({eyebrow, title, children, action}: {eyebrow?: string; title: string; children?: ReactNode; action?: ReactNode}) {
  return <div className="section-title"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2>{title}</h2>{children && <p>{children}</p>}</div>{action}</div>;
}

export function PageHeading({eyebrow, title, children, actions}: {eyebrow?: string; title: string; children?: ReactNode; actions?: ReactNode}) {
  return <div className="page-heading"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h1>{title}</h1>{children && <p>{children}</p>}</div>{actions && <div className="page-heading-actions">{actions}</div>}</div>;
}

export function Switch({checked, onChange, label, disabled}: {checked: boolean; onChange: (value: boolean) => void; label: string; disabled?: boolean}) {
  return <button type="button" role="switch" className="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}/>;
}
