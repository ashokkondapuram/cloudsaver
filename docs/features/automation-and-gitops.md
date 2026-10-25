# Automation and GitOps

Automation and GitOps turns findings from an owned, completed live scan into reviewable artifacts: Terraform import declarations, interactive Bash cleanup scripts for a few Azure finding types, and draft pull requests in operator-approved GitHub repositories. It also checks a saved Terraform plan offline against deletion, tag, association, cost and commitment policies before you merge. CloudSaver never executes the generated code, never applies Terraform and never force-updates a branch. Every artifact still needs your independent review and your repository's normal approval process.

Last reviewed against the code on Oct 25, 2026.

## Where to find it

- **Route:** `/automation` ([web-dashboard/app/automation/page.tsx](../../web-dashboard/app/automation/page.tsx) renders `ConsolePage view="automation"`, which shows `Automation` from [WorkspaceViews.tsx](../../web-dashboard/components/WorkspaceViews.tsx)).
- **Navigation label:** **Automation & GitOps**, in the **ACT & GOVERN** group ([AppShell.tsx](../../web-dashboard/components/AppShell.tsx)).
- **Tabs:**
  - **Review packages** — `GitOpsPanel` in [GitOpsPanel.tsx](../../web-dashboard/components/GitOpsPanel.tsx).
  - **Plan guardrails** — `PlanPolicyPanel` in [GitOpsPanel.tsx](../../web-dashboard/components/GitOpsPanel.tsx), including `AutomaticPlanPreview` from [V150Views.tsx](../../web-dashboard/components/V150Views.tsx).
  - **Execution history** — `ExecutionSyncTimeline` from [V150Views.tsx](../../web-dashboard/components/V150Views.tsx), listing paired agent GitOps synchronizations.
- **Per-finding code review:** The **Review code** tab in the finding drawer and the **Review selected resources** drawer both use `CodeReview` in [drawer/FindingDrawer.tsx](../../web-dashboard/components/drawer/FindingDrawer.tsx).
- **Who can see it:** Every signed-in user can open the page, see approved repositories, review request history and run offline plan checks. Only a `TenantAdmin` whose plan includes Terraform export can prepare or publish review packages or generate Terraform. Only a `TenantAdmin` can generate Bash scripts.

## What you can do

### Generate code for a finding

1. Open a finding (or select several and choose **Review selected resources**), then open **Review code**.
2. Select **Preview Terraform imports** or **Preview Bash script**.
3. Inspect the generated file, then copy or **Download** it.

Requirements shown in the drawer:

- The scan is completed and not a historical synthetic snapshot.
- You select 1–50 unique resources from one provider.
- **Terraform** supports `ORPHANED_DISK`, `UNASSOCIATED_PUBLIC_IP`, `ORPHANED_NIC`, `ORPHANED_NSG`, `IDLE_APP_GATEWAY`, `AWS_UNATTACHED_EBS`, `AWS_UNASSOCIATED_EIP`, `AWS_IDLE_RDS`, `GCP_UNATTACHED_DISK`, `GCP_UNASSIGNED_ADDRESS` and `GCP_IDLE_CLOUD_SQL`, and your plan must include Terraform export.
- **Bash** supports only Azure `ORPHANED_DISK`, `UNASSOCIATED_PUBLIC_IP`, `ORPHANED_NIC` and `ORPHANED_NSG`, and is blocked when any selected finding shows protected intent (for example retention or disaster-recovery tags).

### Open a draft pull request

1. Go to **Review packages** and choose an approved repository and base branch.
2. Select up to 50 resources with supported findings from one provider.
3. Select **Preview review package** and expand each file to inspect it.
4. Confirm that you reviewed the files and understand the repository may run CI, then select **Open draft PR**.
5. Track the result in **Review request history**, which shows the status (`pending`, `publishing`, `open` or `uncertain`), the attempt count and a link to the pull request.

If publishing fails, retry from the same preview. The browser reuses its idempotency key, so a retry resumes the same request instead of creating a duplicate.

### Check a Terraform plan before merging

- **Automatic preview:** In **Plan guardrails**, `AutomaticPlanPreview` builds the import review package for the selected scan and returns it with a `review_required` policy decision. Repository CI must still produce the real plan.
- **Offline evaluation:** Expand **Advanced: offline Terraform plan evaluation**, upload a Terraform plan JSON file (`terraform show -json` output) and optionally an Infracost JSON file (combined under 1.9 MB), then select **Check plan**. The result shows **Pass** or **Review required**, the number of managed resources checked, the cost evidence status, the estimated monthly change and each issue with its code and address.

### Look up where a resource is defined

Call `GET /api/v1/gitops/resource-mapping?resource_id=...` to look up an operator-supplied index entry. The resource must occur in the latest visible owned scan, pass current cloud-scope authorization, and map to a repository explicitly granted to the workspace. Foreign, unobserved and ungranted entries receive the same 404. The response returns repository, file path and IaC kind. This read-only API is also forwarded by the dashboard proxy; no dedicated screen or generated AST patch is claimed.

## How it works

### Remediation exports

- [app/remediation.py](../../app/remediation.py) (`generate_script`) builds a Bash script for an owned, completed live Azure scan. It validates each ARM ID against the finding's rule and an authorized subscription and refuses protected findings. The script checks the active Azure tenant, requires an interactive terminal, asks you to type each full resource ID before deleting it, re-reads live tags and attachment state, and for disks creates and verifies a pre-deletion snapshot tagged for 90-day retention first. The module never calls Azure or a shell.
- [app/remediation_terraform.py](../../app/remediation_terraform.py) generates import-only HCL with no deletion, apply or guessed configuration. `generate_terraform_hcl` covers Azure with one provider alias per subscription; `generate_cloud_terraform_hcl` adds AWS and Google Cloud with one provider per file and rejects Kubernetes. Labels are stable SHA-256 hashes of the resource ID.

### Review packages and draft pull requests

1. [app/gitops_api.py](../../app/gitops_api.py) checks the role and entitlement, loads the owned scan and calls `build_review` in [app/gitops.py](../../app/gitops.py).
2. `build_review` writes three files under `.cloudsaver/reviews/<review_id>/`: `imports.tf`, `README.md` and `manifest.json` (`action: import_review_only`, `automatic_deletion: false`). The review ID is a UUIDv5 derived from the scan, resources, repository, base branch and the Terraform SHA-256 hash, so the same selection always produces the same package and branch (`cloudsaver/review-<review_id>`).
3. On publish, [app/gitops_store.py](../../app/gitops_store.py) (`ReviewRepository`) commits the request intent before any external call, keyed by a SHA-256 digest of your idempotency key, and fences the publisher with a 10-minute lease.
4. `GitHubApp.publish` mints a GitHub App installation token restricted to the single configured repository with `contents` and `pull_requests` write permissions. It verifies the repository ID and name and that the repository is not archived, then creates a tree, commit, branch and draft pull request with `maintainer_can_modify: false`. If a matching pull request already exists, it verifies that each file's blob hash matches the preview and returns it. If the branch exists with different content, it stops for manual review.
5. Any GitHub error or uncertain response leaves the request `uncertain` so you can inspect it and retry with the same key.

### Paired agent synchronization

When an approved agent task includes a `gitops.terraform.sync` step, [app/agent_gitops_sync.py](../../app/agent_gitops_sync.py) generates a Terraform JSON review fragment for the one approved tag, label or annotation merge (`generate_synchronized_terraform_patch`, using `TERRAFORM_RESOURCE_MAP`). It publishes `metadata.tf.json` and `evidence.json` under `cloudsaver/agent-reviews/<task_id>/` on a `cloudsaver/agent-<fingerprint>` branch. Publishing requires a current human approval, the step's single-use permit and successful evidence digests from earlier steps. The journal entry in `agent_gitops_syncs` records `parity_verified: false`. An uncertain repository outcome becomes `needs_reconciliation` and is never replayed. `POST /api/v1/gitops/sync-agent` returns the same bundle as a preview without publishing.

### Terraform plan policy checks

[app/plan_policy.py](../../app/plan_policy.py) (`evaluate_plan`) accepts Terraform plan `format_version` 1.0–1.2 with complete `resource_changes` and `configuration.root_module`, and optional Infracost JSON version 0.2. Input is limited to 2 MB, 64 levels of nesting and 200,000 nodes, and duplicate keys and non-finite numbers are rejected. Issue codes:

| Code | Raised when |
| --- | --- |
| `DESTRUCTIVE_CHANGE` | A managed resource is deleted or replaced and the policy does not allow deletes |
| `REQUIRED_TAGS` | A created or updated resource lacks a known, nonempty required tag or label |
| `ORPHAN_RESOURCE` | A new disk, public IP, EBS volume, Elastic IP or Google address has no supported planned attachment |
| `ASSOCIATION_UNKNOWN` | The resource's configuration is unavailable, so association cannot be checked |
| `INSTANCE_REVIEW_REQUIRED` | An indexed (`count` or `for_each`) resource needs instance-level review |
| `COST_BUDGET_EXCEEDED` | The estimated monthly increase exceeds `max_monthly_increase_usd` |
| `COST_EVIDENCE_REQUIRED` | A budget is configured but complete USD Infracost evidence is missing |
| `CLEAN_BASELINE_APPROVAL_REQUIRED` | A commitment, reservation or provisioned AI capacity change needs an independently reviewed usage baseline ([app/commitment_arbitrage.py](../../app/commitment_arbitrage.py)) |

Results mask indexed keys in addresses and never include raw before or after values.

### Resource mapping index

[app/gitops_ast_mapper.py](../../app/gitops_ast_mapper.py) (`GitOpsAstMapper`) loads `CLOUDSAVER_GITOPS_AST_INDEX` as a JSON object keyed by cloud resource ID. Each entry provides `repository`, `file_path` and `iac_kind`, which `lookup` returns as a `ResourceMapping`. A `patch_preview` helper exists for Terraform and OpenTofu but returns only a placeholder import block and is not exposed through the API.

## API reference

All paths are served by the scanner service and forwarded by the API gateway ([services/gateway.py](../../services/gateway.py)). Every route requires an authenticated workspace credential.

| Method | Path | Purpose | Required role/scope |
| --- | --- | --- | --- |
| POST | `/api/v1/scans/{scan_id}/remediation` | Generate the interactive Bash review script (`resource_ids`, 1–50) | `TenantAdmin` |
| POST | `/api/v1/scans/{scan_id}/remediation-terraform` | Generate import-only Terraform HCL (`resource_ids`, 1–50) | `TenantAdmin`; Terraform export entitlement |
| GET | `/api/v1/gitops/targets` | Approved repositories for your workspace and whether publishing is enabled | Any authenticated caller |
| POST | `/api/v1/gitops/preview` | Build a review package without publishing | `TenantAdmin`; Terraform export entitlement |
| POST | `/api/v1/gitops/preview-and-evaluate` | Build a review package with a `review_required` policy projection | `TenantAdmin`; Terraform export entitlement |
| POST | `/api/v1/gitops/requests` | Publish a draft pull request (adds `idempotency_key`, 16–128 characters) | `TenantAdmin`; Terraform export entitlement; publishing enabled |
| GET | `/api/v1/gitops/requests` | Review request history (`limit` 1–100) | Any authenticated caller; scan must be visible |
| GET | `/api/v1/gitops/requests/{request_id}` | One review request | Any authenticated caller; scan must be visible |
| GET | `/api/v1/gitops/resource-mapping` | Look up `resource_id` in the resource mapping index | Any authenticated caller |
| POST | `/api/v1/gitops/sync-agent` | Preview the paired GitOps bundle for an agent task (`task_id`, `plan_hash`) | `TenantAdmin`; Terraform export entitlement |
| GET | `/api/v1/gitops/syncs` | Paired agent GitOps synchronization journal | Any authenticated caller |
| POST | `/api/v1/policies/terraform/evaluate` | Evaluate a Terraform plan (`plan`, optional `infracost`) | Any authenticated caller |

Request bodies are limited to 2 MB.

## Data and evidence

- **`gitops_requests`** ([migrations/versions/0006_gitops_requests.py](../../migrations/versions/0006_gitops_requests.py)) stores the scan, idempotency digest, package fingerprint, target, repository, branch, status, attempts (0–4), lease and the GitHub result (pull request URL, number, state and draft flag). The runtime refuses to start against PostgreSQL unless this table has forced row-level security and is not owned by the runtime role.
- **`agent_gitops_syncs`** ([migrations/versions/0020_billing_and_agent_gitops.py](../../migrations/versions/0020_billing_and_agent_gitops.py)) keeps only linkage and replay fences: task ID, plan hash, step evidence digest, target, repository, state, fingerprint and result.
- **Generated artifacts** are returned to you and, when published, stored in the target repository. CloudSaver does not keep a separate copy of exported HCL or scripts.
- **Plan evaluations** are processed transiently and are not stored.

## Permissions

| Action | Required |
| --- | --- |
| View targets, history, sync journal, resource mappings | Any authenticated workspace caller |
| Evaluate a Terraform plan | Any authenticated workspace caller |
| Generate a Bash script | `TenantAdmin` |
| Generate Terraform, preview or publish review packages, preview agent sync bundles | `TenantAdmin` with the Terraform export plan entitlement |

GitOps targets are bound to a workspace by the operator. A target that belongs to another workspace is rejected.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `CLOUDSAVER_GITOPS_TARGETS` | JSON array (at most 100) of targets with exactly `target_id`, `tenant_id`, `repository` (`owner/name`), `repository_id`, `base_branch` and `installation_id` | `[]` |
| `CLOUDSAVER_GITOPS_PUBLISH` | Set to `true` to enable draft pull request publishing | `false` |
| `CLOUDSAVER_GITHUB_APP_ID` | Numeric GitHub App ID; required when publishing is enabled | Unset |
| `CLOUDSAVER_GITHUB_APP_PRIVATE_KEY` | GitHub App private key used to sign app tokens; required when publishing is enabled. Store it in a secrets manager. | Unset |
| `CLOUDSAVER_PLAN_POLICY` | JSON object with optional `max_monthly_increase_usd`, `required_tags` (up to 20 names) and `allow_deletes` (boolean) | `{}` (deletes blocked, no tag or budget rules) |
| `CLOUDSAVER_GITOPS_AST_INDEX` | JSON object mapping cloud resource IDs to `{repository, file_path, iac_kind}` | `{}` |

## Guardrails and limitations

- **Review artifacts only.** CloudSaver never runs Terraform or Bash, never applies changes and never merges pull requests. Pull requests are always drafts.
- **Import-only Terraform.** Exports contain `import` blocks and provider configuration, not resource settings or deletions. Use a new directory and read-only credentials, and do not import resources already managed in another state.
- **Destructive Bash is gated.** Scripts require typed confirmation for each resource, abort on protected or unreadable tags, and recheck state before deleting. Azure state can still change between the final check and the delete.
- **No force-push.** An existing branch with different content stops publishing for manual review.
- **Attempt limit.** A review request allows at most four publish attempts.
- **Static policy checks.** Association checks cover only the supported attributes. External, dynamic or indirect relationships still need review, and cost estimates depend on the Infracost evidence you supply.
- **Paired sync is not parity proof.** A draft pull request does not show that runtime and IaC match.
- **Resource mapping is a lookup.** The AST index is operator-supplied JSON; CloudSaver does not parse repositories to build it.

## Tests

- [tests/test_remediation.py](../../tests/test_remediation.py) — Bash script generation and validation.
- [tests/test_remediation_terraform.py](../../tests/test_remediation_terraform.py) — Terraform import generation across providers.
- [tests/test_gitops.py](../../tests/test_gitops.py) — review packages, GitHub App publishing and idempotency.
- [tests/test_plan_policy.py](../../tests/test_plan_policy.py) — offline Terraform plan policy checks.
- [tests/test_gitops_ast_mapper.py](../../tests/test_gitops_ast_mapper.py) — resource mapping index.
- [tests/test_v150_workflows.py](../../tests/test_v150_workflows.py) — paired agent GitOps synchronization.
- [web-dashboard/e2e/v150.spec.ts](../../web-dashboard/e2e/v150.spec.ts), [web-dashboard/e2e/ui.spec.ts](../../web-dashboard/e2e/ui.spec.ts), [web-dashboard/e2e/lean.spec.ts](../../web-dashboard/e2e/lean.spec.ts) — browser coverage of automation views and code review.

## Related docs

- [GitOps and pre-merge guardrails](../GITOPS.md)
- [Agentic worker](../AGENTIC_WORKER.md)
- [Agent worker](agent-worker.md)
- [Production hardening](../PRODUCTION_HARDENING.md)
- [Environment variables](../ENVIRONMENT.md)
