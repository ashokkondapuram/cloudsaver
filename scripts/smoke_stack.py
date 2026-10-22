"""Verify the running local demo through the gateway and dashboard proxy.

Creates one demo scan. Never invokes remediation, notifications or live scans.
Run again with --scan-id after restarting services to verify persistence.
"""
import argparse
import os
from pathlib import Path

import httpx

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--scan-id', help='Verify a prior demo scan instead of creating another')
args = parser.parse_args()
key = os.getenv('DEMO_ACCESS_KEY')
if not key:
    path = Path(__file__).resolve().parents[1] / '.env'
    if path.exists():
        key = next((line.partition('=')[2].strip() for line in path.read_text().splitlines()
                    if line.startswith('DEMO_ACCESS_KEY=')), None)
if not key:
    raise SystemExit('Set DEMO_ACCESS_KEY or run scripts/setup_compose.py first')
gateway = os.getenv('CLOUDSAVER_GATEWAY_URL', 'http://127.0.0.1:8000').rstrip('/')
dashboard = os.getenv('CLOUDSAVER_DASHBOARD_URL', 'http://127.0.0.1:3000').rstrip('/')
with httpx.Client(timeout=60, trust_env=False) as client:
    assert client.get(gateway + '/healthz').status_code == 200
    assert client.get(gateway + '/api/v1/me').status_code == 401
    headers = {'Authorization': 'Bearer ' + key}
    me = client.get(gateway + '/api/v1/me', headers=headers)
    me.raise_for_status()
    assert me.json()['mode'] == 'demo', 'Smoke script only creates demo scans'
    if args.scan_id:
        response = client.get(gateway + '/api/v1/scans/' + args.scan_id, headers=headers)
    else:
        response = client.post(gateway + '/api/v1/scans', headers=headers)
        assert response.status_code == 201
    response.raise_for_status()
    scan = response.json()
    assert scan['mode'] == 'demo' and len(scan['findings']) == scan['total_items_found'] == 8
    scan_id = scan['scan_id']
    assert client.get(gateway + '/api/v1/scans/' + scan_id, headers=headers).json() == scan
    assert any(s['scan_id'] == scan_id for s in client.get(gateway + '/api/v1/scans', headers=headers).json())
    analytics = client.get(gateway + '/api/v1/analytics', headers=headers)
    analytics.raise_for_status()
    assert analytics.json()['total_items_found'] == 8
    page = client.get(dashboard)
    assert page.status_code == 200 and 'CloudSaver' in page.text
    assert client.get(dashboard + '/api/v1/me', headers=headers).json() == me.json()
    assert client.get(dashboard + '/api/v1/scans/' + scan_id, headers=headers).json() == scan
    assert client.get(dashboard + '/api/v1/unlisted', headers=headers).status_code == 404
print(f'Demo stack smoke passed; scan_id={scan_id}')
