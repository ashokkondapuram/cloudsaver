export type Provider = 'azure' | 'aws' | 'gcp' | 'kubernetes';
export type Role = 'TenantAdmin' | 'BillingAdmin' | 'Viewer';
export type PlanTier = 'STARTER' | 'GROWTH' | 'ENTERPRISE';
export type RecordStatus = 'active' | 'suspended' | 'deleted';

export type Session = {
  actor: string;
  display_name: string;
  roles: string[];
  auth_mode: 'entra' | 'operator_key';
  provider_scoped_keys: boolean;
  environment: string;
  key_prefix: 'cs_test_' | 'cs_live_';
  billing_enabled: boolean;
  billing_provider: BillingProviderName;
};

export type BillingState = 'active' | 'grace' | 'lapsed' | 'none';
export type BillingProviderName = 'manual' | 'stripe';

export type Customer = {
  id: string; name: string; status: RecordStatus; notes: string | null; version: number;
  created_at: string; created_by: string; updated_at: string; updated_by: string; deleted_at: string | null;
  workspace_count: number; active_workspace_count: number;
  billing_contact_email?: string | null; manage_billing_url?: string | null; external_customer_refs?: Record<string, string> | null;
  billing_state?: BillingState; billing_state_changed_at?: string | null;
};

export type ScanFrequency = 'manual' | 'daily' | 'hourly';

export type Entitlements = {
  max_subscriptions: number;
  max_resources_per_scan: number;
  allowed_scan_frequencies: ScanFrequency[];
  can_export_terraform: boolean;
  can_use_keyvault: boolean;
  can_dispatch_automated_alerts: boolean;
  retention_days: number;
  allowed_providers: Provider[];
  max_workspaces: number;
  max_active_keys_per_workspace: number;
  max_key_lifetime_days: number;
};
export type EntitlementKey = keyof Entitlements;

export type BillingInterval = 'month' | 'year' | 'custom';

export type Plan = {
  code: string; name: string; description: string | null; status: 'active' | 'retired';
  list_price_minor: number | null; currency: string | null; interval: BillingInterval | null;
  entitlements: Entitlements; external_price_refs: {stripe?: string[]} & Record<string, string[] | undefined>;
  customer_count: number; workspace_count: number;
  version: number; created_at: string; created_by: string; updated_at: string; updated_by: string;
};

export type SubscriptionStatus = 'trialing' | 'active' | 'past_due' | 'canceled' | 'expired';

export type Subscription = {
  id: string; customer_id: string; plan_code: string; plan_name: string; status: SubscriptionStatus; provider: BillingProviderName;
  external_subscription_ref: string | null; current_period_start: string; current_period_end: string;
  cancel_at_period_end: boolean; canceled_at: string | null; amount_minor: number; currency: string; interval: BillingInterval;
  grace_days: number; entitlement_overrides: Partial<Entitlements> | null; notes: string | null;
  version: number; created_at: string; created_by: string; updated_at: string; updated_by: string;
};

export type PaymentStatus = 'pending' | 'paid' | 'failed' | 'refunded' | 'void';
export type PaymentMethod = 'bank_transfer' | 'card' | 'check' | 'other';

export type Payment = {
  id: string; customer_id: string; subscription_id: string | null; amount_minor: number; currency: string;
  status: PaymentStatus; method: PaymentMethod; reference: string; invoice_date: string | null; due_date: string | null;
  paid_at: string | null; period_start: string; period_end: string; provider: BillingProviderName; external_payment_ref: string | null;
  notes: string | null; void_reason: string | null; voided_by: string | null; voided_at: string | null;
  version: number; created_at: string; created_by: string; updated_at: string; updated_by: string;
};

export type EntitlementSource = 'plan' | 'override' | 'fallback';

export type CustomerEntitlements = {
  customer_id: string; billing_state: BillingState; plan: {code: string; name: string}; subscription: Subscription | null;
  issuance_blocked: boolean;
  effective: {[K in EntitlementKey]?: {value: Entitlements[K]; source: EntitlementSource}};
  workspaces: Array<{tenant_id: string; name: string; plan_tier: string; entitlements_version: number}>;
};

export type BillingRow = {
  customer_id: string; customer_name: string; billing_state: BillingState; plan_code: string; plan_name: string;
  subscription_id: string | null; subscription_status: SubscriptionStatus | null; current_period_end: string | null;
  amount_minor: number | null; currency: string | null; interval: BillingInterval | null;
  last_payment: {paid_at: string | null; amount_minor: number; currency: string; reference: string} | null;
};

export type LapsedAction = 'downgrade' | 'suspend';

export type BillingSettings = {
  default_plan_code: string; default_grace_days: number; lapsed_action: LapsedAction; lapsed_plan_code: string;
  default_manage_billing_url: string | null; require_subscription_for_keys: boolean;
  version: number; updated_at: string; updated_by: string; billing_enabled: boolean;
  provider: {name: BillingProviderName; configured: boolean; webhook_url: string | null};
};

export type AwsAccount = {account_id: string; region: string; role_arn: string};
export type GcpProject = {project_id: string; regions: string[]};
export type KubernetesCluster = {cluster_id: string; prometheus_url: string; bearer_token_env: string};

export type Workspace = {
  tenant_id: string; customer_id: string; customer_name: string; name: string; plan_tier: PlanTier; status: RecordStatus;
  plan_name?: string; plan_locked?: boolean; issuance_blocked?: boolean; entitlements_version?: number;
  identity: {azure_app_client_id?: string | null; gcp_service_account?: string | null};
  subscription_ids: string[]; aws_accounts: AwsAccount[]; gcp_projects: GcpProject[]; kubernetes_clusters: KubernetesCluster[];
  providers: Provider[]; version: number; created_at: string; created_by: string; updated_at: string; updated_by: string;
  suspended_at: string | null; deleted_at: string | null; active_keys: number; last_used_at: string | null; next_expiry: string | null;
};

export type KeyStatus = 'active' | 'expiring_soon' | 'rotating_out' | 'revoked' | 'expired';

export type ApiKey = {
  key_id: string; tenant_id: string; name: string; roles: Role[]; all_providers: boolean; allowed_providers: Provider[];
  effective_providers: Provider[]; scope_restrictions: null; format: 'v1' | 'legacy';
  source: 'portal' | 'registry_import' | 'env_import'; status: KeyStatus; created_at: string; created_by: string;
  expires_at: string | null; revoked_at: string | null; revoked_by: string | null; revoke_reason: string | null;
  rotated_from: string | null; rotates_out_at: string | null; last_used_at: string | null; last_used_ip: string | null; version: number;
};

export type UsageRow = {key_id: string; hour: string; source_ip: string; success_count: number; failure_count: number; last_seen_at: string};

export type AuditEvent = {
  id: string; occurred_at: string; actor: string; actor_type: 'operator' | 'service' | 'system' | 'provider'; action: string;
  tenant_id: string | null; key_id: string | null; details: Record<string, unknown>;
};

export type FailureReason = 'malformed' | 'unknown' | 'secret_mismatch' | 'revoked' | 'expired' | 'rotated_out' | 'workspace_suspended' | 'throttled';

export type Failure = {
  minute: string; source_ip: string; key_id: string | null; tenant_id: string | null; reason: FailureReason; caller: string; count: number;
};

export type ResourceAccessEffective = Record<string, {value: string | null; source: 'platform' | 'environment' | 'workspace' | 'unset'}>;
export type PlatformSettings = {
  scheduled_scans_enabled: boolean; automated_alerts_enabled: boolean; resource_access?: Partial<Record<string, string>>;
  resource_access_effective?: ResourceAccessEffective; version: number; updated_by: string; updated_at: string;
};

export type Page<T> = {items: T[]; next_cursor: string | null};
export type IssuedKey = {key: ApiKey; secret: string; previous?: ApiKey};
