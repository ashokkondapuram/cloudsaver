#!/usr/bin/env python3
"""Walk CloudSaver HTTP APIs for one workspace (local or deployed).

Usage (from repo root with stack running and .env loaded):
  export CLOUDSAVER_AUDIT_BASE=http://127.0.0.1:8080
  export CLOUDSAVER_AUDIT_KEY=cs_test_...
  python3 scripts/audit_workspace_api.py

Optional: CLOUDSAVER_AUDIT_SCAN_ID=<uuid> to skip creating a scan.
Writes a markdown report to stdout; exit 1 if any required call fails.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

BASE = os.environ.get('CLOUDSAVER_AUDIT_BASE', 'http://127.0.0.1:8080').rstrip('/')
KEY = os.environ.get('CLOUDSAVER_AUDIT_KEY', '')
SCAN_ID = os.environ.get('CLOUDSAVER_AUDIT_SCAN_ID', '')


def call(method: str, path: str, *, body: dict | None = None, required: bool = True) -> tuple[int, Any]:
    url = BASE + path
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': f'Bearer {KEY}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            payload = json.loads(raw) if raw else None
            return resp.status, payload
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors='replace')[:500]
        if required:
            print(f'FAIL {method} {path} -> {error.code} {detail}', file=sys.stderr)
        return error.code, detail
    except Exception as error:
        if required:
            print(f'FAIL {method} {path} -> {error}', file=sys.stderr)
        return 0, str(error)


def main() -> int:
    if not KEY:
        print('Set CLOUDSAVER_AUDIT_KEY to a workspace API key.', file=sys.stderr)
        return 2
    failures = 0
    lines = ['# CloudSaver API audit', f'Base: `{BASE}`', '']

    checks = [
        ('GET', '/health/live', False),
        ('GET', '/health/ready', False),
        ('GET', '/api/v1/me', True),
        ('GET', '/api/v1/settings', True),
        ('GET', '/api/v1/rules/catalog', True),
        ('GET', '/api/v1/rules/effective', True),
        ('GET', '/api/v1/ai/targets', True),
        ('GET', '/api/v1/finops/sync-status', True),
        ('GET', '/api/v1/governance/summary', True),
        ('GET', '/api/v1/outcomes/summary', True),
        ('GET', '/api/v1/engineering/capabilities', True),
    ]
    for method, path, required in checks:
        status, payload = call(method, path, required=required)
        ok = 200 <= status < 300
        if required and not ok:
            failures += 1
        lines.append(f'- {"OK" if ok else "FAIL"} `{method} {path}` → {status}')

    scan_id = SCAN_ID
    if not scan_id:
        status, payload = call('POST', '/api/v1/scans', body={})
        ok = status == 201 and isinstance(payload, dict) and payload.get('scan_id')
        lines.append(f'- {"OK" if ok else "FAIL"} `POST /api/v1/scans` → {status}')
        if not ok:
            failures += 1
            print('\n'.join(lines))
            return 1
        scan_id = payload['scan_id']
    else:
        lines.append(f'- Using scan `{scan_id}`')

    resource_checks = [
        f'/api/v1/scans/{scan_id}/resources?limit=50',
        f'/api/v1/scans/{scan_id}/analysis',
        f'/api/v1/scans/{scan_id}/resources/export',
    ]
    first_key = None
    for path in resource_checks:
        status, payload = call('GET', path)
        ok = status == 200
        if not ok:
            failures += 1
        lines.append(f'- {"OK" if ok else "FAIL"} `GET {path}` → {status}')
        if ok and path.endswith('limit=50') and isinstance(payload, dict):
            items = payload.get('items') or []
            if items:
                first_key = items[0].get('resource_key')

    if first_key:
        detail_path = f'/api/v1/scans/{scan_id}/resources/{first_key}'
        status, payload = call('GET', detail_path)
        ok = status == 200 and isinstance(payload, dict)
        if ok:
            missing = [k for k in ('assessment', 'findings', 'ai_context', 'rule_matches', 'rule_conflicts') if k not in payload]
            if missing:
                ok = False
                lines.append(f'- FAIL detail missing keys: {missing}')
        else:
            failures += 1
        lines.append(f'- {"OK" if ok else "FAIL"} `GET {detail_path}` → {status}')
        ctx = (payload or {}).get('ai_context') if isinstance(payload, dict) else {}
        if isinstance(ctx, dict):
            blob = json.dumps(ctx)
            sensitive = [name for name in ('resource_id', 'resource_name', 'billed_cost_usd') if f'"{name}"' in blob]
            lines.append(f'- AI context sensitive keys present: {sensitive or "none (expected)"}')

    lines.append('')
    lines.append(f'**Failures:** {failures}')
    print('\n'.join(lines))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
