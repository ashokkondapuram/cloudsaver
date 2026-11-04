"""Check dashboard page APIs return 200 with populated payloads (workspace key from file)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = Path(os.getenv('AUDIT_KEY_OUT', str(ROOT / '.env.audit-workspace-key')))
GATEWAY = os.getenv('AUDIT_GATEWAY_URL', 'http://127.0.0.1:8000').rstrip('/')


def get(path: str, key: str) -> tuple[int, object | str]:
    req = urllib.request.Request(
        GATEWAY + path,
        headers={'Authorization': f'Bearer {key}', 'Accept': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
            if resp.headers.get('content-type', '').startswith('application/json'):
                return resp.status, json.loads(body)
            return resp.status, body[:200].decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:300].decode('utf-8', 'replace')


def main() -> int:
    if not KEY_FILE.exists():
        print('Missing workspace key file', KEY_FILE, file=sys.stderr)
        return 2
    key = KEY_FILE.read_text().strip()
    scans_status, scans = get('/api/v1/scans?limit=5', key)
    if scans_status >= 400 or not isinstance(scans, list) or not scans:
        print('No scans', file=sys.stderr)
        return 1
    scan_id = scans[0]['scan_id']
    status, resources = get(
        f'/api/v1/scans/{scan_id}/resources?limit=5&offset=0&cost_scope=billable',
        key,
    )
    rk = None
    if isinstance(resources, dict) and resources.get('items'):
        rk = resources['items'][0].get('resource_key')

    checks: list[tuple[str, str]] = [
        ('bootstrap', '/api/v1/me'),
        ('bootstrap', '/api/v1/billing/entitlements'),
        ('overview/resources', f'/api/v1/scans/{scan_id}'),
        ('overview/resources', f'/api/v1/scans/{scan_id}/analysis'),
        ('resources', f'/api/v1/scans/{scan_id}/resources?limit=10&offset=0&cost_scope=billable'),
        ('settings', '/api/v1/settings'),
        ('settings', '/api/v1/settings/cloud-status'),
        ('allocation', '/api/v1/finops/summary'),
        ('outcomes', '/api/v1/outcomes/summary'),
        ('outcomes', '/api/v1/outcomes/cases?limit=10'),
        ('governance', '/api/v1/governance/summary'),
        ('activity', '/api/v1/operations/reliability'),
        ('activity', '/api/v1/operations/deliveries?limit=10'),
        ('kubernetes', f'/api/v1/scans/{scan_id}/kubernetes'),
        ('optimization', '/api/v1/finops/autopilot/playbooks'),
        ('agents', '/api/v1/agents/tasks?limit=10'),
        ('workloads', '/api/v1/engineering/workloads'),
        ('automation', '/api/v1/gitops/targets'),
    ]
    if rk:
        checks.append(('resource drawer', f'/api/v1/scans/{scan_id}/resources/{rk}'))
        checks.append(('resource history', f'/api/v1/resources/{rk}/history'))

    results = []
    for page, path in checks:
        status, body = get(path, key)
        ok = 200 <= status < 400
        detail: dict = {'page': page, 'path': path, 'status': status, 'ok': ok}
        if ok and isinstance(body, dict):
            for k in ('total', 'items', 'scan_id', 'tenant_id', 'findings', 'summary', 'clusters', 'workers'):
                if k in body:
                    v = body[k]
                    detail[k] = len(v) if isinstance(v, list) else v
        elif ok and isinstance(body, list):
            detail['count'] = len(body)
        elif not ok:
            detail['error'] = str(body)[:200]
        results.append(detail)

    failed = [r for r in results if not r['ok']]
    print(json.dumps({'scan_id': scan_id, 'passed': len(results) - len(failed), 'failed': len(failed), 'results': results}, indent=2))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
