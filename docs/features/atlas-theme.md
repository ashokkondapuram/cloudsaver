# CloudSaver Atlas theme

Atlas is the **opaque enterprise visual system** described in the product Atlas specification: finance-friendly numerals, restrained borders, no glass or decorative motion, and shared tokens for light and dark modes.

## What is implemented

| Area | Status |
|------|--------|
| **`atlas` UI preset** | CSS tokens in `web-dashboard/app/theme-atlas.css`, selectable via platform workspace theme (`ui_theme_preset`) |
| **Semantic mapping** | Atlas `--cs-*` tokens bridge to existing `--surface`, `--text`, `--primary-fill`, chart colors |
| **Contracts** | `web-dashboard/lib/atlas-contracts.ts` (`ChartSeries`, `AtlasNotice`) |
| **Chart boundary** | `web-dashboard/components/charts/AnalyticsChart.tsx` — Recharts default, Nivo pilot (`NEXT_PUBLIC_CHART_ENGINE=nivo`) |
| **FinOps wiring** | `BillingEvidencePanel` maps `/finops/summary` daily rows via `lib/finops-chart.ts` |
| **Notifications adapter** | `web-dashboard/lib/notices.ts` (severity mapping, dedupe, toast bridge — Sileo-compatible pattern) |
| **§12 rollout tracker** | `web-dashboard/lib/atlas-page-rollout.ts` |
| **Governance board** | `FindingWorkflowBoard` on governance **Findings** tab |
| **Agent workspace** | Promoted `agent-event-log`; `CodeModePanel` stub |
| **Package notes** | [atlas-package-verification.md](./atlas-package-verification.md) |
| **WCAG checklist** | [atlas-wcag-checklist.md](./atlas-wcag-checklist.md) (sign-off row pending human review) |

## What remains product-owned

- Formal WCAG sign-off on real hardware (checklist started).
- Live Cloudflare Code Mode execution (stub only).
- Full §12 coverage of every route (see rollout tracker — Activity and others still **planned**).
- **Atrium** portal shell SDK — not integrated.

Do not add a second parallel token system: extend Atlas tokens through `theme-atlas.css` and existing semantic variables.

## Enabling Atlas for a workspace

1. Platform operator sets `ui_theme_preset` to `atlas` on the client workspace (portal **Dashboard appearance**).
2. Users reconnect or refresh the web dashboard; `UiThemeApplier` sets `data-ui-preset="atlas"`.
3. Users can still toggle light/dark unless a preset locks appearance (Atlas supports both).

## Charts

Use `AnalyticsChart` with API-normalized `ChartSeries` payloads. Validate with `validateChartSeries` before render. Prefer the bundled table for accessibility and dense exports.

Compare bundle size:

```bash
cd web-dashboard && du -sh node_modules/@nivo node_modules/recharts
```

## Acceptance checklist

- [x] One production page wired to `AnalyticsChart` with live FinOps data (`/allocation`)
- [x] Nivo pilot installed with env toggle and a11y table fallback retained
- [x] Browser e2e for Atlas preset + billing chart (`e2e/enterprise-ui-atlas-finops-chart.spec.ts`)
- [ ] Contrast review on real hardware for light/dark Atlas (see WCAG doc)
