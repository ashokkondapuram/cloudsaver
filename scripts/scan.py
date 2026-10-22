"""Trigger an authenticated scan on the local gateway without printing credentials."""
import os
from pathlib import Path

import httpx

key = os.getenv('DEMO_ACCESS_KEY')
if not key:
    path = Path(__file__).resolve().parents[1] / '.env'
    if path.exists():
        key = next((line.partition('=')[2].strip() for line in path.read_text().splitlines()
                    if line.startswith('DEMO_ACCESS_KEY=')), None)
if not key:
    raise SystemExit('Set DEMO_ACCESS_KEY or run scripts/setup_compose.py first')
try:
    response = httpx.post(os.getenv('CLOUDSAVER_GATEWAY_URL', 'http://127.0.0.1:8000') + '/api/v1/scans',
                          headers={'Authorization': 'Bearer ' + key}, timeout=300)
    response.raise_for_status()
    result = response.json()
except (httpx.HTTPError, ValueError):
    raise SystemExit('Scan request failed; check gateway health, access key and server logs') from None
print(f"Completed {result['mode']} scan {result['scan_id']}: {result['total_items_found']} findings")
