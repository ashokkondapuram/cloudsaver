# Unused code audit (maintenance)

Last review: consolidated **scanner-service** architecture (`app.main` behind `services/gateway.py`).

## Legacy ARG rule IDs — migrated to catalog (2026-11)

Historical scan rows and identity policy overrides normalize through `app/rule_id_canonical.py`.

| Legacy `rule_id` | Canonical catalog `rule_id` |
| --- | --- |
| `ORPHANED_DISK` / `ORPHANED_DISKS` | `AZURE_DISK_UNATTACHED_RETENTION` |
| `UNASSOCIATED_PUBLIC_IP` / `UNASSOCIATED_PUBLIC_IPS` | `AZURE_PUBLIC_IP_UNASSOCIATED` |
| `STOPPED_VM` / `STOPPED_VMS` | `AZURE_VM_STOPPED_RESIDUAL_COST` |
| `EMPTY_APP_SERVICE_PLAN` / `EMPTY_APP_SERVICE` | `AZURE_ASP_EMPTY_PAID_PLAN` |
| `UNDERUTILIZED_VM` | `AZURE_VM_RIGHTSIZING_UTILIZATION` |
| `UNDERUTILIZED_APP_SERVICE_PLAN` | `AZURE_ASP_UNDERUTILIZED_SKU` |
| `IDLE_APP_GATEWAY` | `AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR` |
| `K8S_CPU_OVERSIZED` / `K8S_MEMORY_OVERSIZED` | `K8S_CONTAINER_CPU_OVERREQUEST` / `K8S_CONTAINER_MEMORY_OVERREQUEST` |

**Still remediation-only (no FAMILIES twin):** `ORPHANED_NIC`, `ORPHANED_NSG`.

Database: Alembic **`0034_canonical_rule_ids`** (core) and **`i0007_canonical_rule_ids`** (identity catalog overrides).

## Removed (not referenced by Compose, gateway, or tests)

| Path | Reason |
| --- | --- |
| `services/scanner.py` | Re-export of `app.main`; Compose runs `uvicorn app.main:create_app` directly |
| `services/tenant.py` | Split tenant microservice; routes live on scanner-service |
| `services/analytics.py` | Split analytics microservice; `app.analytics.summarize` used in-process |
| `services/notification.py` | Split notification microservice; delivery on scanner-service |

## Catalog rules — kept (all in use)

| Category | Why kept |
| --- | --- |
| **51 `FAMILIES` rule IDs** | Evaluated by `evaluate_inventory` (Azure legacy suffix, multicloud family, Kubernetes) |
| **Legacy ARG `rule_id`s** (`ORPHANED_DISK`, `STOPPED_VM`, …) | Still emitted by `app/scanner.py` Resource Graph queries and referenced in workflow routing, pricing, remediation |
| **Metrics-only K8 rules** (`K8S_CPU_OVERSIZED`, `K8S_MEMORY_OVERSIZED`) | Emitted by `app/scanner_kubernetes.py` when inventory binding is metrics-only |
| **Catalog successors** (`K8S_CONTAINER_CPU_OVERREQUEST`, …) | Full rule evaluations with patch preview |

Do not delete legacy finding `rule_id`s until scans no longer persist them and migrations normalize historical rows.

## Active `services/` modules

- `gateway.py` — API gateway
- `common.py` — shared FastAPI helpers
- `agent_gateway.py` — agent ingress
- `engineering_routes.py`, `governance_routes.py` — gateway route registration
