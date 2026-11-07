# Portal session persistence

The portal stores encrypted sessions and one-use OAuth state in SQLite at
`PORTAL_SESSION_DB` (Compose: `/app/session-data/sessions.sqlite`). The named
`portal-session-data` volume retains sessions across container replacement.
AES-256-GCM binds each encrypted payload to its opaque session ID; the key is
derived with a domain separator from the configured portal service token.
Rotating that token invalidates previously stored sessions and requires sign-in.
Never commit the database, its WAL files, or real credentials.

This adapter supports one host with a local filesystem volume, including portal
processes sharing that volume. Do not share SQLite WAL over NFS or use independent
volumes for replicas. Multi-host deployments require a distributed adapter and
its own concurrency/recovery acceptance. A temporary default path is available
for local development; production must retain the Compose volume or configure
an equivalent persistent local volume owned by the portal runtime user.

Absolute expiry is eight hours, idle expiry is thirty minutes, and step-up
remains fifteen minutes. OAuth state is consumed atomically once. Token refresh
uses a thirty-second lease and monotonically increasing fence; concurrent refresh
requests return temporary unavailability without deleting the session. A lost
fence or expired session cannot commit refreshed credentials. Long provider
outages may require sign-in again. Business authorization remains enforced by
the identity service rather than the portal's profile cache.

Verification: `npm run typecheck` and `npm test`. Session tests exercise shared
reads, encrypted payloads, expiry, one-use state, revocation, and stale fences.
