# Atlas WCAG review checklist

Use this checklist before declaring Atlas **WCAG 2.2 AA sign-off** for finance and governance surfaces. Automated checks supplement — they do not replace — review on real displays.

## Preset activation

- [ ] Workspace `ui_theme_preset` set to `atlas` (light and dark).
- [ ] `html[data-ui-preset=atlas]` present after reconnect; no glass/backdrop on primary panels (`theme-atlas.css`).

## Color and contrast

- [ ] Primary text on `--surface` ≥ 4.5:1 (body, table cells, chart axis labels).
- [ ] `--primary-fill` buttons and links ≥ 4.5:1 against label text.
- [ ] Chart line `--chart-line` distinguishable from grid `--chart-grid` without color-only meaning (table fallback always visible).
- [ ] Governance state badges and `.gov-result` variants readable in both modes.

## Motion and interaction

- [ ] Charts use `isAnimationActive={false}` / Nivo `animate={false}`.
- [ ] `prefers-reduced-motion` honored via existing global rules.
- [ ] Focus rings visible on dialog triggers, plan board cards, and billing filters.

## Charts and data tables

- [ ] Every `AnalyticsChart` renders `AnalyticsChartTable` with the same series (screen reader + export path).
- [ ] FinOps billing panel: daily trend chart + inspect daily coverage details remain keyboard reachable.

## Dialogs and nested workflows

- [ ] Governance finding drawer: focus trap, Escape closes, return focus to triggering control.
- [ ] Command palette and workspace menus operable via keyboard (UI data audit regression).

## Automated smoke (local)

```bash
cd web-dashboard
npm run typecheck
npm run test:enterprise-ui -- e2e/enterprise-ui-atlas-finops-chart.spec.ts
```

Playwright can run `@axe-core/playwright` on Cost allocation with Atlas preset when extended — not required for partial sign-off.

## Sign-off record

| Reviewer | Date | Scope | Result |
|----------|------|-------|--------|
| _pending_ | | Atlas pilot (allocation chart, governance board, agents) | |
