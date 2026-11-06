# Wiz (CSPM) — optional read-only enrichment

When enabled, CloudSaver pulls **open issues** from the Wiz **GraphQL API** during scan ingestion (after Stream **E** Advisor signals) and attaches them to inventory as **`evidence.wiz_issues[]`**. The deterministic analysis service emits **`WIZ_SECURITY_POSTURE`** (Security pillar) on resources with a non-empty list.

## Enable

| Setting | Description |
|--------|-------------|
| `CLOUDSAVER_WIZ_ENABLED=true` | Feature flag (or `wiz_security_enabled` in platform `cloudsaver_integration`). |
| `CLOUDSAVER_WIZ_CLIENT_ID` | Wiz service account client id (Custom Integration / GraphQL API). |
| `CLOUDSAVER_WIZ_CLIENT_SECRET` | Wiz client secret (**use Cursor/app secrets**, not chat). |
| `CLOUDSAVER_WIZ_GRAPHQL_URL` | Tenant GraphQL endpoint, e.g. `https://api.us1.app.wiz.io/graphql`. |
| `CLOUDSAVER_WIZ_AUTH_URL` | Optional; default `https://auth.app.wiz.io/oauth/token` (use `https://auth.gov.wiz.io/oauth/token` for Gov). |
| `CLOUDSAVER_WIZ_PAGE_SIZE` | Optional; default `100` (max `500`). |
| `CLOUDSAVER_WIZ_MAX_ISSUES` | Optional; cap pulled issues per scan (default `5000`). |
| `CLOUDSAVER_WIZ_ISSUE_FILTER` | Optional JSON for GraphQL `filterBy` (defaults to open/in-progress + Critical/High/Medium). |

Implementation: `app/collectors/wiz_security.py`.

## Product parity

- **Rule id:** `WIZ_SECURITY_POSTURE` — listed under the **platform** family in `app/resource_catalog.py` (security pillar).
- **Matching:** Issues are joined to `inventory[]` rows by **canonical** resource id: Wiz `entitySnapshot.externalId` / `providerId` vs CloudSaver `resource_id` for `aws`, `azure`, or `gcp` (see `canonical_resource_id`).

## Not covered

- Wiz **vulnerability** findings (separate GraphQL surface), **full** posture dedupe across tools, or **write-back** to Wiz — add as follow-up.
