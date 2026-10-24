/** Synthetic contract fixture. No provider, account or credential is contacted. */
export function foundryView(editable = true) {
  const providers: Record<'azure' | 'aws' | 'gcp', {enabled: boolean; target_id: string | null; [key: string]: string | boolean | null}> = {
    azure: {enabled: false, target_id: null, endpoint_url: null, deployment_name: null, api_version: '2024-10-21', region: null, deployment_sku: 'Standard_PAYG', auth_binding: 'workspace_managed_identity'},
    aws: {enabled: false, target_id: null, region: null, model_id: null, role_arn: null, guardrail_id: null, guardrail_version: null, external_id: null},
    gcp: {enabled: false, target_id: null, project_id: null, location: null, model_id: null, service_account_email: null, vpc_sc_enforced: false}};
  return {version: 1, editable, plan_allowed: true, directory_mode: 'registry',
    ai_foundry: {providers, policy: {advisory_enabled: false, allow_anonymized_knowledge_candidates: false, routing_mode: 'same_cloud_only', primary_provider: 'azure',
      max_input_tokens_per_request: 4000, max_output_tokens_per_request: 1200, hourly_attempt_budget: 10, monthly_token_limit: null}},
    platform_policy: {version: 1, policy: {enabled: true, disabled_providers: [], allow_knowledge_candidates: true,
      max_input_tokens_per_request: 16000, max_output_tokens_per_request: 4096, hourly_attempt_ceiling: 10, monthly_token_ceiling: 1000000}},
    catalog: [{provider: 'azure', target_id: 'review', model: 'approved-model', auth: 'customer_federated',
      fields: {endpoint_url: 'https://approved.openai.azure.com', deployment_name: 'approved-model', api_version: '2024-10-21', region: 'eastus', deployment_sku: 'Standard_PAYG'},
      privacy_attestation: 'Provider retention controls require independent verification.'}],
    usage: {attempts_last_30d: 0, known_input_tokens: 0, known_output_tokens: 0, unmetered_attempts: 0,
      monthly_tokens_used_or_reserved: 0, monthly_unbounded_legacy_attempts: 0, attempts_current_hour: 0, monthly_period: 'UTC calendar month'},
    diagnostics: [], knowledge_retrieval: 'configured', message: 'Synthetic UI fixture. No inference is performed.'};
}
