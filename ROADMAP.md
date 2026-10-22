# CloudSaver roadmap after v0.4.1

1. Accept the release against real Entra test tenants, Stripe test-mode events,
   authorized Azure subscriptions and the intended Terraform toolchain. Complete
   browser QA and remediate inherited frontend dependency advisories.
2. Implement browser authorization-code/PKCE sign-in and consent callbacks with
   single-use state, nonce, memberships and explicit subscription RBAC approval.
3. Add a PostgreSQL transactional outbox and leased dispatcher for broker publish
   and notifications. Verify restart/broker/Redis failover; document at-least-once
   delivery and provider idempotency limits. Keep automatic alerts disabled.
4. Add authorized interactive job submission, idempotency, progress, lifecycle
   history and cooperative cancellation while preserving/versioning the current
   synchronous API contract deliberately.
5. Reconcile actual Cost Management data with retail meters, currency, period,
   tiers, discounts and commitments. Model backup/retention and net costs only
   with evidence; unsupported cases stay unknown.
6. Add existing-subscription billing portal/upgrades, retention, audit logs,
   deployment infrastructure, HTTPS ingress, observability and a tested restore
   process. Complete load/fault and incident exercises.

Consult TEST_REPORT.md for executed evidence. Preserve original Drive artifacts,
record remaining limits and deliver matching source/checksum packages. Ordinary
verification must not run remediation, send alerts, create live payments or claim
Gemini review that has not happened.
