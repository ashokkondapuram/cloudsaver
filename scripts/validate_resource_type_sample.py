"""One sample resource per ARM type: Azure live read vs Postgres scan vs gateway API."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = Path(os.getenv('AUDIT_KEY_OUT', str(ROOT / '.env.audit-workspace-key')))
GATEWAY = os.getenv('AUDIT_GATEWAY_URL', 'http://127.0.0.1:8000').rstrip('/')
MAX_TYPES = int(os.getenv('VALIDATE_MAX_TYPES', '6'))
PER_TYPE = int(os.getenv('VALIDATE_PER_TYPE', '2'))
QUICK = os.getenv('VALIDATE_QUICK', 'true').lower() in ('1', 'true', 'yes')
SKIP_AZURE = os.getenv('VALIDATE_SKIP_AZURE', 'false').lower() in ('1', 'true', 'yes')
ARM_SPOT_CHECKS = int(os.getenv('VALIDATE_ARM_SPOT', '2'))


def http_json(method: str, path: str, key: str | None, body: bytes | None = None) -> tuple[int, Any]:
    headers = {'Accept': 'application/json'}
    if key:
        headers['Authorization'] = f'Bearer {key}'
    req = urllib.request.Request(GATEWAY + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            if resp.headers.get('content-type', '').startswith('application/json'):
                return resp.status, json.loads(raw)
            return resp.status, raw[:200].decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:300].decode('utf-8', 'replace')
    except Exception as exc:  # noqa: BLE001 — audit script; keep orchestrator running
        return 599, f'{type(exc).__name__}: {exc}'[:300]


def pick_samples(items: list[dict]) -> list[dict]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from validation_scan_db import pick_resource_samples

    return pick_resource_samples(items, max_types=MAX_TYPES, max_per_type=PER_TYPE)


def compare_identity(azure: dict, row: dict, label: str) -> list[str]:
    issues: list[str] = []
    if azure.get('name') != row.get('resource_name'):
        issues.append(f'{label}: name mismatch')
    if (azure.get('type') or '').lower() != (row.get('resource_type') or '').lower():
        issues.append(f'{label}: type mismatch')
    if azure.get('resourceGroup') != row.get('resource_group'):
        issues.append(f'{label}: resource group mismatch')
    if (azure.get('id') or '').lower() != (row.get('resource_id') or '').lower():
        issues.append(f'{label}: resource id mismatch')
    return issues


def worker_validate(payload: dict) -> dict:
    """Runs inside scanner-service: Postgres + batched Azure ARG (+ optional ARM spot checks)."""
    from uuid import UUID

    from app.azure_resource_registry import arm_api_version, normalize_arm_body, supports_arm_detail
    from app.cloud_http import JSONReader
    from app.cloud_identity import CredentialError, azure_credential, identity_mode
    from app.collectors.azure_endpoint import arm_url, validate_arm_resource_path
    import os
    from app.scanner import execute_pages
    import psycopg

    scan_id = payload['scan_id']
    tenant_id = payload['tenant_id']
    samples = payload['samples']
    import os
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from validation_scan_db import compare_api_to_db_record, expand_subscription_ids, payload_index

    subs = expand_subscription_ids(
        [str(UUID(s)) for s in (payload.get('subscription_ids') or [])],
        [s['resource_id'] for s in samples if s.get('resource_id')],
    )
    if not subs:
        sub = os.getenv('AUDIT_SUBSCRIPTION_ID', '93ca908b-5732-440d-b712-f6d7951951c0')
        subs = [str(UUID(sub))]
    arm_spots_left = int(payload.get('arm_spot_checks', ARM_SPOT_CHECKS))
    results: list[dict] = []

    def credential():
        workspace = {'tenant_id': payload['tenant_id'], 'identity': payload.get('identity') or {}}
        try:
            return azure_credential(workspace)
        except CredentialError:
            if identity_mode() != 'developer':
                raise
            from azure.identity import AzureCliCredential

            return AzureCliCredential(process_timeout=60)

    with psycopg.connect(os.environ['CLOUDSAVER_DATABASE_URL']) as db:
        db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (str(UUID(tenant_id)),))
        prow = db.execute(
            'SELECT payload FROM public.scans WHERE id=%s AND tenant_id=%s',
            (scan_id, tenant_id),
        ).fetchone()
        if not prow:
            return {'error': 'scan missing in postgres', 'results': []}
        db_index = payload_index(prow[0])
    ids = [s['resource_id'] for s in samples if s.get('resource_id')]

    with credential() as cred:
        az_by_id: dict[str, dict] = {}
        for start in range(0, len(ids), 50):
            chunk = ids[start : start + 50]
            quoted = ','.join("'" + i.replace("'", "''") + "'" for i in chunk)
            query = (
                'Resources | where id in (' + quoted + ') '
                '| project id, name, type, resourceGroup, location, subscriptionId'
            )
            for az in execute_pages(cred, query, subs):
                az_by_id[az['id'].lower()] = az

        from app.cloud_http import BearerTokenCache

        reader = JSONReader(headers_factory=BearerTokenCache(cred, 'https://management.azure.com/.default'))
        for sample in samples:
            rid = (sample.get('resource_id') or '').lower()
            rtype = (sample.get('resource_type') or '').lower()
            entry: dict[str, Any] = {
                'resource_type': rtype,
                'resource_name': sample.get('resource_name'),
                'resource_key': sample.get('resource_key'),
                'checks': {},
                'issues': [],
            }
            hit = db_index.get(rid)
            inv_row = hit[1] if hit and hit[0] == 'inventory' else None
            entry['checks']['db_source'] = hit[0] if hit else None
            entry['checks']['db_inventory_row'] = inv_row is not None
            if not hit:
                entry['issues'].append('postgres: missing in findings and inventory')
            elif hit[0] == 'finding':
                entry['checks']['db_finding_only'] = True
                entry['issues'].extend(compare_api_to_db_record(sample, 'finding', hit[1]))
            else:
                if (hit[1].get('resource_name') or '') != (sample.get('resource_name') or ''):
                    entry['issues'].append('postgres: name differs from API list')
                ev = hit[1].get('evidence') or {}
                entry['checks']['db_arm_detail'] = ev.get('arm_detail')

            db_row = inv_row

            az = az_by_id.get(rid)
            entry['checks']['azure_arg_found'] = az is not None
            if az:
                entry['issues'].extend(compare_identity(az, sample, 'azure_arg vs api_list'))
                if db_row:
                    entry['issues'].extend(compare_identity(az, db_row, 'azure_arg vs db'))
            else:
                entry['issues'].append('azure: resource not found in ARG')

            if db_row and supports_arm_detail(rtype):
                arm_status = (db_row.get('evidence') or {}).get('arm_detail')
                entry['checks']['arm_detail_status'] = arm_status
                if arm_status == 'resource_budget_exceeded':
                    entry['checks']['arm_skipped_reason'] = 'pilot ARM detail cap'
                elif arm_status == 'collected' and arm_spots_left > 0:
                    version = arm_api_version(rtype)
                    if version:
                        arm_spots_left -= 1
                        try:
                            scope = sample['resource_id'].split('/providers/')[0]
                            validate_arm_resource_path(sample['resource_id'], scope_path_lower=scope)
                            body = reader.get(arm_url(sample['resource_id']), {'api-version': version})
                            live_typed = (normalize_arm_body(body).get('typed_configuration')) or {}
                            db_typed = ((db_row.get('evidence') or {}).get('typed_configuration')) or {}
                            entry['checks']['arm_live_spot_check'] = True
                            if live_typed and db_typed and not (set(live_typed) & set(db_typed)):
                                entry['issues'].append('arm: typed_configuration keys diverge from live ARM')
                        except Exception as exc:  # noqa: BLE001 — audit script
                            entry['issues'].append(f'azure_arm: {type(exc).__name__}')
            results.append(entry)
        reader.close()

    return {'scan_id': scan_id, 'sample_count': len(results), 'results': results}


def orchestrator() -> int:
    if not KEY_FILE.exists():
        print(json.dumps({'error': f'Missing key file {KEY_FILE}'}), file=sys.stderr)
        return 2
    key = KEY_FILE.read_text().strip()
    _, scans = http_json('GET', '/api/v1/scans?limit=3', key)
    if not isinstance(scans, list) or not scans:
        print(json.dumps({'error': 'no scans'}), file=sys.stderr)
        return 1
    scan_id = scans[0]['scan_id']
    _, me = http_json('GET', '/api/v1/me', key)
    tenant_id = me.get('tenant_id') if isinstance(me, dict) else None

    items: list[dict] = []
    offset = 0
    max_pages = 1 if QUICK else 20
    pages = 0
    while pages < max_pages:
        st, page = http_json(
            'GET',
            f'/api/v1/scans/{scan_id}/resources?limit=250&offset={offset}&cost_scope=all',
            key,
        )
        if st >= 400 or not isinstance(page, dict):
            print(json.dumps({'error': 'resources list failed', 'status': st}), file=sys.stderr)
            return 1
        batch = page.get('items') or []
        items.extend(batch)
        total = page.get('total', len(batch))
        if offset + len(batch) >= total:
            break
        offset += len(batch)
        pages += 1

    samples = pick_samples(items)
    if QUICK and len(items) > 250:
        # One page is enough to discover types when inventory is large.
        samples = pick_samples(items[:250])

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch_detail(sample: dict) -> dict:
        rk = sample['resource_key']
        st, detail = http_json('GET', f'/api/v1/scans/{scan_id}/resources/{rk}', key)
        issues: list[str] = []
        if st >= 400 or st == 599:
            return {'resource_type': sample.get('resource_type'), 'resource_key': rk, 'issues': [f'detail HTTP {st}: {detail}']}
        if not isinstance(detail, dict):
            return {'resource_type': sample.get('resource_type'), 'resource_key': rk, 'issues': ['detail not JSON object']}
        a = detail.get('assessment') or {}
        if (a.get('resource_id') or '').lower() != (sample.get('resource_id') or '').lower():
            issues.append('list vs detail resource_id')
        if a.get('resource_name') != sample.get('resource_name'):
            issues.append('list vs detail resource_name')
        obs = detail.get('observation')
        return {
            'resource_type': sample.get('resource_type'),
            'resource_name': sample.get('resource_name'),
            'resource_key': rk,
            'resource_id': sample.get('resource_id'),
            'service_category': sample.get('service_category'),
            'arm_detail': a.get('arm_detail'),
            'finding_count': len(detail.get('findings') or []),
            'pillar_count': len(a.get('pillars') or []),
            'has_observation': obs is not None,
            'has_configuration_detail': bool(detail.get('configuration_detail')),
            'ui_path': f'/resources?resource={rk}',
            'issues': issues,
        }

    api_results: list[dict] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(fetch_detail, s) for s in samples]
        for fut in as_completed(futs):
            api_results.append(fut.result())

    worker_payload = {
        'scan_id': scan_id,
        'tenant_id': tenant_id,
        'subscription_ids': me.get('subscription_ids') if isinstance(me, dict) else [],
        'azure_tenant_id': (me.get('identity') or {}).get('azure_tenant_id') if isinstance(me, dict) else None,
        'identity': me.get('identity') if isinstance(me, dict) else {},
        'arm_spot_checks': ARM_SPOT_CHECKS if QUICK else len(samples),
        'samples': [
            {
                'resource_key': s['resource_key'],
                'resource_id': s['resource_id'],
                'resource_name': s.get('resource_name'),
                'resource_type': s.get('resource_type'),
                'resource_group': s.get('resource_group'),
            }
            for s in samples
        ],
    }

    worker_out: dict = {}
    if SKIP_AZURE:
        worker_out = {'skipped': True, 'reason': 'VALIDATE_SKIP_AZURE'}
    else:
        import subprocess

        script_path = Path(__file__).resolve()
        cp = subprocess.run(
            [
                'docker',
                'compose',
                'run',
                '--rm',
                '--no-deps',
                '-v',
                f'{script_path.parent}:/scripts:ro',
                'scanner-service',
                'python',
                '/scripts/validate_resource_type_sample.py',
                '--worker',
            ],
            cwd=str(ROOT),
            input=(json.dumps(worker_payload) + '\n').encode(),
            capture_output=True,
            timeout=120,
        )
        if cp.returncode != 0:
            worker_out = {
                'error': 'worker failed',
                'stderr': cp.stderr.decode('utf-8', 'replace')[-1200:],
                'stdout': cp.stdout.decode('utf-8', 'replace')[-400:],
            }
        else:
            try:
                worker_out = json.loads(cp.stdout.decode())
            except json.JSONDecodeError:
                worker_out = {'error': 'worker invalid json', 'stdout': cp.stdout.decode()[:500]}

    by_key = {r['resource_key']: r for r in api_results if 'resource_key' in r}
    for wr in worker_out.get('results') or []:
        rk = wr.get('resource_key')
        if rk in by_key:
            by_key[rk]['azure_db'] = wr

    failed = sum(
        1
        for r in api_results
        if r.get('issues') or (r.get('azure_db') or {}).get('issues')
    )
    if worker_out.get('error') and not SKIP_AZURE:
        failed = max(failed, 1)
    report = {
        'scan_id': scan_id,
        'types_sampled': len(samples),
        'distinct_types_in_scan': len({(i.get('resource_type') or '').lower() for i in items}),
        'inventory_total': len(items),
        'failed_samples': failed,
        'samples': api_results,
        'worker_error': worker_out.get('error'),
        'worker_stderr_tail': worker_out.get('stderr') if worker_out.get('error') else None,
    }
    print(json.dumps(report, indent=2))
    return 1 if failed else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        payload = json.loads(sys.stdin.read())
        print(json.dumps(worker_validate(payload)))
        return 0
    return orchestrator()


if __name__ == '__main__':
    raise SystemExit(main())
