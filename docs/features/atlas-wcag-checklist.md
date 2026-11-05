# Atlas WCAG review checklist

Use this checklist before declaring Atlas **WCAG 2.2 AA sign-off** for finance and governance surfaces. Automated checks supplement — they do not replace — review on physical displays (laptop, external monitor, tablet).

## Preset activation

- [x] Workspace `ui_theme_preset` set to `atlas` (light and dark).
- [x] `html[data-ui-preset=atlas]` present after reconnect; opaque surfaces in `theme-atlas.css`.

## Color and contrast

- [x] Static Atlas token pairs ≥ 4.5:1 (`node scripts/atlas-contrast-audit.mjs`).
- [ ] Primary controls verified on **your** hardware in light and dark (buttons, links, chart axes).
- [ ] Chart line distinguishable from grid without color-only meaning (table fallback always visible).

## Motion and interaction

- [x] Charts use animation off (Recharts / Nivo).
- [x] `prefers-reduced-motion` honored via global rules.
- [ ] Focus rings verified on dialog triggers, plan board cards, billing filters (manual spot check).

## Charts and data tables

- [x] `AnalyticsChart` always renders `AnalyticsChartTable`.
- [x] FinOps allocation + Activity delivery/AI charts wired.

## Dialogs and nested workflows

- [ ] Governance finding drawer keyboard retest on hardware.
- [ ] Command palette operable via keyboard (regression from UI data audit).

## Automated smoke (CI / Cloud Agent VM)

```bash
cd web-dashboard
npm run typecheck
node scripts/atlas-contrast-audit.mjs
node unit/atlas-rollout-operations.test.mjs
npm run test:enterprise-ui -- e2e/enterprise-ui-atlas-wcag.spec.ts
npm run test:enterprise-ui -- e2e/enterprise-ui-atlas-finops-chart.spec.ts
```

## Sign-off record

| Reviewer | Date (America/Toronto) | Scope | Result |
|----------|------------------------|-------|--------|
| Cloud Agent VM (axe + token audit) | 2026-11-05 (Toronto) | Atlas preset on Overview, allocation, activity — `#main-content` scope | **Automated AA baseline passed** (axe 2.1 AA tags, zero violations; token contrast PASS light/dark) |
| Product / design owner | _pending_ | Physical hardware (external monitor, calibrated laptop) | Required for final AA attestation |

**Real hardware:** Run the same Playwright axe spec locally with `data-ui-preset=atlas`, then spot-check contrast outdoors/indirect light if your users work in varied lighting. Record the reviewer row above when complete.
