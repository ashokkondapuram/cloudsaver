# Cloudflare Code Mode

Code Mode runs **operator-reviewed JavaScript transforms** inside an isolated Cloudflare Worker. CloudSaver stores an append-only audit trail; snippets are validated in Python before the worker bridge executes them.

## Operator configuration

| Variable | Purpose |
|----------|---------|
| `CLOUDSAVER_CODE_MODE_ENABLED=true` | Enables tenant API |
| `CLOUDFLARE_CODE_MODE_BRIDGE_URL` | HTTPS base URL of the deployed worker (e.g. `https://code-mode.example.com`) |
| `CLOUDFLARE_CODE_MODE_BRIDGE_SECRET` | Shared secret (≥32 chars); sent as `X-CloudSaver-Code-Mode-Secret` and HMAC key |
| `CLOUDSAVER_CODE_MODE_STUB=true` | Local/test stub executor (no worker HTTP call) |

Deploy the reference worker:

```bash
cd workers/code-mode-bridge
wrangler secret put BRIDGE_SECRET
wrangler deploy
```

Point `CLOUDFLARE_CODE_MODE_BRIDGE_URL` at the worker origin (the handler listens on `POST /run`).

## Snippet contract

Only this shape is accepted:

```javascript
function transform(input) {
  return { ...input, normalized: true };
}
```

Forbidden: `import`, `fetch`, `eval`, `Function`, `require`, `globalThis`, etc.

## API

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/code-mode/status` | Deployment flags (no secrets) |
| GET | `/api/v1/code-mode/runs` | Recent runs for the workspace |
| GET | `/api/v1/code-mode/runs/{id}` | Run + audit events |
| POST | `/api/v1/code-mode/runs` | Human `TenantAdmin`; body: `request_key`, `snippet`, `input`, `acknowledge_sandbox: true` |

Gateway forwards these routes to the scanner service ([services/gateway.py](../../services/gateway.py)).

## UI

Agent workspace **Code Mode** panel ([CodeModePanel.tsx](../../web-dashboard/components/code-mode/CodeModePanel.tsx)) surfaces status, a sandbox run form, and run history.

## Relationship to agent `runCode`

Agent connector execution still uses the TypeScript worker ([agent-worker/src/runtime.ts](../../agent-worker/src/runtime.ts)). Code Mode is a **separate** sandbox for short transforms, not connector plans.
