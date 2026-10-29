# Keycloak deployment

This is a single-node HTTPS deployment with a dedicated PostgreSQL database and persistent volume. It is a development/pilot starting point, not a highly available production installation. Keycloak and PostgreSQL have readiness probes; native Keycloak liveness is `/health/live` on internal management port 9000. Only HTTPS port 8443 is published, on loopback by default. Do not expose the management port or database.

## Prepare and start

Provide a real certificate/key pair, an existing CloudSaver workspace UUID, and a future-dated license JSON matching `docs/KEYCLOAK_AND_COLLECTION.md`. The generated private directory must be outside the repository. Certificate files must be readable by Keycloak's container UID; protect their parent directory on the host. For a local trial, a self-signed certificate must include the chosen hostname in its SAN and be explicitly trusted by the browser and application; never disable TLS verification.

```sh
python -m scripts.setup_keycloak \
  --directory /secure/cloudsaver-keycloak \
  --public-url https://identity.example.com:8443 \
  --tenant-id 11111111-1111-4111-8111-111111111111 \
  --license-file /secure/license.json \
  --tls-cert /secure/tls/cert.pem --tls-key /secure/tls/key.pem

docker compose --env-file /secure/cloudsaver-keycloak/keycloak.env \
  -f deploy/keycloak/compose.yaml up -d
```

Generated `keycloak.env` contains the bootstrap administrator and database passwords. Generated `cloudsaver.env` contains the confidential verifier secret and exact binding. Both files have mode 0600 and their parent has mode 0700. Realm imports also contain a verifier secret: keep the complete directory private, backed up and out of Git. Startup import creates a new realm only; changing the file does not update an existing realm. Later changes require an authenticated, reviewed Admin API operation or admin-console change.

Create a permanent named administrator in the master realm, test it, then remove the temporary bootstrap administrator. Enforce MFA and reviewed administrator permissions before any public/customer use. In the tenant realm create human users, add them to `licensed-workspace`, and explicitly assign an appropriate `cloudsaver-api` client role. CloudSaver's verifier service has read roles, not `realm-admin`. Verify these permissions against the deployed version before delegated administration.

## Connect CloudSaver

The issuer hostname must resolve to this same HTTPS service from both browsers and application containers. For same-host Docker, attach Keycloak to the application's external network with that hostname as a network alias; preserve its private database network. For a remote hostname, use normal DNS and a valid certificate. The default loopback port is not reachable from another machine.

Create a combined CA bundle containing the normal public roots and any private CA. Load generated `cloudsaver.env` after the existing CloudSaver environment file, and layer `cloudsaver.override.yaml` over its Compose file, setting `KEYCLOAK_CA_BUNDLE` to the bundle's absolute path. The override deliberately selects Keycloak authentication; existing workspace keys cease authenticating those services. Retain your original deployment configuration for recovery. Test discovery, login, enabled state, current membership/roles/license, revocation and gateway `/api/v1/me` before customer cutover.

The generated `cloudsaver-console` client supports authorization code with S256 PKCE and only the local `http://127.0.0.1:8765/callback` redirect. Password grants and implicit grants are disabled. The existing dashboard accepts an access token; integrated browser SSO/refresh/logout remains separate work. To obtain a short-lived token for local testing, run this on the same host as your browser:

```sh
python -m scripts.keycloak_login \
  --issuer https://identity.example.com:8443/realms/cloudsaver-WORKSPACE_UUID \
  --ca-bundle /secure/combined-ca.pem --output /secure/access-token.txt
```

The helper prints the authorization URL, accepts one local callback for up to three minutes, exchanges the code with PKCE, and saves only the access token with mode 0600. Tokens expire after five minutes. Keep the output out of source control; do not paste tokens into logs or support tickets.

## License storage and operation

Keycloak 26.4 group attributes have a 255-character value limit. Generated realms store `cloudsaver_license_v1` as a list of `0000:<payload>`, `0001:<payload>` chunks, each at most 245 characters. The consumer validates a contiguous unique sequence before reconstructing the bounded JSON. Attribute order is irrelevant; gaps, duplicates and simultaneous legacy/chunked records fail closed. The older single-value `cloudsaver_license` form remains accepted for compatibility. Restrict editing either attribute to licensing administrators.

Back up the dedicated database and configuration/secrets together. Test restore before relying on it. Rotate verifier credentials through Keycloak and update all application replicas together; environment changes require container recreation. Database password rotation requires updating PostgreSQL itself, not only its environment file. Certificate renewal requires updated files and a tested reload/restart. Select and test a supported patched Keycloak release before public production deployment; the image here is pinned for reproducible local acceptance.

## Local validation on 2026-10-29

A local instance was started at `https://keycloak.localhost:8443`, with a 30-day local trial license for the existing development workspace. Generated deployment files are under `/workspace/.keycloak-local/config/`; TLS files are under `/workspace/.keycloak-local/tls/`. These are local runtime artifacts, not source or production credentials. Use `keycloak.env` for bootstrap-admin credentials and `user-credentials.json` for the local `cloudsaver-admin` login. The hostname/port is local to the execution host; no public DNS or public hosting was provisioned.

Local acceptance passed: HTTPS discovery returned 200 with certificate verification enabled; Keycloak and its database became healthy; CloudSaver gateway readiness returned 200; a real issued token passed signature, introspection, user/group membership, client-role and license checks through gateway `/api/v1/me`; logging out that user's sessions immediately changed the gateway response to 401. Password grants used during this smoke check were disabled afterward. The focused local test suite passed 32 tests. Browser SSO embedded in the dashboard and a public production hostname were not part of this acceptance.
