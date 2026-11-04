#!/usr/bin/env bash
# Point host and container Azure CLI at the subscription CloudSaver scans/bills in local dev.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT}/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing .env; run ./start.sh or scripts/setup_compose.py first." >&2
  exit 1
fi
# shellcheck disable=SC1091
while IFS= read -r line; do
  [[ "$line" =~ ^CLOUDSAVER_(BILLING_CONNECTORS|AZURE_CONFIG_DIR|CLOUD_IDENTITY)= ]] || continue
  name="${line%%=*}"
  value="${line#*=}"
  value="${value#\'}"; value="${value%\'}"
  value="${value#\"}"; value="${value%\"}"
  export "$name=$value"
done < "$ENV_FILE"
if [[ "${CLOUDSAVER_CLOUD_IDENTITY:-}" != developer ]]; then
  echo "Set CLOUDSAVER_CLOUD_IDENTITY=developer in .env for local Azure CLI credentials." >&2
  exit 1
fi
SUB="$(python3 - <<'PY'
import json, os, re
raw = os.environ.get("CLOUDSAVER_BILLING_CONNECTORS", "[]")
try:
    rows = json.loads(raw)
except json.JSONDecodeError:
    rows = []
for row in rows:
    if isinstance(row, dict) and row.get("provider") == "azure" and row.get("scope_id"):
        print(row["scope_id"])
        break
PY
)"
if [[ -z "${SUB:-}" ]]; then
  echo "No azure scope_id in CLOUDSAVER_BILLING_CONNECTORS; add your subscription UUID." >&2
  exit 1
fi
if ! command -v az >/dev/null; then
  echo "Install Azure CLI on the host and run: az login" >&2
  exit 1
fi
az account set --subscription "$SUB"
echo "Host default subscription: $(az account show --query name -o tsv) ($SUB)"
if docker compose -f "$ROOT/compose.yaml" ps scanner-service --status running -q 2>/dev/null | grep -q .; then
  docker compose -f "$ROOT/compose.yaml" exec -T scanner-service az account set --subscription "$SUB"
  docker compose -f "$ROOT/compose.yaml" exec -T scanner-service az account show --query "{name:name,subscription:id,tenantId:tenantId}" -o json
  echo "Scanner container uses the same ~/.azure mount as the host."
else
  echo "Start the stack (make up) so scanner and billing-sync-worker mount ${CLOUDSAVER_AZURE_CONFIG_DIR:-~/.azure}."
fi
for svc in scanner-service billing-sync-worker; do
  if docker compose -f "$ROOT/compose.yaml" ps "$svc" --status running -q 2>/dev/null | grep -q .; then
    docker compose -f "$ROOT/compose.yaml" exec -T "$svc" az account set --subscription "$SUB" 2>/dev/null || true
  fi
done
