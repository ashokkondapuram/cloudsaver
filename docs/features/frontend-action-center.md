# Frontend action center and scan lifecycle

Implemented remediation for Action Center source loading (FE-01/02/05/07/08), workspace scan polling (FE-03/04), and automatic scan coordination (FE-06).

- `web-dashboard/lib/source-state.ts` — per-source `SourceState` and API error classification
- `web-dashboard/lib/action-center-metrics.ts` — lane count helpers
- `web-dashboard/lib/scan-lifecycle.ts` — scan phase and poll backoff helpers
- `web-dashboard/lib/auto-scan-coordination.ts` — workspace-keyed cooldown and tab broadcast

Grafana job worker and backend paths are documented in `docs/BACKEND_IMPROVEMENTS.md` §5b.
