# Platform-issued offline license tokens

The platform portal can issue a signed bearer license at **Workspace → Keys → Issue license token**. The token includes a required expiry, workspace/customer identity, roles, explicit provider and cloud-scope snapshots, plan entitlements, issue/not-before times, a unique license ID, audience, issuer and schema version. JWT contents are readable; no cloud credential, signing private key or connection secret is embedded.

CloudSaver validates the signature and claims using locally pinned RSA public keys. It does not query the platform database, identity service, Keycloak, a remote JWKS URL or an introspection endpoint. Its own resource/connection registry remains necessary for resource data and operational safety: the workspace must exist locally, its customer must match when registered, and its locally enabled status and configured cloud scopes still constrain the signed grant. A token cannot provision connections or authorize a scope absent from the core registry.

## One-command local setup

```sh
./start.sh --auth-mode license
```

Startup generates a persistent RSA-3072 signing key and key ID, mounts the private key **only** into the platform identity service, passes public-key trust to CloudSaver, and consolidates settings into the ignored private `.env`. Keycloak can keep running for identity administration, but token validation in this mode is entirely offline. Later starts preserve the signing key. A missing previously registered private key stops startup rather than silently rotating it.

The important generated settings are:

- Platform: `PLATFORM_LICENSE_PRIVATE_KEY_FILE`, `PLATFORM_LICENSE_KEY_ID`, `PLATFORM_LICENSE_ISSUER`, `PLATFORM_LICENSE_AUDIENCE`.
- CloudSaver: `CLOUDSAVER_AUTH_MODE=license`, `CLOUDSAVER_DIRECTORY_MODE=registry`, `CLOUDSAVER_LICENSE_ISSUER`, `CLOUDSAVER_LICENSE_AUDIENCE`, `CLOUDSAVER_LICENSE_PUBLIC_KEYS` (JSON mapping trusted key IDs to PEM public keys).
- Local early revocation: `CLOUDSAVER_LICENSE_DENIED_IDS` (JSON array of license UUIDs).

For a managed deployment, independently provision and protect the issuer's private key, distribute public trust through your deployment configuration, and use the same explicit issuer and audience at both ends. Public keys are not secrets. The private key is a file under the owner-only state directory, referenced from `.env`; it must never be baked into an image or committed. Back it up securely. Keep former public keys only while intentionally accepting their unexpired tokens; removing a key rejects every token it signed.

The underlying operator-authenticated route is `POST /admin/v1/workspaces/{tenant_id}/license-tokens`. The portal proxy exposes it as `POST /api/portal/workspaces/{tenant_id}/license-tokens` and applies its existing authenticated-session, operator-role, origin and no-store controls. Request fields are `name`, `roles`, `all_providers`, `allowed_providers`, optional `scope_restrictions`, and required `expires_at`. Roles/scopes are validated against the platform workspace. Clients cannot submit their own plan. Unknown fields are rejected.

Issuance checks the current customer/workspace status, existing billing issuance policy and current plan, then signs and records an audit event in one transaction. The bearer token is shown once and is not persisted in the platform database or audit event. The audit records its unique license ID, expiry, scopes and signing-key ID. This is independent of the existing opaque workspace-key list and its revoke/rotate controls. Copy the issued token into the CloudSaver dashboard's access-token field, or send it as `Authorization: Bearer <token>` to the API. Tokens are capped to 12,000 characters for common HTTP-header limits; oversized grants must be narrowed.

## Expiry, changes and revocation

Every token requires expiry (at most the existing platform 365-day issuance limit). A paid billing-period boundary, or grace boundary when applicable, caps that expiry. Choose short practical lifetimes: offline validation deliberately has no live billing or directory check. JWT issue/not-before/expiry times use the receiver's current clock with no expiry grace; keep host clocks synchronized.

Platform suspension, subscription changes, role changes, key revocation and new cloud accounts **do not rewrite or invalidate an issued offline token**. The existing opaque-key revoke buttons do not revoke it. Previously configured scopes are frozen in the token; newly added scopes/providers need a replacement token. Removal of scopes or disabling a workspace in CloudSaver's own registry takes effect locally.

To invalidate a particular token before expiry, add its audit-visible license UUID to the local `CLOUDSAVER_LICENSE_DENIED_IDS` configuration and recreate the CloudSaver API/worker replicas. No platform request is made. Removing its public signing key revokes all tokens signed by that key. These are deployment/configuration actions, not instant push revocation from the portal. If you need immediate central revocation without deploying local revocation data, use the existing online authentication modes instead.

A bearer license is an automation/credential identity, not proof that a named human approved an action. It does not satisfy independent-human approval requirements. Generation does not deploy Terraform, expand native cloud IAM or import resources. If an issuance response is lost, check audit history; a token cannot be retrieved from storage and repeated issuance creates a different token.

## Background collection

Workers use separately installed grants, not a browser token. In offline mode configure `CLOUDSAVER_BACKGROUND_LICENSES` as a JSON mapping of tenant UUID to an explicitly authorized issued token. Existing billing/observability/scan authorization checkpoints verify that token locally, including its expiry and narrowed scopes. Without an installed background license these checkpoints fail closed. Rotate these bearer credentials as private runtime configuration; do not put them in source or container layers. API access can work without enabling scheduled collection.

## Local acceptance boundary

Tests use the real RSA signer, the existing platform memory store/authorization rules, the core validator and its FastAPI dependency. They prove signature/expiry/issuer/audience/schema checks, scope freezing, local denylisting and successful validation with platform/network access disabled. They do not establish a deployed customer integration, live-cloud acceptance, public-hosting support or an end-to-end browser test. Existing production deployments require a reviewed key-distribution and authentication-mode rollout.

Validation on 2026-10-29: 18 offline-issuance/verification tests passed; 66 core auth, entitlement, identity-client, non-human approval and startup regression tests passed; both frontend TypeScript checks and 13 portal unit tests passed. The existing platform identity suite also passed alongside the license tests (53 tests before the final readiness case was added). The workspace disk limit prevented rebuilding/deploying this increment or running its browser workflow; these results establish local contracts, not a deployed customer rollout.
