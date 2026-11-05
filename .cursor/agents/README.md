# CloudSaver Cursor subagents

Specialized agents for local dashboard work. The **parent agent** picks one or chains them (audit → logs → fix → re-audit).

## Pipeline

```text
User report / UI change
        │
        ├─► ui-field-auditor ───────► Per-field data audit → invokes fixers → re-audit
        │
        ├─► browser-tab-auditor ──► Tab audit report (pass/fail per tab)
        │
        ├─► docker-log-analyst ───► Stack verdict + log evidence (502/500/crash)
        │
        ├─► backend-fixer ────────► Python/API/store/gateway fix + rebuild + verify
        │
        └─► ui-fixer ─────────────► Code + CSS (+ hand off API issues to backend-fixer)
```

| Agent | Role | Triggers | Does not |
|-------|------|----------|----------|
| **ui-field-auditor** | Field-level “is data showing?” audit; delegates to fixers | User asks if data visible; after UI changes; field blanks vs empty states; orchestration before merge | Replace ui-fixer for large fixes unless re-audit only |
| **browser-tab-auditor** | Read-only UI verification in built-in browser | After drawer/page UI changes; before merge; user says tab broken/blank; parent wants proof | Edit code, restart Docker, commit |
| **docker-log-analyst** | Compose logs + health snapshot | After deploy/rebuild; UI shows upstream/502/500; scan or API failures; user asks for Docker logs | Fix code unless parent asked |
| **backend-fixer** | Scanner, gateway, store, workers — minimal Python fixes | 500/502 tracebacks; missing API data; resource/scan endpoints; migrations | Frontend/CSS (ui-fixer) |
| **ui-fixer** | End-to-end fix in `web-dashboard/` | Layout/CSS bugs; tabs not clickable; drawer issues; stale dashboard image | Backend-only bugs (backend-fixer) |

## Recommended chains

| Situation | Order |
|-----------|--------|
| “Is data showing on this screen?” | **ui-field-auditor** → (fixers as needed) → re-audit |
| “This tab is broken” | **browser-tab-auditor** → **ui-fixer** (use audit as acceptance checklist) |
| Field blank but tab passes | **ui-field-auditor** → **ui-fixer** or **docker-log-analyst** |
| “502 / upstream error” | **docker-log-analyst** → **backend-fixer** → **ui-fixer** or **ui-field-auditor** if UI still wrong |
| “Fix the backend / API” | **backend-fixer** (logs first if unknown) |
| “Shipped drawer/CSS change” | **ui-fixer** (build + Docker) → **browser-tab-auditor** |
| “Is the stack healthy?” | **docker-log-analyst** only |

## Defaults (CloudSaver)

- Dashboard URL: `http://127.0.0.1:3000` (loopback only).
- Resource drawer audit: `/resources` → open one row → sweep drawer tabs.
- Rebuild after UI/CSS: `docker compose build web-dashboard && docker compose up -d web-dashboard`.
- Rebuild after backend: `docker compose build scanner-service api-gateway && docker compose up -d scanner-service api-gateway`.

See each agent file for checklists and report formats.
