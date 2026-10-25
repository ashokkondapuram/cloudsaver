> GitOps, reviewed remediation exports and plan-policy checks are restored. See [the restoration guide](FEATURE_RESTORATION_673C20A.md) for their relationship to current resource, agent and governance workflows.

# v0.7.0 GitOps and pre-merge guardrails

The product never runs Terraform, applies a plan or deletes cloud resources.
GitOps publishing writes a branch and draft PR only after a TenantAdmin explicitly
submits an owned live-scan selection. Growth/Enterprise Terraform entitlement is
required. Historical synthetic snapshots cannot be exported or published.

## Configure approved GitHub targets

Publishing defaults to disabled. Supply trusted operator environment configuration
on scanner-service (Compose forwards these names):

```text
CLOUDSAVER_GITOPS_PUBLISH=false
CLOUDSAVER_GITHUB_APP_ID=<numeric App ID>
CLOUDSAVER_GITHUB_APP_PRIVATE_KEY=<PEM private key from your secret manager>
CLOUDSAVER_GITOPS_TARGETS=[{"target_id":"infra","tenant_id":"11111111-1111-4111-8111-111111111111","repository":"your-org/infra","repository_id":12345,"base_branch":"main","installation_id":67890}]
```

Use the exact canonical repository name and numeric ID from your approved
installation. Configure only intended repositories with Contents and Pull requests
write access. Before enabling, review repository CI rules: a draft PR can trigger
the repository's own workflows. Exclude `.cloudsaver/reviews/` from automatic
Terraform discovery/apply jobs. This release has no self-service OAuth onboarding.

The App adapter signs a short-lived RS256 App JWT, requests a short-lived
installation token limited to the configured repository ID/permissions, verifies
repository metadata, and calls only api.github.com with redirect following off.
Neither App nor installation tokens are returned to the browser or persisted in
request history. Keep private keys in a deployment secret manager; never commit
them or put them in target JSON.

After operator test acceptance, set CLOUDSAVER_GITOPS_PUBLISH=true. A browser user
cannot enable publishing, change an installation or submit a repository URL.

## Review and publish

1. Select an owned completed live scan and a supported single-provider resource
   selection (1–50). Choose the configured repository in the GitOps panel.
2. Preview the exact files and PR title. Preview performs no external GitHub I/O.
3. Explicitly open the draft PR. Only three files are added under a deterministic
   `.cloudsaver/reviews/<review-id>/` directory: imports.tf, README.md and a
   checksum manifest. No existing resource definition is edited and no deletion
   or fabricated backup verification is generated.
4. Independently check resource/state ownership, dependencies, backups/retention
   and recovery. Generate and review a plan in a separate isolated working
   directory using read-only credentials. Existing state ownership matters:
   importing one resource into multiple states creates conflicting control.

API routes:

| Route | Authorization / behavior |
| --- | --- |
| GET /api/v1/gitops/targets | Authenticated; workspace targets and enable flag only |
| POST /api/v1/gitops/preview | TenantAdmin + Terraform entitlement; scan_id, target_id, resource_ids |
| POST /api/v1/gitops/requests | Same selection plus 16–128 character idempotency_key; explicit publishing |
| GET /api/v1/gitops/requests | Workspace history; limit 1–100 |
| GET /api/v1/gitops/requests/{id} | Owned request or 404 |
| POST /api/v1/policies/terraform/evaluate | Authenticated read-only analysis; plan and optional infracost JSON |

The request key is hashed at rest. Reusing it with different package bytes returns
409. A 600-second database lease coordinates publishers, with at most four
attempts; stale tokens cannot overwrite newer results. External I/O happens after
intent is committed. No database transaction is held during GitHub calls.

A timeout can happen after GitHub accepts an operation. Status becomes uncertain;
inspect history and retry the same selection/key. The adapter reconciles existing
PRs and never force-updates a branch. If an existing branch differs or the base
advanced during a partial publication, stop for manual review. Closed/ready PRs
are returned as existing history; they are not reopened or replaced. There is no
distributed exactly-once promise, automatic background replay or GitHub merge.
The browser retains its retry key in memory; keep API request keys if retrying
across browser reloads. New equivalent keys still use the same deterministic
review branch and reconcile GitHub, but create separate request-history rows.

## Offline Terraform checks

With Python 3.12 and a complete `terraform show -json` artifact:

```bash
python scripts/check_terraform_plan.py plan.json --policy finops-policy.json \
  --infracost infracost.json --output policy-report.json
```

The policy file is operator-owned, for example:

```json
{"required_tags":["Owner","CostCenter"],"max_monthly_increase_usd":"100","allow_deletes":false}
```

Exit codes: 0 means configured checks passed, 1 means policy violation, and 2 means
invalid/unsupported/unreadable input. Policy defaults block deletion/replacement
and supported orphan creation; tag/budget checks apply when configured. Empty,
incomplete or unknown-version plan formats are rejected. Input is bounded to 2 MB,
64 JSON levels and 10,000 resource changes. Reports omit raw before/after values,
variables and for_each keys. The API never persists raw submitted plan/cost JSON.

The checker accepts Terraform plan format_version 1.0–1.2. Association checks
cover declared Azure disk/public-IP, AWS EBS/EIP and GCP disk/regional-address
resources. Only supported attachment attributes and concrete IDs prove binding;
tags/depends_on/name-only references do not. Module-local static references are
supported; indexed, indirect module-output and externally managed associations
may require a separate reviewed workflow. This is a conservative structural
guardrail, not a general Terraform interpreter or native OPA engine.

Infracost support is a bounded v0.2 USD breakdown with explicit current/past
monthly totals, priced affected resource addresses and internally consistent
current totals. Missing/unsupported currency, partial pricing or delete pricing
stays unknown. A configured budget fails closed on unknown evidence. Numbers are
reported estimates, not verified billing or savings. The operator must generate
the Infracost report for the same trusted plan; this checker does not authenticate
artifact provenance or run the Infracost CLI.

## Composite GitHub Action

The reusable action is `.github/actions/finops/action.yml`. It assumes Python 3.12
is available and runs no dependency installs, Terraform or cloud requests. Inputs
are plan, policy and optional infracost paths. Pin the action to a reviewed commit
SHA before making its result a required merge check. Do not load checker/policy
code from an untrusted PR, use pull_request_target to execute PR code with secrets,
or expose cloud/GitHub credentials to forked workflows. Configure protected checks
and policy ownership in the repository; source files alone cannot enforce merges.

Native OAuth onboarding, GitLab/Bitbucket adapters, OPA execution, automatic
resource destruction and multi-stage approval execution remain roadmap work.
