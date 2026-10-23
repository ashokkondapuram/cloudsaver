import {formatMoney} from './format';
import type {
  ApiKey, AuditEvent, BillingInterval, BillingProviderName, BillingState, EntitlementKey, EntitlementSource, FailureReason, KeyStatus,
  LapsedAction, PaymentMethod, PaymentStatus, PlanTier, Provider, RecordStatus, Role, ScanFrequency, Session, SubscriptionStatus,
} from './types';

export const PROVIDERS: Provider[] = ['azure', 'aws', 'gcp', 'kubernetes'];
export const ROLES: Role[] = ['TenantAdmin', 'BillingAdmin', 'Viewer'];
export const PLANS: PlanTier[] = ['STARTER', 'GROWTH', 'ENTERPRISE'];
export const STATUSES: RecordStatus[] = ['active', 'suspended', 'deleted'];

export const providerLabel: Record<Provider, string> = {azure: 'Azure', aws: 'AWS', gcp: 'Google Cloud', kubernetes: 'Kubernetes'};
export const roleLabel: Record<Role, string> = {TenantAdmin: 'Workspace admin', BillingAdmin: 'Billing admin', Viewer: 'Viewer'};
export const planLabel: Record<PlanTier, string> = {STARTER: 'Starter', GROWTH: 'Growth', ENTERPRISE: 'Enterprise'};
export const statusLabel: Record<RecordStatus, string> = {active: 'Active', suspended: 'Suspended', deleted: 'Deleted'};
export const keyStatusLabel: Record<KeyStatus, string> = {
  active: 'Active', expiring_soon: 'Expiring soon', rotating_out: 'Rotating out', revoked: 'Revoked', expired: 'Expired',
};
export const failureReasonLabel: Record<FailureReason, string> = {
  unknown: 'Unknown key', secret_mismatch: 'Wrong secret', malformed: 'Malformed key', revoked: 'Revoked', expired: 'Expired',
  rotated_out: 'Rotated out', workspace_suspended: 'Workspace suspended', throttled: 'Throttled',
};

/** Plan display name for a workspace or plan code; unknown codes fall back to the code itself. */
export function planName(code: string | null | undefined, name?: string | null) {
  if (name) return name;
  if (!code) return '—';
  return (planLabel as Record<string, string>)[code] || code;
}

export const BILLING_STATES: BillingState[] = ['active', 'grace', 'lapsed', 'none'];
export const billingStateLabel: Record<BillingState, string> = {active: 'Active', grace: 'Grace period', lapsed: 'Lapsed', none: 'No subscription'};

export type BillingBadgeKind = 'active' | 'trial' | 'grace' | 'lapsed' | 'canceled' | 'none';
export const billingBadgeLabel: Record<BillingBadgeKind, string> = {
  active: 'Active', trial: 'Trial', grace: 'Grace period', lapsed: 'Lapsed', canceled: 'Canceled', none: 'No subscription',
};

/** Combines the customer's derived billing state with its subscription status into one badge. */
export function billingBadgeKind(state: BillingState | null | undefined, status?: SubscriptionStatus | null): BillingBadgeKind {
  if (!state || state === 'none') return 'none';
  if (state === 'active') return status === 'trialing' ? 'trial' : 'active';
  if (state === 'grace') return 'grace';
  return status === 'canceled' ? 'canceled' : 'lapsed';
}

export const subscriptionStatusLabel: Record<SubscriptionStatus, string> = {
  trialing: 'Trial', active: 'Active', past_due: 'Past due', canceled: 'Canceled', expired: 'Expired',
};
export const paymentStatusLabel: Record<PaymentStatus, string> = {pending: 'Pending', paid: 'Paid', failed: 'Failed', refunded: 'Refunded', void: 'Void'};
export const PAYMENT_METHODS: PaymentMethod[] = ['bank_transfer', 'card', 'check', 'other'];
export const paymentMethodLabel: Record<PaymentMethod, string> = {bank_transfer: 'Bank transfer', card: 'Card', check: 'Check', other: 'Other'};
export const INTERVALS: BillingInterval[] = ['month', 'year', 'custom'];
export const intervalLabel: Record<BillingInterval, string> = {month: 'Monthly', year: 'Yearly', custom: 'Custom'};
export const billingProviderLabel: Record<BillingProviderName, string> = {manual: 'Manual', stripe: 'Stripe'};
export const lapsedActionLabel: Record<LapsedAction, string> = {downgrade: 'Downgrade', suspend: 'Suspend workspaces'};
export const entitlementSourceLabel: Record<EntitlementSource, string> = {plan: 'Plan', override: 'Override', fallback: 'Fallback'};
export const SCAN_FREQUENCIES: ScanFrequency[] = ['manual', 'daily', 'hourly'];
export const scanFrequencyLabel: Record<ScanFrequency, string> = {manual: 'Manual', daily: 'Daily', hourly: 'Hourly'};

/** "$1,200.00 per month" */
export function priceText(amountMinor: number | null | undefined, currency: string | null | undefined, interval: BillingInterval | null | undefined, options: {code?: boolean} = {}) {
  const amount = formatMoney(amountMinor, currency, options, '');
  if (!amount) return '—';
  if (interval === 'month') return `${amount} per month`;
  if (interval === 'year') return `${amount} per year`;
  return amount;
}

export const ENTITLEMENT_KEYS: EntitlementKey[] = [
  'max_subscriptions', 'max_resources_per_scan', 'allowed_scan_frequencies', 'can_export_terraform', 'can_use_keyvault',
  'can_dispatch_automated_alerts', 'retention_days', 'allowed_providers', 'max_workspaces', 'max_active_keys_per_workspace',
  'max_key_lifetime_days',
];
export const entitlementLabel: Record<EntitlementKey, string> = {
  max_subscriptions: 'Cloud scopes per workspace',
  max_resources_per_scan: 'Resources per scan',
  allowed_scan_frequencies: 'Scan frequencies',
  can_export_terraform: 'Terraform review',
  can_use_keyvault: 'Key Vault integration',
  can_dispatch_automated_alerts: 'Automatic alerts',
  retention_days: 'Retention (days)',
  allowed_providers: 'Cloud providers',
  max_workspaces: 'Workspaces per customer',
  max_active_keys_per_workspace: 'Active keys per workspace',
  max_key_lifetime_days: 'Maximum key lifetime (days)',
};

export function entitlementValueText(key: EntitlementKey, value: unknown) {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'Included' : 'Not included';
  if (typeof value === 'number') return new Intl.NumberFormat('en-US').format(value);
  if (Array.isArray(value)) {
    if (key === 'allowed_providers') return providersText(value as Provider[]);
    if (key === 'allowed_scan_frequencies') return (value as ScanFrequency[]).map(item => scanFrequencyLabel[item] || item).join(', ') || 'None';
    return value.join(', ');
  }
  return String(value);
}

export function isOperator(session: Session | null) {
  return !!session?.roles.includes('PlatformOperator');
}

export function operatorRoleLabel(session: Session | null) {
  if (isOperator(session)) return 'Operator';
  if (session?.roles.includes('PlatformAuditor')) return 'Auditor';
  return 'No access';
}

/** User-facing label for PLATFORM_ENVIRONMENT / identity-service environment. */
export function environmentDisplayLabel(environment: string) {
  if (environment === 'development') return 'Local';
  if (environment === 'production') return 'Production';
  return environment;
}

export function keyIdLabel(key: Pick<ApiKey, 'key_id' | 'format'>, prefix: Session['key_prefix'] = 'cs_test_') {
  return key.format === 'legacy' ? `Legacy · ${key.key_id}` : `${prefix}${key.key_id}…`;
}

export function rolesText(roles: Role[]) {
  return roles.map(role => roleLabel[role] || role).join(', ') || '—';
}

export function providersText(providers: Provider[], allProviders = false) {
  if (allProviders) return 'All providers';
  return providers.map(provider => providerLabel[provider] || provider).join(', ') || 'None';
}

const ACTIONS: Record<string, string> = {
  issued: 'Issued key',
  rotated: 'Rotated key',
  revoked: 'Revoked key',
  revoked_all: 'Revoked all keys',
  updated: 'Edited key',
  key_updated: 'Edited key',
  providers_changed: 'Changed key providers',
  expired: 'Key expired',
  rotated_out: 'Key rotated out',
  hash_upgraded: 'Upgraded key hash',
  imported: 'Imported key',
  workspace_created: 'Created workspace',
  workspace_updated: 'Edited workspace',
  workspace_suspended: 'Suspended workspace',
  workspace_reactivated: 'Reactivated workspace',
  workspace_deleted: 'Deleted workspace',
  identity_changed: 'Changed identity bindings',
  scopes_changed: 'Changed cloud accounts',
  customer_created: 'Created customer',
  customer_updated: 'Edited customer',
  customer_suspended: 'Suspended customer',
  customer_reactivated: 'Reactivated customer',
  customer_deleted: 'Deleted customer',
  platform_updated: 'Changed platform settings',
  resource_access_updated: 'Updated resource access settings',
  workspace_identity_updated: 'Updated workspace identity bindings',
  access_check_requested: 'Requested access test',
  access_check_completed: 'Completed access test',
  platform_settings_updated: 'Changed platform settings',
  plan_created: 'Created plan',
  plan_updated: 'Edited plan',
  plan_retired: 'Retired plan',
  subscription_created: 'Created subscription',
  subscription_changed: 'Changed subscription',
  subscription_canceled: 'Canceled subscription',
  payment_recorded: 'Recorded payment',
  payment_updated: 'Edited payment',
  payment_voided: 'Voided payment',
  billing_state_changed: 'Billing status changed',
  entitlements_changed: 'Entitlements changed',
  billing_settings_updated: 'Changed billing settings',
  provider_event_applied: 'Applied payment provider event',
};

export const AUDIT_ACTIONS = Object.keys(ACTIONS);

export function actionLabel(action: string) {
  if (ACTIONS[action]) return ACTIONS[action];
  const words = action.replace(/[._-]+/g, ' ').trim().toLowerCase();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Changed item';
}

/** "Stripe" for provider:stripe, otherwise the recorded actor. */
export function auditActor(event: Pick<AuditEvent, 'actor' | 'actor_type'>) {
  if (event.actor_type !== 'provider') return event.actor;
  const name = event.actor.replace(/^provider:/, '');
  return (billingProviderLabel as Record<string, string>)[name] || name || 'Payment provider';
}

export function auditSubject(event: AuditEvent) {
  const details = event.details || {};
  const text = (value: unknown) => (typeof value === 'string' && value.trim() ? value.trim() : '');
  if (event.key_id) return text(details.name) || text(details.key_name) || event.key_id;
  if (event.action.startsWith('payment_')) {
    const reference = text(details.reference);
    const amount = typeof details.amount_minor === 'number' ? formatMoney(details.amount_minor, text(details.currency), {}, '') : '';
    return [reference, amount && `for ${amount}`].filter(Boolean).join(' ');
  }
  if (event.action.startsWith('plan_')) return text(details.plan_name) || text(details.name) || text(details.code) || text(details.plan_code);
  if (event.action.startsWith('subscription_')) {
    const customer = text(details.customer_name);
    const plan = text(details.plan_name) || planName(text(details.plan_code) || null, null);
    return [customer, plan !== '—' ? plan : ''].filter(Boolean).join(' · ');
  }
  return text(details.workspace_name) || text(details.customer_name) || text(details.name) || '';
}
