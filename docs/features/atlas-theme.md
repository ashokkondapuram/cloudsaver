# CloudSaver Atlas theme

Atlas is the **opaque enterprise visual system** described in the product Atlas specification: finance-friendly numerals, restrained borders, no glass or decorative motion, and shared tokens for light and dark modes.

## What is implemented

| Area | Status |
|------|--------|
| **`atlas` UI preset** | CSS tokens in `web-dashboard/app/theme-atlas.css`, selectable via platform workspace theme (`ui_theme_preset`) |
| **Semantic mapping** | Atlas `--cs-*` tokens bridge to existing `--surface`, `--text`, `--primary-fill`, chart colors |
| **Contracts** | `web-dashboard/lib/atlas-contracts.ts` (`ChartSeries`, `AtlasNotice`) |
| **Chart boundary** | `web-dashboard/components/charts/AnalyticsChart.tsx` (Recharts pilot, animation off, table fallback) |
| **Notifications adapter** | `web-dashboard/lib/notices.ts` (severity mapping + dedupe by id) |

## What is not integrated (by design)

The specification names **Nivo, Sileo, Arc UI, Fleetflow AI, BoardUI, Atrium, Cloudflare Code Mode** as references or future integrations. None of those packages are installed until official packages, licenses, and React compatibility are verified.

Do not add a second parallel token system: extend Atlas tokens through `theme-atlas.css` and existing semantic variables.

## Enabling Atlas for a workspace

1. Platform operator sets `ui_theme_preset` to `atlas` on the client workspace (portal **Dashboard appearance**).
2. Users reconnect or refresh the web dashboard; `UiThemeApplier` sets `data-ui-preset="atlas"`.
3. Users can still toggle light/dark unless a preset locks appearance (Atlas supports both).

## Pilot charts

Use `AnalyticsChart` with API-normalized `ChartSeries` payloads. Validate with `validateChartSeries` before render. Prefer the bundled table for accessibility and dense exports.

## Acceptance checklist (partial)

- [ ] Contrast review on real hardware for light/dark Atlas
- [ ] One production page wired to `AnalyticsChart` with live FinOps data
- [ ] Nivo pilot only after bundle and a11y comparison with Recharts
- [ ] Browser e2e for Atlas preset + nested dialogs (see UI data audit doc)
