"""Configure local Azure scopes and verify gateway APIs (operator key + optional workspace key)."""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
TID = '2b916926-51b6-4a95-8003-bd3525f83077'
SUB = '93ca908b-5732-440d-b712-f6d7951951c0'


def load_env(path):
    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
            continue
        key, _, raw = line.partition('=')
        values[key.strip()] = raw.strip().strip("'").strip('"')
    return values


def operator_headers(key):
    return {'Authorization': 'Bearer ' + key}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace-id', default=TID)
    parser.add_argument('--subscription-id', default=SUB)
    parser.add_argument('--workspace-key', default=os.getenv('CLOUDSAVER_WORKSPACE_KEY', ''))
    parser.add_argument('--skip-scopes', action='store_true')
    parser.add_argument('--identity-url', default='http://identity-service:8005')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--gateway-url', default='http://127.0.0.1:8000')
    parser.add_argument('--operator-stdin', action='store_true',
                        help='Read PLATFORM_OPERATOR_ACCESS_KEY from stdin instead of .env')
    args = parser.parse_args()
    env_path = args.env_file
    env = load_env(env_path) if env_path.exists() else {}
    operator = (sys.stdin.readline().strip() if args.operator_stdin else None) or env.get('PLATFORM_OPERATOR_ACCESS_KEY') or os.getenv('PLATFORM_OPERATOR_ACCESS_KEY')
    if not operator:
        raise SystemExit('PLATFORM_OPERATOR_ACCESS_KEY missing from .env')

    identity_base = env.get('CLOUDSAVER_IDENTITY_URL', args.identity_url).rstrip('/')
    if 'identity-service' in identity_base:
        identity_base = args.identity_url.rstrip('/')

    gateway = args.gateway_url.rstrip('/')
    tid, sub = args.workspace_id, args.subscription_id
    errors = []

    with httpx.Client(timeout=60, trust_env=False) as client:
        if not args.skip_scopes:
            ws = client.get(f'{identity_base}/admin/v1/workspaces/{tid}', headers=operator_headers(operator))
            if ws.status_code == 404:
                errors.append(f'workspace {tid} not found in platform')
            else:
                ws.raise_for_status()
                body = ws.json()
                version = body['version']
                scopes = client.put(
                    f'{identity_base}/admin/v1/workspaces/{tid}/scopes/azure',
                    headers=operator_headers(operator),
                    json={'version': version, 'items': [sub]},
                )
                if scopes.status_code >= 400:
                    errors.append(f'scope update failed: {scopes.status_code} {scopes.text[:200]}')
                else:
                    print(f'Azure scope {sub} set on workspace {tid}')

        key = args.workspace_key
        if not key:
            issue = client.post(
                f'{identity_base}/admin/v1/workspaces/{tid}/keys',
                headers=operator_headers(operator),
                json={
                    'name': 'local-verify',
                    'roles': ['TenantAdmin', 'BillingAdmin', 'Viewer'],
                    'allowed_providers': ['azure', 'aws', 'gcp', 'kubernetes'],
                    'scope_restrictions': {'azure': [sub]},
                },
            )
            if issue.status_code >= 400:
                errors.append(f'issue key failed: {issue.status_code} {issue.text[:240]}')
            else:
                key = issue.json()['secret']
                print('Issued temporary workspace key (save in CLOUDSAVER_WORKSPACE_KEY if you reuse it).')

        if key:
            headers = {'Authorization': 'Bearer ' + key}
            for path in ('/api/v1/me', '/api/v1/settings', '/api/v1/settings/cloud-status'):
                response = client.get(gateway + path, headers=headers)
                if response.status_code >= 400:
                    errors.append(f'{path} -> {response.status_code} {response.text[:200]}')
                else:
                    print(f'{path} -> {response.status_code}')
                    if path.endswith('cloud-status'):
                        summary = response.json()
                        print(json.dumps({
                            'subscriptions': summary.get('subscription_ids'),
                            'billing_scopes': summary.get('billing', {}).get('scopes'),
                            'azure_probe': next((p for p in summary.get('access', {}).get('providers', [])
                                                 if p.get('provider') == 'azure'), None),
                        }, indent=2))

            entitlements = client.get(gateway + '/api/v1/billing/entitlements', headers=headers)
            print(f'/api/v1/billing/entitlements -> {entitlements.status_code}')

    if errors:
        print('\nFailures:', file=sys.stderr)
        for item in errors:
            print(' -', item, file=sys.stderr)
        return 1
    print('Local cloud verification passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
