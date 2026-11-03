"""Ensure platform identity has workspaces matching CLOUDSAVER_TENANTS after an empty DB volume."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _request(method, url, token, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read()
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors='replace')
        try:
            detail = json.loads(body)
        except json.JSONDecodeError:
            detail = body
        return error.code, detail


def ensure_workspace(base_url, token, tenant):
    tenant_id = tenant['tenant_id']
    status, body = _request('GET', f'{base_url}/admin/v1/workspaces/{tenant_id}', token)
    if status == 200:
        workspace = body
    else:
        status, customer = _request(
            'POST',
            f'{base_url}/admin/v1/customers',
            token,
            {'name': tenant.get('name') or 'Local workspace customer'},
        )
        if status not in (200, 201):
            raise RuntimeError(f'Could not create identity customer: {customer}')
        status, workspace = _request(
            'POST',
            f'{base_url}/admin/v1/workspaces',
            token,
            {
                'tenant_id': tenant_id,
                'customer_id': customer['id'],
                'name': tenant.get('name') or 'Local workspace',
                'plan_tier': tenant.get('plan_tier') or 'STARTER',
            },
        )
        if status not in (200, 201):
            raise RuntimeError(f'Could not create identity workspace: {workspace}')
    subscriptions = tenant.get('subscription_ids') or []
    if subscriptions:
        status, updated = _request(
            'PUT',
            f'{base_url}/admin/v1/workspaces/{tenant_id}/scopes/azure',
            token,
            {'version': workspace['version'], 'items': subscriptions},
        )
        if status != 200:
            raise RuntimeError(f'Could not set Azure scopes: {updated}')
    return tenant_id


def resync_directory():
    from app.config import Settings
    from app.directory_projector import DirectoryProjector
    from app.identity_client import IdentityClient

    settings = Settings.load()
    if settings.registry is None:
        return
    client = IdentityClient(subscribe=False)
    try:
        DirectoryProjector(settings.registry, client).resync()
    finally:
        client.close()


def main():
    token = os.environ.get('LOCAL_OPERATOR_KEY', '').strip()
    if not token:
        print('bootstrap_local_identity: no LOCAL_OPERATOR_KEY; skip', file=sys.stderr)
        return 0
    raw = os.environ.get('LOCAL_TENANT_CONFIG', '[]')
    tenants = json.loads(raw)
    if not isinstance(tenants, list) or not tenants:
        print('bootstrap_local_identity: empty LOCAL_TENANT_CONFIG; skip', file=sys.stderr)
        return 0
    base = os.environ.get('CLOUDSAVER_IDENTITY_URL', 'http://identity-service:8005').rstrip('/')
    for tenant in tenants:
        if not isinstance(tenant, dict) or not tenant.get('tenant_id'):
            raise SystemExit('Each CLOUDSAVER_TENANTS entry needs tenant_id')
        ensure_workspace(base, token, tenant)
    resync_directory()
    print(f'bootstrap_local_identity: synced {len(tenants)} workspace(s)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
