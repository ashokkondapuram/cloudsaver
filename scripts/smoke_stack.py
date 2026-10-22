"""Verify the running stack through the gateway and dashboard proxy.

Does not run cloud scans (requires operator credentials and authorized scopes).
Run with --scan-id to verify a prior scan still loads after restart.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

import httpx

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--scan-id', help='Verify a saved scan instead of only checking workspace auth')
args = parser.parse_args()


def workspace_key():
    env_tenants = os.getenv('CLOUDSAVER_TENANTS')
    if env_tenants:
        tenants = json.loads(env_tenants)
        digest = tenants[0].get('api_key_sha256') if tenants else None
        if digest:
            key = os.getenv('CLOUDSAVER_WORKSPACE_KEY')
            if key and hashlib.sha256(key.encode()).hexdigest() == digest:
                return key
    path = Path(__file__).resolve().parents[1] / '.env'
    if not path.exists():
        raise SystemExit('Configure CLOUDSAVER_TENANTS or run scripts/setup_compose.py first')
    lines = path.read_text().splitlines()
    tenants_line = next((line for line in lines if line.startswith('CLOUDSAVER_TENANTS=')), None)
    if not tenants_line:
        raise SystemExit('CLOUDSAVER_TENANTS missing from .env')
    tenants = json.loads(tenants_line.partition('=')[2])
    digest = tenants[0]['api_key_sha256']
    key = os.getenv('CLOUDSAVER_WORKSPACE_KEY')
    if not key:
        raise SystemExit(
            'Set CLOUDSAVER_WORKSPACE_KEY to the workspace access key printed by setup_compose.py '
            '(the key is not stored in .env for security).'
        )
    if hashlib.sha256(key.encode()).hexdigest() != digest:
        raise SystemExit('CLOUDSAVER_WORKSPACE_KEY does not match CLOUDSAVER_TENANTS')
    return key


gateway = os.getenv('CLOUDSAVER_GATEWAY_URL', 'http://127.0.0.1:8000').rstrip('/')
dashboard = os.getenv('CLOUDSAVER_DASHBOARD_URL', 'http://127.0.0.1:3000').rstrip('/')
key = workspace_key()
with httpx.Client(timeout=60, trust_env=False) as client:
    assert client.get(gateway + '/healthz').status_code == 200
    assert client.get(gateway + '/api/v1/me').status_code == 401
    headers = {'Authorization': 'Bearer ' + key}
    me = client.get(gateway + '/api/v1/me', headers=headers)
    me.raise_for_status()
    body = me.json()
    assert body['mode'] == 'azure', 'Workspace must run in azure mode'
    assert 'scheduled_scans_enabled' in body and 'notification_webhook_configured' in body
    entitlements = client.get(gateway + '/api/v1/billing/entitlements', headers=headers)
    entitlements.raise_for_status()
    if args.scan_id:
        response = client.get(gateway + '/api/v1/scans/' + args.scan_id, headers=headers)
        response.raise_for_status()
        scan_id = args.scan_id
    else:
        history = client.get(gateway + '/api/v1/scans', headers=headers).json()
        scan_id = history[0]['scan_id'] if isinstance(history, list) and history else None
    if scan_id:
        assert client.get(gateway + '/api/v1/scans/' + scan_id, headers=headers).json()['scan_id'] == scan_id
        analytics = client.get(gateway + '/api/v1/analytics', headers=headers)
        analytics.raise_for_status()
    page = client.get(dashboard)
    assert page.status_code == 200 and 'CloudSaver' in page.text
    assert client.get(dashboard + '/api/v1/me', headers=headers).json()['tenant_id'] == body['tenant_id']
    targets = client.get(dashboard + '/api/v1/gitops/targets',headers=headers)
    targets.raise_for_status()
    assert isinstance(targets.json()['targets'],list)
    history = client.get(dashboard + '/api/v1/gitops/requests',headers=headers)
    history.raise_for_status()
    assert isinstance(history.json(),list)
    reliability = client.get(dashboard + '/api/v1/operations/reliability',headers=headers)
    reliability.raise_for_status()
    assert reliability.json()['available'] is True
    deliveries = client.get(dashboard + '/api/v1/operations/deliveries',headers=headers)
    deliveries.raise_for_status()
    assert isinstance(deliveries.json()['items'],list)
    invalid = client.post(dashboard + '/api/v1/policies/terraform/evaluate',headers=headers,
                          json={'plan':{'format_version':'unsupported','variables':{'secret':'do-not-echo'}}})
    assert invalid.status_code == 422 and 'do-not-echo' not in invalid.text
    assert client.get(dashboard + '/api/v1/unlisted', headers=headers).status_code == 404
print('Stack smoke passed' + (f'; scan_id={scan_id}' if scan_id else ' (no saved scans)'))
