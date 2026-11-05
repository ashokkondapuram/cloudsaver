# CloudSaver Atlas theme

Atlas is the **opaque enterprise visual system** described in the product Atlas specification: finance-friendly numerals, restrained borders, no glass or decorative motion, and shared tokens for light and dark modes.

## What is implemented

| Area | Status |
|------|--------|
| **`atlas` UI preset** | CSS tokens in `web-dashboard/app/theme-atlas.css`, selectable via platform workspace theme (`ui_theme_preset`) |
| **§12 route coverage** | All primary nav routes in `lib/atlas-page-rollout.ts` at **pilot**; `AtlasRouteBoundary` on every authenticated page |
| **Semantic mapping** | Atlas `--cs-*` tokens bridge to existing `--surface`, `--text`, `--primary-fill`, chart colors |
| **Contracts** | `web-dashboard/lib/atlas-contracts.ts` (`ChartSeries`, `AtlasNotice`) |
| **Chart boundary** | `AnalyticsChart` — **Atlas: Nivo + `--cs-*` only**; other presets: Recharts (Nivo via `NEXT_PUBLIC_CHART_ENGINE=nivo`) |
| **FinOps wiring** | Cost allocation daily series; **Overview** expandable MTD mini-chart |
| **Activity charts** | Delivery backlog + AI usage summary on Activity tabs |
| **Governance board** | `FindingWorkflowBoard` on Findings tab |
| **Agent workspace** | Event log + Code Mode worker bridge |
| **Sileo notices** | `workspaceAtlasNotices` + `KeyNotices` + `atlasNoticeToToast` |
| **WCAG baseline** | Token contrast script + `enterprise-ui-atlas-wcag.spec.ts` (see checklist) |
| **Package notes** | [atlas-package-verification.md](./atlas-package-verification.md) |

## Enabling Atlas for a workspace

1. **In the dashboard:** Settings → **Access & API keys** → **Dashboard appearance** → choose **CloudSaver Atlas (enterprise)**. The choice is saved in this browser and applies immediately (Nivo charts, `--cs-*` tokens, Atlas shell).
2. **Platform operator:** set `ui_theme_preset` to `atlas` on the client workspace (portal **Dashboard appearance**).
3. **Deployment default:** set `CLOUDSAVER_DEFAULT_UI_THEME_PRESET=atlas` on the API and/or `NEXT_PUBLIC_DEFAULT_UI_THEME_PRESET=atlas` for the web build when no workspace assignment exists.
4. Users can still toggle light/dark unless a preset locks appearance (Atlas supports both).

## Charts

Use `AnalyticsChart` with API-normalized `ChartSeries` payloads. Validate with `validateChartSeries` before render. Prefer the bundled table for accessibility and dense exports.

## Acceptance checklist

- [x] Full §12 primary route rollout (`atlasRolloutComplete()`)
- [x] Overview FinOps mini-chart (lazy expand — no billing API call until opened)
- [x] Activity AnalyticsCharts (deliveries + AI history)
- [x] Automated WCAG AA baseline on VM (axe + token audit — see [atlas-wcag-checklist.md](./atlas-wcag-checklist.md))
- [ ] Final AA sign-off on operator physical hardware (one row pending in checklist)
