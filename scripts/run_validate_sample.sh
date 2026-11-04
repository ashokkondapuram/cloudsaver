#!/usr/bin/env bash
# Sample validation: 2 resources × up to 6 types, Azure + DB + gateway + UI BFF (~2 min).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY_FILE="${AUDIT_KEY_OUT:-$ROOT/.env.audit-workspace-key}"
export VALIDATE_SAMPLE_TYPES="${VALIDATE_SAMPLE_TYPES:-6}"
export VALIDATE_PER_TYPE="${VALIDATE_PER_TYPE:-2}"
export VALIDATE_FINDING_SAMPLE="${VALIDATE_FINDING_SAMPLE:-3}"
export VALIDATE_LIST_LIMIT="${VALIDATE_LIST_LIMIT:-80}"
export VALIDATE_UI_BFF="${VALIDATE_UI_BFF:-true}"
exec docker compose -f "$ROOT/compose.yaml" --env-file "$ROOT/.env" run --rm --no-deps \
  -v "$ROOT/scripts:/scripts:ro" \
  -v "$KEY_FILE:/audit-key:ro" \
  -e AUDIT_KEY_OUT=/audit-key \
  -e AUDIT_GATEWAY_URL=http://api-gateway:8000 \
  -e AUDIT_UI_ORIGIN=http://web-dashboard:3000 \
  -e VALIDATE_SAMPLE_TYPES \
  -e VALIDATE_PER_TYPE \
  -e VALIDATE_FINDING_SAMPLE \
  -e VALIDATE_LIST_LIMIT \
  -e VALIDATE_UI_BFF \
  -e PYTHONPATH=/app \
  scanner-service python /scripts/validate_e2e_azure_db_api.py 2>/dev/null
