# Platform operator login secret on Kubernetes

For **non-production** clusters (for example AKS dev/staging), you can store the portal operator access key as a **plaintext file** in a Kubernetes Secret and mount it into **platform-portal** and **identity-service**. The apps derive `PLATFORM_OPERATOR_KEY_SHA256` at runtime; you do not need a separate digest in the Secret.

Production clusters should use **`PLATFORM_PORTAL_AUTH=entra`**. The `operator_key` fallback is refused when `PLATFORM_ENVIRONMENT=production`.

## Create the Secret

Generate a key locally (or reuse `platform/operator-access.key` from `setup_platform.py`):

```bash
openssl rand -base64 32 > operator-access.key
chmod 600 operator-access.key
```

Apply (namespace `platform` is an example):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: platform-operator-access
  namespace: platform
type: Opaque
stringData:
  operator-access.key: |
    # replace with one line: URL-safe operator token
```

Or from the shell (never commit the key):

```bash
kubectl -n platform create secret generic platform-operator-access \
  --from-file=operator-access.key=./operator-access.key \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Mount into platform-portal and identity-service

In **cloudsaver-helm** (`charts/cloudsaver-platform`), mount the same file on both workloads and set the file path env var (digest env can be omitted).

```yaml
# values fragment (non-prod)
config:
  PLATFORM_ENVIRONMENT: development
  PLATFORM_PORTAL_AUTH: operator_key

components:
  platform-portal:
    extraEnv:
      PLATFORM_OPERATOR_ACCESS_KEY_FILE: /run/platform-secrets/operator-access.key
    volumeMounts:
      - name: operator-access
        mountPath: /run/platform-secrets
        readOnly: true
  identity-service:
    extraEnv:
      PLATFORM_OPERATOR_ACCESS_KEY_FILE: /run/platform-secrets/operator-access.key
    volumeMounts:
      - name: operator-access
        mountPath: /run/platform-secrets
        readOnly: true

extraVolumes:
  - name: operator-access
    secret:
      secretName: platform-operator-access
      defaultMode: 0400
```

Helm chart layout may use different keys (`secretVolumes`, `identitySecret`, etc.). Map the same Secret and env var on **both** portal and identity pods.

## Alternatives

| Approach | When to use |
| --- | --- |
| **File mount** (`PLATFORM_OPERATOR_ACCESS_KEY_FILE`) | Kubernetes; plaintext only in Secret data |
| **Digest env** (`PLATFORM_OPERATOR_KEY_SHA256`) | Compose, ACA, or legacy Helm values with no file mount |
| **Plaintext env** (`PLATFORM_OPERATOR_ACCESS_KEY`) | Local `platform/.env` only; avoid in cluster env vars |

## Operators retrieving the key

Admins with `kubectl` access:

```bash
kubectl -n platform get secret platform-operator-access \
  -o jsonpath='{.data.operator-access\.key}' | base64 -d; echo
```

Prefer RBAC, external secrets (Azure Key Vault, ESO), and rotation over checking in plaintext keys to Git.

## Related

- [DEPLOYMENT_ENVIRONMENT.md](../DEPLOYMENT_ENVIRONMENT.md) — Helm secret key catalog  
- [ENVIRONMENT.md](../ENVIRONMENT.md) — local `operator-access.key` and `setup_platform.py`
