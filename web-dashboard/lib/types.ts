export type Finding = {
  cloud_provider?: string;
  scope_id?: string;
  evidence?: Record<string, unknown>;
  rule_id: string;
  severity: string;
  resource_name: string;
  resource_type: string;
  resource_group: string;
  subscription_id: string;
  resource_id: string;
  estimated_monthly_waste_usd: number | null;
  details: string;
  cost_attribution?: {
    confidence: string;
    currency?: string;
    calculation_basis: string;
    realizable_savings_usd: number | null;
    unit_price?: number;
    unit_of_measure?: string;
  };
};

export type Scan = {
  scan_id: string;
  timestamp: string;
  status: string;
  mode: string;
  data_origin?: string;
  cloud_providers?: string[];
  subscriptions_scanned: number;
  total_items_found: number;
  total_monthly_waste_usd: number | null;
  realizable_monthly_savings_usd?: number | null;
  findings: Finding[];
};

export type Workspace = {
  name: string;
  tenant_id: string;
  subscription_ids: string[];
  roles: string[];
  mode: string;
  plan_tier: string;
  plan_name?: string;
  billing_state?: BillingState;
  providers?: string[];
  configured_scope_count?: number;
  max_scopes_per_scan?: number;
  can_export_terraform?: boolean;
  scheduled_scans_enabled?: boolean;
  scheduled_scan_interval_seconds?: number;
  allowed_scan_frequencies?: string[];
  automated_alerts_enabled?: boolean;
  notification_webhook_configured?: boolean;
  scan_frequency?: Frequency;
  platform_scheduled_scans_enabled?: boolean;
  platform_automated_alerts_enabled?: boolean;
  settings_editable?: boolean;
  allowed_providers?: string[];
  all_providers?: boolean;
  key_id?: string | null;
  key_name?: string | null;
  key_expires_at?: string | null;
  directory_mode?: 'registry' | 'cutover';
  scopes_editable?: boolean;
};

export type Frequency = 'manual' | 'daily' | 'hourly';
export type AwsAccount = {account_id: string; region: string; role_arn: string};
export type GcpProject = {project_id: string; regions: string[]};
export type KubernetesCluster = {cluster_id: string; prometheus_url: string; bearer_token_env: string};

export type TenantSettings = {
  tenant_id: string;
  name: string;
  plan_tier: string;
  active: boolean;
  version: number;
  subscription_ids: string[];
  aws_accounts: AwsAccount[];
  gcp_projects: GcpProject[];
  kubernetes_clusters: KubernetesCluster[];
  identity: {azure_app_client_id?: string; gcp_service_account?: string};
  schedule: {frequency: Frequency};
  alerts: {enabled: boolean; channel: 'slack' | 'teams' | null; webhook_configured: boolean};
};

export type IdentityOnboarding = {
  identity_mode: string;
  azure_access: string;
  azure_app_client_id: string | null;
  managed_identity_client_id: string | null;
  aws_hub_role_arn: string | null;
  aws_token_audience: string;
  aws_external_id?: string | null;
  gcp_workload_provider: string | null;
  gcp_token_audience?: string | null;
  gcp_service_account?: string | null;
  source?: Record<string, string>;
  commands?: {azure?: string[]; aws?: string[]; gcp?: string[]};
  setup_guide_path?: string;
};

export type PlatformSettings = {scheduled_scans_enabled: boolean; automated_alerts_enabled: boolean; version: number};

export type SettingsResponse = {
  editable: boolean;
  scopes_editable?: boolean;
  directory_mode?: 'registry' | 'cutover';
  settings: TenantSettings;
  limits: {max_subscriptions: number; allowed_scan_frequencies: Frequency[]; can_dispatch_automated_alerts: boolean};
  platform: PlatformSettings | null;
  identity: IdentityOnboarding;
};

export type BillingState = 'active' | 'grace' | 'lapsed' | 'none';

export type Entitlements = {
  tenant_id: string;
  tier: string;
  plan_name: string;
  billing_state: BillingState;
  current_period_end: string | null;
  grace_ends_at: string | null;
  subscription_plan_name: string | null;
  manage_billing_url: string | null;
  max_subscriptions: number;
  current_subscriptions: number;
  max_resources_per_scan: number;
  allowed_scan_frequencies: string[];
  allowed_providers: string[];
  can_export_terraform: boolean;
  can_use_keyvault: boolean;
  can_dispatch_automated_alerts: boolean;
  retention_days: number;
  entitlements_source: 'platform' | 'fallback';
  settings_version: number;
  plan_change_allowed: boolean;
};

export type PlanOption = {
  code: string;
  name: string;
  max_subscriptions: number;
  max_resources_per_scan: number;
  allowed_scan_frequencies: string[];
  can_export_terraform: boolean;
  can_use_keyvault: boolean;
  can_dispatch_automated_alerts: boolean;
  retention_days: number;
  allowed_providers: string[];
};

export type Delivery = {
  id: string;
  kind: string;
  status: string;
  target_id: string | null;
  job_id: string | null;
  scan_id: string | null;
  attempts: number;
  replay_count: number;
  error_code: string | null;
  created_at: string;
  updated_at: string;
};

export type Reliability = {
  available: boolean;
  dispatcher_enabled: boolean;
  targets: {target_id: string; channel: string}[];
  counts: {kind: string; status: string; count: number}[];
  oldest_due_seconds: number | null;
  dispatcher: {last_poll_at: string; last_success_at: string | null; last_error_at: string | null} | null;
};

export type Density = 'compact' | 'medium' | 'relaxed';
