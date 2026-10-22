# CloudSaver v0.4.1 status

The current code extends the Drive v0.4.0 ZIP. Baseline documents under
docs/drive-v0.4.0 are historical source material, not present verification.

| Area | Implemented | Remaining work/acceptance |
| --- | --- | --- |
| Identity | Signed Entra v2 delegated access tokens, strict tenant/issuer/audience/scope claims and app roles; shared service auth | Live Entra acceptance, browser PKCE sign-in, consent callbacks, memberships and onboarding |
| Billing | Real SDK Checkout with trusted ownership/idempotency/fixed URLs; verified webhook persistence | Live Stripe acceptance, existing-subscription portal/upgrades and invoice UX |
| Entitlements | Persisted plans, subscription/resource limits, role/Terraform/Key Vault gates, paid schedule cadence | Contract metering and retention enforcement |
| Pricing | Exact supported retail meter evidence; unknown unsupported prices and net savings | Customer billing reconciliation, disk/VM storage models, discounts, commitments and remediation costs |
| Exports | Live disk/IP import review declarations and interactive Bash review scripts | Target Terraform/provider acceptance, verified independent backups and separately designed deletion workflows |
| Database | Atomic snapshot/domain writes, forced RLS, compatible lineage convergence | Restore drill and external production review |
| Worker | Opt-in Celery, durable attempts, Redis heartbeats, stale job-token checks and transactional cadence reservations | Publish/crash recovery and Redis failover acceptance; interactive submission/progress/cancellation |
| Outbox | Explicitly labeled, unused in-memory test foundation | Transactional PostgreSQL outbox, leased dispatcher, replay/audit and provider delivery semantics |
| Dashboard | Built Next.js table/history/exports, truthful unknown values and role-sensitive actions | Browser visual/accessibility/performance QA and complete interactive sign-in |
| Operations | Loopback Compose, restricted roles, migration step, PostgreSQL/Redis integration tests | Dependency remediation, ingress, monitoring, load/fault tests, deployment and backup acceptance |

There is no at-least-once or exactly-once alert-delivery guarantee. Heartbeats
and job tokens do not prove exactly-once execution across Redis failover and
PostgreSQL; a newer attempt on the same durable job fences its old token.
Dashboard scans are synchronous. In-memory cancellation/outbox demonstrations
are not exposed as durable production features.

Configuration accepts at most 100 subscriptions per workspace. Enterprise's tier
constant is not an unlimited estate or latency guarantee. Retail list prices are
estimates, not customer billing or realized savings. No zero-data-loss promise
is made by the import review generator.
