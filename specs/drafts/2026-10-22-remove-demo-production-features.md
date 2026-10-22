# Remove demo mode and expand production dashboard

**Status:** Draft (implementation in progress)  
**Date:** Oct 22, 2026  
**Author:** Engineering

## Problem statement

Demo mode and synthetic fixtures let operators run the stack without cloud credentials, but they conflict with a production posture: illustrative costs, disabled exports, and bootstrap keys that are not tenant provisioning. Operators need azure-only execution, explicit `CLOUDSAVER_TENANTS`, and dashboard surfaces for multi-cloud scans, entitlements, scheduled scans, cost evidence, billing, and notification configuration.

## Proposed solution

1. Remove `CLOUDSAVER_MODE=demo`, `DEMO_ACCESS_KEY`, `demo_workspace`, and runtime synthetic scan paths.
2. Default Compose and setup scripts to `CLOUDSAVER_MODE=azure` with hashed workspace keys in `CLOUDSAVER_TENANTS`.
3. Extend `GET /api/v1/me` with plan limits, scheduling, alerts, and webhook configuration flags.
4. Expand the dashboard: multi-provider selection, billing/entitlements panel, operations (schedule/alerts), and cost evidence summary.
5. Relocate synthetic fixtures to `tests/fixtures/` for unit tests only.

## Out of scope

- Live Entra PKCE sign-in, Stripe test-mode acceptance, and real cloud scan verification in CI.
- Exposing notification webhook URLs to browsers (boolean configured flag only).

## Acceptance criteria

- [ ] `Settings.load()` rejects `demo` mode.
- [ ] No production code path calls synthetic scan fixtures.
- [ ] Dashboard shows entitlements, schedule/alerts status, and multi-provider scan controls without demo copy.
- [ ] `pytest` and `npm run build` pass.
- [ ] `scripts/smoke_stack.py` verifies health and workspace auth without requiring a scan.
