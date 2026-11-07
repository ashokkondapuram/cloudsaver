"""Audit dashboard API paths with credentials from the repo .env (never prints secrets)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ENV = Path(os.getenv('AUDIT_ENV_FILE', str(ROOT / '.env')))
GATEWAY = os.getenv('AUDIT_GATEWAY_URL', 'http://127.0.0.1:8000').rstrip('/')
IDENTITY = os.getenv('AUDIT_IDENTITY_URL', 'http://127.0.0.1:8005').rstrip('/')
WORKSPACE = os.getenv('AUDIT_WORKSPACE_ID', '2b916926-51b6-4a95-8003-bd3525f83077')
SUB = os.getenv('AUDIT_SUBSCRIPTION_ID', '93ca908b-5732-440d-b712-f6d7951951c0')
# For a fast local pass, set on scanner-service (see CLOUDSAVER_AZURE_INVENTORY_LIMIT in .env).
SCAN_WAIT_POLLS = int(os.getenv('AUDIT_SCAN_WAIT_POLLS', '120'))


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
            continue
        key, _, raw = line.partition('=')
        values[key.strip()] = raw.strip().strip("'").strip('"')
    return values


def admin_headers(operator: str, portal_token: str) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {operator}',
        'X-Service-Token': portal_token,
        'Accept': 'application/json',
    }


def issue_workspace_key(client: httpx.Client, operator: str, portal_token: str) -> str:
    existing = os.getenv('CLOUDSAVER_WORKSPACE_KEY', '').strip()
    key_out = Path(os.getenv('AUDIT_KEY_OUT', str(ROOT / '.env.audit-workspace-key')))
    if not existing and key_out.exists():
        existing = key_out.read_text().strip()
    if existing:
        return existing
    headers = admin_headers(operator, portal_token)
    expires = (datetime.now(timezone.utc) + timedelta(days=90)).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    response = client.post(
        f'{IDENTITY}/admin/v1/workspaces/{WORKSPACE}/keys',
        headers=headers,
        json={
            'name': 'api-audit',
            'roles': ['TenantAdmin', 'BillingAdmin', 'Viewer'],
            'all_providers': True,
            'allowed_providers': ['azure', 'aws', 'gcp', 'kubernetes'],
            'scope_restrictions': {'azure': [SUB]},
            'expires_at': expires,
        },
    )
    if response.status_code >= 400:
        raise RuntimeError(f'issue key failed: {response.status_code} {response.text[:240]}')
    return response.json()['secret']


def check(name: str, response: httpx.Response, *, expect_json=True) -> dict:
    ok = response.status_code < 400
    detail = {'name': name, 'status': response.status_code, 'ok': ok}
    if not ok:
        detail['error'] = response.text[:300]
        return detail
    if expect_json and response.headers.get('content-type', '').startswith('application/json'):
        try:
            body = response.json()
        except ValueError:
            detail['ok'] = False
            detail['error'] = 'invalid json'
            return detail
        if isinstance(body, list):
            detail['count'] = len(body)
        elif isinstance(body, dict):
            for key in ('total', 'scan_id', 'items', 'tenant_id', 'findings'):
                if key in body:
                    detail[key] = body[key] if key != 'items' else len(body.get('items') or [])
    return detail


def resolve_operator_key(env: dict[str, str]) -> str:
    operator = env.get('PLATFORM_OPERATOR_ACCESS_KEY', '').strip()
    if operator:
        return operator
    platform_env = load_env(ROOT / 'platform' / '.env')
    operator = platform_env.get('PLATFORM_OPERATOR_ACCESS_KEY', '').strip()
    if operator:
        return operator
    key_file = ROOT / 'platform' / 'operator-access.key'
    if key_file.is_file():
        text = key_file.read_text().strip()
        if text:
            return text.splitlines()[0].strip()
    return ''


def main() -> int:
    env = load_env(ENV)
    operator = resolve_operator_key(env)
    platform_env = load_env(ROOT / 'platform' / '.env')
    portal_token = (env.get('PLATFORM_PORTAL_TOKEN') or platform_env.get('PLATFORM_PORTAL_TOKEN', '')).strip()
    if not operator or not portal_token:
        print('Missing operator key (platform/operator-access.key or PLATFORM_OPERATOR_ACCESS_KEY) or PLATFORM_PORTAL_TOKEN', file=sys.stderr)
        return 2
    results: list[dict] = []
    with httpx.Client(timeout=120, trust_env=False) as client:
        try:
            key = issue_workspace_key(client, operator, portal_token)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        headers = {'Authorization': f'Bearer {key}'}
        # Session bootstrap (dashboard connect)
        for path in ('/api/v1/me', '/api/v1/scans', '/api/v1/billing/entitlements'):
            results.append(check(path, client.get(GATEWAY + path, headers=headers)))
        scans = client.get(GATEWAY + '/api/v1/scans', headers=headers).json()
        scan_id = scans[0]['scan_id'] if isinstance(scans, list) and scans else None
        if not scan_id:
            print('No scans found; starting Azure scan (may take several minutes)...', file=sys.stderr)
            started = client.post(
                GATEWAY + '/api/v1/scans/multi-cloud',
                headers=headers,
                json={'providers': ['azure']},
                timeout=600,
            )
            if started.status_code >= 400:
                results.append({'name': 'POST /api/v1/scans/multi-cloud', 'status': started.status_code, 'ok': False, 'error': started.text[:300]})
            else:
                body = started.json()
                scan_id = body.get('scan_id')
                results.append(check('POST /api/v1/scans/multi-cloud', started))
                if body.get('status') == 'running':
                    for _ in range(SCAN_WAIT_POLLS):
                        import time
                        time.sleep(5)
                        history = client.get(GATEWAY + '/api/v1/scans', headers=headers).json()
                        running = next((s for s in history if s.get('scan_id') == scan_id and s.get('status') == 'completed'), None)
                        if running:
                            break
                        active = next((s for s in history if s.get('scan_id') == scan_id), None)
                        if active and active.get('status') == 'failed':
                            results.append({'name': 'scan completion', 'ok': False, 'error': 'scan failed'})
                            scan_id = None
                            break
                    else:
                        results.append({'name': 'scan completion', 'ok': False, 'error': 'scan timed out waiting'})
                        scan_id = None
        if not scan_id:
            if not any(r.get('name') == 'scan selection' for r in results):
                results.append({'name': 'scan selection', 'ok': False, 'error': 'no scans'})
        else:
            paths = [
                f'/api/v1/scans/{scan_id}',
                f'/api/v1/scans/{scan_id}/resources?limit=100&offset=0&cost_scope=all',
                f'/api/v1/scans/{scan_id}/analysis',
                '/api/v1/settings',
                '/api/v1/settings/cloud-status',
                '/api/v1/resources/billable-catalog',
                '/api/v1/ai-batches?limit=5',
            ]
            for path in paths:
                results.append(check(path, client.get(GATEWAY + path, headers=headers)))
            resources = client.get(
                f'{GATEWAY}/api/v1/scans/{scan_id}/resources?limit=5&offset=0&cost_scope=all',
                headers=headers,
            ).json()
            items = resources.get('items') or []
            if items:
                rk = items[0]['resource_key']
                results.append(check(
                    f'/api/v1/scans/{scan_id}/resources/{rk}',
                    client.get(f'{GATEWAY}/api/v1/scans/{scan_id}/resources/{rk}', headers=headers),
                ))
                results.append(check(
                    f'/api/v1/resources/{rk}/history',
                    client.get(f'{GATEWAY}/api/v1/resources/{rk}/history', headers=headers),
                ))
        key_path = Path(os.getenv('AUDIT_KEY_OUT', str(ROOT / '.env.audit-workspace-key')))
        key_path.write_text(key)
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
    failed = [r for r in results if not r.get('ok')]
    print(json.dumps({'passed': len(results) - len(failed), 'failed': len(failed), 'results': results}, indent=2))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
