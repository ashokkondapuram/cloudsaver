# CloudSaver v0.4.0 Verification & Test Report

## Test Execution Summary
- **Execution Date**: 2026-10-22
- **Test Suite Results**: **29 passed, 0 failures, 0 errors** in 2.159s.
- **Environment**: Python 3.11 with FastAPI 0.92, Pydantic 1.10.4, SQLite WAL/Postgres RLS compatibility layer.

## Passed Test Modules
1. `tests/test_auth.py` (5 tests):
   - `test_admin_consent_url_generation`: Validates Microsoft Entra ID admin consent URL structure with client ID, state, and scopes.
   - `test_cross_tenant_token_rejected`: Confirms foreign tenant tokens are rejected with HTTP 403.
   - `test_expired_token_rejected`: Confirms expired tokens raise HTTP 401.
   - `test_valid_token_extraction`: Verifies claims parsing (`tid`, `oid`, `roles`).
   - `test_viewer_role_cannot_access_admin_action`: Enforces RBAC permissions.

2. `tests/test_pricing.py` (4 tests):
   - `test_empty_app_service_attribution`: Live and baseline rate lookup for dedicated App Service capacity.
   - `test_orphaned_disk_attribution`: Azure storage pricing calculation by SKU and size with snapshot cost netting.
   - `test_stopped_vm_attribution`: Idle persistent OS disk and compute reservation attribution.
   - `test_unassociated_public_ip_attribution`: Idle IPv4 rate calculation via Azure Retail Prices API.

3. `tests/test_remediation_terraform.py` (3 tests):
   - `test_generates_valid_hcl_with_snapshots_and_imports`: HCL generation with native Terraform 1.5+ `import` blocks and `azurerm_snapshot` safety backups.
   - `test_refuses_demo_scan`: Blocks IaC export on non-cloud mock records.
   - `test_refuses_unauthorized_subscription`: Enforces strict tenant authorization checks.

4. `tests/test_entitlements.py` (5 tests):
   - `test_create_checkout_session`: Stripe Checkout session creation for self-service tier upgrades.
   - `test_keyvault_restricted_on_growth`: Feature-gating Key Vault access to Enterprise tier.
   - `test_starter_tier_limits`: Validates 2 subscriptions limit on Starter tier.
   - `test_subscription_quota_enforcement`: Confirms HTTP 402 upgrade response upon exceeding quotas.
   - `test_terraform_export_restricted_on_starter`: Enforces Growth+ tier requirement for IaC exports.

5. `tests/test_outbox_lease.py` (4 tests):
   - `test_cooperative_cancellation_and_job_lifecycle`: Scan lifecycle state progression and cancellation handling.
   - `test_distributed_lease_acquisition_and_release`: Distributed Redis task mutual exclusion lease with heartbeat.
   - `test_outbox_enqueue_and_dispatch`: Transactional outbox persistence and dispatch.
   - `test_outbox_retry_and_dead_letter`: Outbox retry backoff with DLQ isolation.

6. `tests/test_api_v4.py` (8 tests):
   - `test_healthz_endpoint`: Verified service health and version `0.4.0`.
   - `test_consent_url_endpoint`: Admin consent URL generation via API gateway.
   - `test_me_endpoint_with_entitlements`: Tenant context with plan tier and role verification.
   - `test_billing_entitlements_endpoint`: Real-time tier limits and permissions endpoint.
   - `test_billing_checkout_endpoint`: Checkout session dispatch.
   - `test_scan_with_pricing_enrichment`: End-to-end scan with real-time pricing attribution and realizable savings.
   - `test_remediation_terraform_export`: End-to-end Terraform IaC plan export with safety snapshot.
   - `test_cancel_scan_endpoint`: Scan cancellation signal handling.

## Frontend Dashboard Verification
- **Framework**: Next.js 15 (TypeScript / React 19)
- **API Proxy**: Updated regex routing for Entra consent, billing entitlements, Stripe checkout, Terraform remediation, and scan cancellation.
- **Component Integrity**: Bracket matching and JSX nesting verified across `page.tsx` and `route.ts`.
