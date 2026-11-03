# Enterprise backend & contracts program

Living record of the **Enterprise Backend and Contracts** workstream (route parity, agent/GitOps contracts, scan concurrency, typed inventory APIs, platform migration visibility). Changes merge to `main`, regenerate `RELEASE_MANIFEST.json`, and run targeted pytest before push.

**Related specs:** Azure resource detail phases in [`specs/drafts/2026-11-02-azure-resource-detail.md`](../specs/drafts/2026-11-02-azure-resource-detail.md); route inventory in [`app/route_inventory.py`](../app/route_inventory.py) and [`docs/API_ROUTE_REGISTER.md`](API_ROUTE_REGISTER.md).

## Invariants

- **Three-tier route parity:** scanner service, API gateway (`services/gateway.py`), and dashboard BFF (`web-dashboard/app/api/[...path]/route.ts`) must agree with `ROUTES` in `app/route_inventory.py` (`tests/test_route_inventory.py`).
- **Scoped keys:** new `/api/v1/*` routes need an explicit inventory class; gateway enforces provider scope before upstream calls.
- **Agent execution:** worker TypeScript contracts stay aligned with `app/agent_contract.py`; drift guards run **before** step permits.
- **Scan concurrency:** interactive scans, async multi-cloud scans, and durable `scan-jobs` respect the Redis workspace lease when `CLOUDSAVER_DISTRIBUTED_SCAN_LOCK=true`.
- **Platform outbox:** workers refuse startup if `platform_outbox_intents` exists without migration **0033** lease columns.

## Contract backlog (BC-01–BC-14)

| ID | Theme | `main` anchor |
| --- | --- | --- |
| BC-01 | Engineering outbox read API reachable via gateway/BFF (404 fix) | `36afdc5` |
| BC-02 | Catalog routes: billable catalog, Azure resource types, typed tables, rules catalog | `36afdc5` |
| BC-03 | `cost_scope` forwarded on scan resource lists | `36afdc5` |
| BC-04 | Worker `checkAssignment` for paired `rightsize_sku` GitOps | `54e32ee` |
| BC-05 | `Task.payload` typing; expected-state guard before step permit | `54e32ee` |
| BC-06 | `sync-agent` passes `EnterpriseStore` for AST rightsize; `unreconciled()` includes `compute.resize` | `54e32ee` |
| BC-07 | Scan lease fencing: no async lease steal; `scan-jobs` 409 when lease held | `2c5fd36` |
| BC-08 | `arm_detail` query filter on scan resource list/export | `8928311` |
| BC-09 | List rows expose `arm_detail`; gateway forwards filter | `8928311` |
| BC-10 | `schema_capabilities` on `GET /api/v1/settings/cloud-status` | `8928311` |
| BC-11 | Worker guard for missing platform outbox lease columns | `8928311` |
| BC-12–14 | BFF parity: FinOps autopilot, saas-focus import, platform GitOps AST/PR routes | `2c5fd36` + `8928311` |

## Key modules

| Area | Path |
| --- | --- |
| Route inventory | `app/route_inventory.py` |
| Scan concurrency | `app/scan_concurrency.py`, `workers/tasks.py` (`RedisLease`) |
| Schema capabilities | `app/schema_capabilities.py` |
| Agent store / GitOps sync | `app/agent_store.py`, `app/gitops_api.py`, `agent-worker/src/contracts.ts` |
| Typed inventory | `app/typed_resources/`, `app/resource_api.py` |
| Platform outbox | `app/drift/outbox_store.py`, migration `0033_platform_outbox_lease` |

## Verification

```bash
python3 -m pytest tests/test_route_inventory.py tests/test_agent_unreconciled.py \
  tests/test_scan_concurrency.py tests/test_schema_capabilities.py -q
python3 scripts/release_manifest.py --check
cd agent-worker && node --test tests/*.test.ts
cd web-dashboard && npm run test:enterprise-ui   # BFF allowlist regressions
```

## Program status

**BC-01–BC-14 complete on `main` (through `8928311`).** Follow-on work is product-driven: integration tests with mocked ARM enrichment, dashboard `arm_detail` filter UX, optional CI workflow split for enterprise-ui (requires GitHub token with `workflow` scope), and pilot sign-off items in the Azure resource detail spec.
