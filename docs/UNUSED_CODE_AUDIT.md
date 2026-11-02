# Unused code audit (maintenance)

Last review: consolidated **scanner-service** architecture (`app.main` behind `services/gateway.py`).

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
