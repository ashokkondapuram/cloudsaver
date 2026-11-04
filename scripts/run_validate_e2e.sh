#!/usr/bin/env bash
# Run full Azure + DB + API + UI BFF validation inside scanner (Azure CLI creds + Postgres).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY_FILE="${AUDIT_KEY_OUT:-$ROOT/.env.audit-workspace-key}"
exec docker compose -f "$ROOT/compose.yaml" --env-file "$ROOT/.env" run --rm --no-deps \
  -v "$ROOT/scripts:/scripts:ro" \
  -v "$KEY_FILE:/audit-key:ro" \
  -e AUDIT_KEY_OUT=/audit-key \
  -e AUDIT_GATEWAY_URL=http://api-gateway:8000 \
  -e AUDIT_UI_ORIGIN="${AUDIT_UI_ORIGIN:-http://web-dashboard:3000}" \
  -e VALIDATE_SAMPLE_TYPES="${VALIDATE_SAMPLE_TYPES:-8}" \
  -e VALIDATE_FINDING_SAMPLE="${VALIDATE_FINDING_SAMPLE:-5}" \
  -e PYTHONPATH=/app \
  scanner-service python /scripts/validate_e2e_azure_db_api.py 2>/dev/null
