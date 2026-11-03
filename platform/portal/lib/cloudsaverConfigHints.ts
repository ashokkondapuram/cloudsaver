/** Operator help for CloudSaver integration fields (platform UI + deployment .env). */

export type ConfigHint = {
  env?: string;
  summary: string;
  detail: string;
  deploymentOnly?: boolean;
};

export const RESOURCE_ACCESS_HINTS: Record<string, ConfigHint> = {
  managed_identity_client_id: {
    env: 'AZURE_CLIENT_ID / AZURE_MANAGED_IDENTITY_CLIENT_ID',
    summary: 'Hub identity CloudSaver uses to reach Azure, AWS, and GCP.',
    detail: 'Attach this managed identity to scanner-service, scan-worker, and billing workers. Changing it affects every workspace unless a workspace override is set.',
  },
  azure_access: {
    env: 'CLOUDSAVER_AZURE_ACCESS',
    summary: 'How CloudSaver reaches Azure APIs.',
    detail: 'Use federated for production (workload identity). Direct is for local developer CLI only.',
  },
  azure_app_client_id: {
    env: 'CLOUDSAVER_AZURE_APP_CLIENT_ID',
    summary: 'Entra app used for Azure federation.',
    detail: 'Required when Azure access is federated unless each workspace supplies its own app registration.',
  },
  azure_token_audience: {
    env: 'CLOUDSAVER_AZURE_TOKEN_AUDIENCE',
    summary: 'Token audience for Azure federation.',
    detail: 'Usually api://AzureADTokenExchange for workload identity exchange.',
  },
  aws_hub_role_arn: {
    env: 'CLOUDSAVER_AWS_HUB_ROLE_ARN',
    summary: 'AWS role CloudSaver assumes for inventory and billing.',
    detail: 'Trust must allow your hub managed identity or developer principal.',
  },
  aws_token_audience: {
    env: 'CLOUDSAVER_AWS_TOKEN_AUDIENCE',
    summary: 'Audience for AWS web identity tokens.',
    detail: 'Must match the trust policy on the hub role.',
  },
  gcp_workload_provider: {
    env: 'CLOUDSAVER_GCP_WORKLOAD_PROVIDER',
    summary: 'GCP workload identity provider resource name.',
    detail: 'Full resource path for the pool provider that trusts your hub identity.',
  },
  gcp_token_audience: {
    env: 'CLOUDSAVER_GCP_TOKEN_AUDIENCE',
    summary: 'Audience for GCP federation tokens.',
    detail: 'Must match the provider configuration in Google Cloud.',
  },
};

export const INTEGRATION_FIELDS = [
  {key: 'live_evidence_enabled', label: 'Live evidence', type: 'bool' as const,
    hint: 'Collect Azure Monitor metrics and activity history during scans.',
    info: {env: 'CLOUDSAVER_LIVE_EVIDENCE_ENABLED', summary: '30-day metrics and activity log enrichment.',
      detail: 'Increases scan time and Azure API usage. Requires Monitoring Reader on scoped subscriptions.'}},
  {key: 'azure_arm_detail_enabled', label: 'ARM resource detail', type: 'bool' as const,
    hint: 'Fetch full ARM configuration per resource during scans.',
    info: {env: 'CLOUDSAVER_AZURE_ARM_DETAIL_ENABLED', summary: 'Read-only GET for each Microsoft.* resource.',
      detail: 'Populates typed configuration evidence used by rules and typed resource tables.'}},
  {key: 'azure_arm_detail_max', label: 'ARM detail cap', type: 'int' as const,
    hint: '0 means no cap (every resource).',
    info: {env: 'CLOUDSAVER_AZURE_ARM_DETAIL_MAX', summary: 'Maximum ARM GET calls per scan.',
      detail: 'Use a positive number to limit cost on very large subscriptions. Maximum 50000.'}},
  {key: 'live_evidence_max_resources', label: 'Live evidence cap', type: 'int' as const,
    hint: '0 means every metric-capable resource.',
    info: {env: 'CLOUDSAVER_LIVE_EVIDENCE_MAX_RESOURCES', summary: 'Resources that receive Monitor enrichment.',
      detail: 'Only types with a metrics contract are enriched. 0 removes the per-scan cap.'}},
  {key: 'default_billing_currency', label: 'Reporting currency', type: 'currency' as const,
    hint: 'Three-letter ISO code for cost columns and FinOps views.',
    info: {env: 'CLOUDSAVER_DEFAULT_BILLING_CURRENCY', summary: 'Default currency when a workspace does not set one.',
      detail: 'FOCUS charges must exist in this currency for typed resource cost columns.'}},
  {key: 'auto_billing_sync', label: 'Automatic billing sync', type: 'bool' as const,
    hint: 'Pull Azure Cost Management into FOCUS on a schedule.',
    info: {env: 'CLOUDSAVER_AUTO_BILLING_SYNC', summary: 'Runs billing-sync-worker against configured connectors.',
      detail: 'Requires CLOUDSAVER_BILLING_CONNECTORS in deployment .env with matching workspace scopes.'}},
  {key: 'delivery_enabled', label: 'Durable delivery', type: 'bool' as const,
    hint: 'Run the delivery dispatcher for scheduled scans and webhooks.',
    info: {env: 'CLOUDSAVER_DELIVERY_ENABLED', summary: 'PostgreSQL-backed scan and notification queue.',
      detail: 'Webhook URLs stay in deployment .env (CLOUDSAVER_NOTIFICATION_TARGETS).'}},
  {key: 'observability_sync', label: 'Observability sync', type: 'bool' as const,
    hint: 'Ingest Prometheus or Datadog signals where connectors exist.',
    info: {env: 'CLOUDSAVER_OBSERVABILITY_SYNC', summary: 'Background observability worker.',
      detail: 'Connector secrets remain in deployment .env only.'}},
] as const;

export const DEPLOYMENT_ONLY_SETTINGS: ConfigHint[] = [
  {env: 'CLOUDSAVER_DATABASE_URL / CLOUDSAVER_DB_PASSWORD', deploymentOnly: true,
    summary: 'PostgreSQL connection for CloudSaver.', detail: 'Set in the CloudSaver compose .env. Never store in the platform database.'},
  {env: 'CLOUDSAVER_IDENTITY_TOKEN_*', deploymentOnly: true,
    summary: 'Service tokens for identity-service.', detail: 'Register digests with platform/scripts/setup_platform.py --add-callers.'},
  {env: 'CLOUDSAVER_BILLING_CONNECTORS', deploymentOnly: true,
    summary: 'Authorized billing export scopes.', detail: 'JSON in CloudSaver .env. Must align with workspace subscription and account scopes in this portal.'},
  {env: 'CLOUDSAVER_NOTIFICATION_TARGETS / CLOUDSAVER_WEBHOOK_*', deploymentOnly: true,
    summary: 'Slack and Teams webhook destinations.', detail: 'Secrets stay in deployment .env; workspaces can add registry webhooks separately.'},
  {env: 'PLATFORM_* (platform/.env)', deploymentOnly: true,
    summary: 'Platform database, portal auth, and Stripe.', detail: 'Configure platform/.env only. CloudSaver reads effects through directory projection.'},
];
