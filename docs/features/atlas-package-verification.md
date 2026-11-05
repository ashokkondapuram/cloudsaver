# Atlas package verification (2026-11)

| Reference | npm / product | Status in CloudSaver |
|-----------|---------------|----------------------|
| **Nivo** | `@nivo/core`, `@nivo/line`, `@nivo/scales` | Atlas preset uses Nivo with shared `lib/chart-theme.ts` (`--cs-*` tokens only) |
| **Recharts** | `recharts` | Default chart engine behind `AnalyticsChart` |
| **Sileo** | No verified OSS package matching spec | Use `lib/notices.ts` + AppShell toast (`atlasNoticeToToast`) |
| **Arc UI** | No separate install | Map to shared `components/ui/dialog`, `PageTabs`, command palette |
| **Fleetflow AI** | No verified npm workspace package | Agent workspace chronological `agent-event-log` |
| **BoardUI** | No verified npm package | `FindingWorkflowBoard` on governance Findings tab |
| **Atrium** | Product shell reference | Portal/workspace chrome only; no Atrium SDK |
| **Cloudflare Code Mode** | Worker bridge in `workers/code-mode-bridge` | API + UI when `CLOUDSAVER_CODE_MODE_ENABLED` and bridge URL or stub |

Record bundle impact after dependency changes:

```bash
cd web-dashboard && du -sh node_modules/@nivo node_modules/recharts
```
