# CloudSaver roadmap after v0.6.0

Source: [Advanced Features & Product Roadmap, v0.6.0–v1.0.0](https://docs.google.com/document/d/1Z-4CAVfSpimqBaxbNGAze_SWsbWdHwFP-bG0rccKK6Y/edit).
A text snapshot is retained in docs/drive-advanced-roadmap.txt. Its release dates,
production/compliance language and savings percentages are planning targets,
not acceptance evidence. The v0.5.0 source/guide was reviewed before development.

## v0.6.0 delivered milestone

Read-only GCP inventory and evidence-gated SQL review, native Kubernetes sampled
P95 request review, scoped AWS ingestion, provider UX, truthful observation
trends, import-only GCP/AWS/Azure Terraform and atomic forced-RLS persistence.
See IMPLEMENTATION_STATUS.md and TEST_REPORT.md for exact limits and checks.

## Finish v0.6 acceptance and the operational foundation

1. Accept AWS profiles/STS, GCP APIs/IAM/Monitoring, cluster metric sampling,
   Entra tokens, Stripe test-mode events and Terraform against authorized test
   systems. Complete browser QA. Remediate inherited dependency advisories with
   a planned compatible frontend upgrade.
2. Add exact GCP Billing Catalog SKU/currency/period attribution and customer
   billing reconciliation. Unsupported cases stay unknown. Add OpenCost/Kubecost
   allocation and evidence-based namespace/DaemonSet audits.
3. Add PostgreSQL transactional outbox/leased dispatcher, broker restart/failover
   acceptance, durable multi-cloud jobs, idempotency, progress, lifecycle history
   and cooperative cancellation. Preserve the synchronous API deliberately.
   Keep automatic alerts disabled until delivery audit/retry behavior is accepted.
4. Implement browser PKCE/consent callbacks with single-use state/nonce, memberships
   and explicit cloud-scope authorization. Finish billing portal, retention, audit,
   restore drills, deployment/HTTPS, observability and load/fault tests.

## Subsequent roadmap milestones

- **v0.7 GitOps:** customer repository OAuth, isolated branches and reviewed PRs;
  Terraform plan JSON cost/OPA checks. Import reviews alone do not authorize
  destruction. Require source mapping, backup evidence and independent approval.
- **v0.8 anomalies/rightsizing:** billing time series, evaluated models, baseline
  and seasonality evidence, workload compatibility and measurable confidence.
  Do not promise fixed gp2/ARM savings across contracts or workloads.
- **v0.9 tags/showback:** tenant-scoped policy definitions, compliance scorecards,
  ownership, allocation rules and customer-supplied unit economics.
- **v1.0 governance:** durable multi-stage approvals/snooze/exemption, independently
  accepted recovery plans, credential rotation and immutable audit storage before
  any separately authorized execution. SOC 2 needs a real audit; code cannot
  certify it.

Preserve original Drive documents/packages. Publish matching source/checksum and
verification artifacts to the project folder. Ordinary checks must not execute
remediation, send alerts, create payments or claim unperformed external review.
