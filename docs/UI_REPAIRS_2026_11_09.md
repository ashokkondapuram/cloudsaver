# Dashboard UI repairs — 2026-11-09

Baseline: `ccd7c91` on main. Scope: dashboard shell, credential entry, dialogs, appearance controls, notification state and flat surfaces.

## Changes

- Credential entry has an accessible show/hide control, disables spelling/capitalization helpers and hides the value when submission starts. The value remains transient and is cleared by the existing submission flow.
- Login exposes a main landmark and describes session behavior without claiming the user is already signed in.
- Search uses its visible label as its accessible name and declares keyboard shortcuts separately.
- Appearance choices retain native button semantics and pressed states in a labeled group.
- Global navigation shortcuts cannot navigate behind an unrelated modal. Escape and focus restoration remain available.
- Clicking a dialog's interior padding does not dismiss it; actual backdrop clicks still dismiss it.
- Notification state clears on credential changes and failed polling. Responses from a disposed workspace request cannot update the new workspace.
- Flat surfaces have no backdrop blur or decorative CSS transitions/animations. The entrance wrapper renders content immediately. Progress spinners remain functional and respect reduced-motion preferences.
- Small table headings in the light theme use stronger text contrast.

## Verification

Node 24.22.1: production build and typecheck passed. Dashboard unit suite: 39 passed. Chromium console/UI selection: 11 passed, including mobile layout, light/dark axe checks, missing telemetry behavior, drawer keyboard focus, credential controls, flat surfaces and notification refresh failure. Final focused browser selection is recorded in `/tmp/ui-final-regressions.log`.

Browser journeys use synthetic API fixtures. These checks verify UI behavior and accessibility for the exercised views; they do not certify live identity/provider integrations or all pages. No existing running application service or retained volume was replaced. The test dashboard ran separately on port 3105.
