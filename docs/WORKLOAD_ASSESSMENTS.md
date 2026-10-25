# Workload assessments — first enterprise platform increment

## Delivered scope

A read-only /workloads dashboard groups saved resource-level five-pillar assessments by current explicit application/environment ownership. It presents resource counts, risk/unknown/observed pillar counts, unassigned/ambiguous mappings, and VM/network review templates with prerequisites, steps, verification and recovery limitations.

This increment reuses existing authorized GET /api/v1/outcomes/ownership and paginated GET /api/v1/scans/{scan_id}/resources. It adds no backend route, migration, connector credential, dependency, agent action, approval record, or provider mutation. Existing Outcomes permissions and full-scope restrictions remain authoritative. BillingAdmin/TenantAdmin UI gating is a convenience, not a replacement for server authorization. No alternate data path is used after an authorization failure.

Open Resources and choose Workload assessments. Configure ownership through the existing Outcomes Application ownership workflow. The selected observation must be completed and live. Current mappings are not historical ownership; dependency coverage remains unknown.

## Safety and limits

Identity joins require provider, exact account/scope and resource identifier; Azure identifiers are case-insensitive. Names/tags do not establish membership. Conflicting equal-version mappings remain unassigned. No aggregate money or verified-savings claim is generated. Observed is not a compliance pass.

Only existing rule/check codes that match supported review templates produce guidance. Unsupported findings say so explicitly. Every preview is non-executable and requires current evidence plus separate exact approval. Protections remain visible. A smaller VM does not fix a vulnerability, and a network API success does not prove legitimate traffic works.

Resource loading is bounded to 10000 rows and ownership mappings. All resource pages must load successfully before a rollup is displayed. Empty, duplicate, changed, oversized or mismatched pages fail visibly; no partial totals are presented. These independent API reads are not an atomic historical snapshot. The user can refresh after ownership, authorization or evidence changes.

Tenant/token/scan changes remount the assessment and cancel old requests. Source errors do not silently reuse stale results. Workload and member displays are paginated locally after bounded loading.

## Verification

Dependency-free helper tests:

    node --test web-dashboard/unit/workloads.test.mjs

Existing dashboard checks:

    npm --prefix web-dashboard run typecheck
    npm --prefix web-dashboard run build
    npm --prefix web-dashboard run test:e2e -- e2e/workloads.spec.ts

Browser tests use intercepted test-only APIs; they do not establish real backend/RLS isolation. Existing real-stack, backend and authorization suites remain required. Test production-like signed-in navigation, logout, role/scope changes and live ownership on an authorized staging deployment before release.

The release manifest covers all tracked files. Before a merge-ready release, stage the source changes, regenerate RELEASE_MANIFEST.json with python scripts/release_manifest.py, and run its --check mode. Do not bypass the manifest gate. A stale manifest is a merge blocker.

## Deferred

No Wiz ingestion, dependency discovery, persisted cross-resource plans, new approvals, provider execution, financial reconciliation changes or automatic remediation are delivered here. The earlier backend-API package is superseded by this smaller integration using existing endpoints.
