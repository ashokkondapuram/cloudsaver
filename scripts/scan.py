"""Trigger an authenticated scan on the local gateway without printing credentials."""
import hashlib
import json
import os
from pathlib import Path

import httpx


def workspace_key():
    key = os.getenv('CLOUDSAVER_WORKSPACE_KEY')
    if key:
        return key
    raise SystemExit('Set CLOUDSAVER_WORKSPACE_KEY to your operator-issued workspace access key')


def tenant_digest():
    raw = os.getenv('CLOUDSAVER_TENANTS')
    if not raw:
        path = Path(__file__).resolve().parents[1] / '.env'
        if path.exists():
            raw = next((line.partition('=')[2] for line in path.read_text().splitlines()
                        if line.startswith('CLOUDSAVER_TENANTS=')), None)
    if not raw:
        raise SystemExit('Configure CLOUDSAVER_TENANTS or run scripts/setup_compose.py')
    tenants = json.loads(raw)
    return tenants[0]['api_key_sha256'] if tenants else None


digest = tenant_digest()
key = workspace_key()
if digest and hashlib.sha256(key.encode()).hexdigest() != digest:
    raise SystemExit('CLOUDSAVER_WORKSPACE_KEY does not match CLOUDSAVER_TENANTS')
try:
    response = httpx.post(os.getenv('CLOUDSAVER_GATEWAY_URL', 'http://127.0.0.1:8000') + '/api/v1/scans',
                          headers={'Authorization': 'Bearer ' + key}, timeout=300)
    response.raise_for_status()
    result = response.json()
except (httpx.HTTPError, ValueError):
    raise SystemExit('Scan request failed; check gateway health, access key, cloud credentials and server logs') from None
print(f"Completed {result['mode']} scan {result['scan_id']}: {result['total_items_found']} findings")
