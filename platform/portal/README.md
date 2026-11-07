# Portal session storage

Compose uses a dedicated `portal-session-redis` service for encrypted sessions
and one-use OAuth state. It is separate from the ephemeral identity throttling
cache. AOF persistence is enabled, a named data volume is retained, and
`noeviction` prevents silently evicting sessions to make space. Capacity must be
monitored: memory exhaustion rejects new writes and readiness degrades rather
than silently accepting a session that was not stored.

All portal replicas and hosts must use the same `PORTAL_SESSION_REDIS_URL` and
portal service-token secret. A `rediss://` URL supports an approved external TLS
Redis endpoint; do not expose the bundled unencrypted Redis service publicly.
The service has no published host port. Encrypt backups and restrict network and
volume access according to deployment policy. With `appendfsync everysec`, a
server/storage failure may lose recent writes; no zero-loss or recovery target
is promised. Restore testing remains required.

AES-256-GCM binds each payload to its opaque session ID. The encryption key is
derived with a domain separator from the configured portal service token.
Rotating that token invalidates older sessions and requires sign-in. Cookies
contain only opaque IDs. Server-side credentials and OAuth verifier/nonce data
are encrypted before storage; never commit stores, WAL/AOF files, or credentials.

Absolute expiry is eight hours and idle expiry is thirty minutes. Redis server
time governs expiry, idle renewal and refresh leases, avoiding client-clock
renewal of an expired session. OAuth state is consumed atomically once. Refresh
uses a thirty-second lease and monotonically increasing fence; concurrent
requests return temporary unavailability without deleting a valid session. A
lost fence cannot commit refreshed credentials. Uncertain provider refresh may
require sign-in again. Business authorization remains in the identity service.

The Redis adapter reconnects with bounded backoff, disables offline command
queuing, and bounds connection/command waits. Configured Redis failures never
fall back to another store or silently create a different session universe.
Readiness checks the configured session store as well as identity-service.

Without `PORTAL_SESSION_REDIS_URL`, the SQLite adapter at `PORTAL_SESSION_DB`
(default `/tmp/cloudsaver-portal/sessions.sqlite`) remains available for local
use. SQLite supports only one host with a local volume, not multi-host/NFS WAL.
Changing adapters requires sign-in again; no session migration is implied.

Verification: `npm run typecheck`, `npm test`, and `npm run build` on Node
24.22.1. Set `REDIS_SESSION_TEST_URL` to a dedicated test Redis to run acceptance
checks; without it those real-Redis cases are skipped. CI supplies an ephemeral
Redis service. Tests use UUID session IDs and short TTLs, never flush a database,
and remove only their own keys. Do not use production Redis for routine CI.
