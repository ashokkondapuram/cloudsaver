"""Azure live + Postgres ingestion + gateway/UI API parity for the latest completed scan."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
KEY_PATH = Path(os.getenv('AUDIT_KEY_OUT', '/audit-key'))
GATEWAY = os.getenv('AUDIT_GATEWAY_URL', 'http://127.0.0.1:8000').rstrip('/')
UI_ORIGIN = os.getenv('AUDIT_UI_ORIGIN', 'http://127.0.0.1:3000').rstrip('/')
CHECK_UI = os.getenv('VALIDATE_UI_BFF', 'true').lower() in ('1', 'true', 'yes')
SAMPLE_TYPES = int(os.getenv('VALIDATE_SAMPLE_TYPES', '6'))
PER_TYPE = int(os.getenv('VALIDATE_PER_TYPE', '2'))
FINDING_SAMPLE = int(os.getenv('VALIDATE_FINDING_SAMPLE', '3'))
LIST_LIMIT = int(os.getenv('VALIDATE_LIST_LIMIT', '80'))

RULE_PREDICATES = {
    'AZURE_DISK_UNATTACHED_RETENTION': "type =~ 'microsoft.compute/disks' and tostring(properties.diskState) == 'Unattached'",
    'AZURE_PUBLIC_IP_UNASSOCIATED': "type =~ 'microsoft.network/publicipaddresses' and isempty(properties.ipConfiguration.id) and isempty(properties.natGateway.id)",
    'AZURE_VM_STOPPED_RESIDUAL_COST': "type =~ 'microsoft.compute/virtualmachines' and tostring(properties.extended.instanceView.powerState.code) in ('PowerState/stopped','PowerState/deallocated')",
    'AZURE_ASP_EMPTY_PAID_PLAN': "type =~ 'microsoft.web/serverfarms' and toint(properties.numberOfSites) == 0",
    'ORPHANED_NIC': "type =~ 'microsoft.network/networkinterfaces' and isempty(properties.virtualMachine.id) and isempty(properties.privateEndpoint.id)",
    'ORPHANED_NSG': "type =~ 'microsoft.network/networksecuritygroups' and coalesce(array_length(properties.networkInterfaces), 0) == 0 and coalesce(array_length(properties.subnets), 0) == 0",
    'AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR': "type =~ 'microsoft.network/applicationgateways' and (properties.operationalState =~ 'Stopped' or coalesce(array_length(properties.backendAddressPools), 0) == 0)",
}


def load_key() -> str:
    if not KEY_PATH.exists():
        print(json.dumps({'error': f'Missing key file {KEY_PATH}'}), file=sys.stderr)
        raise SystemExit(2)
    return KEY_PATH.read_text().strip()


def http_get(origin: str, path: str, key: str) -> tuple[int, Any]:
    req = urllib.request.Request(
        origin + path,
        headers={'Authorization': f'Bearer {key}', 'Accept': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            if 'application/json' in (resp.headers.get('content-type') or ''):
                return resp.status, json.loads(raw)
            return resp.status, raw[:200]
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:300].decode('utf-8', 'replace')


def page_checks(scan_id: str, resource_key: str | None, key: str) -> list[dict]:
    paths: list[tuple[str, str]] = [
        ('bootstrap', '/api/v1/me'),
        ('bootstrap', '/api/v1/billing/entitlements'),
        ('overview', f'/api/v1/scans/{scan_id}'),
        ('overview', f'/api/v1/scans/{scan_id}/analysis'),
        ('resources', f'/api/v1/scans/{scan_id}/resources?limit=10&cost_scope=all'),
        ('settings', '/api/v1/settings'),
        ('settings', '/api/v1/settings/cloud-status'),
        ('finops', '/api/v1/finops/summary'),
        ('outcomes', '/api/v1/outcomes/summary'),
        ('governance', '/api/v1/governance/summary'),
        ('activity', '/api/v1/operations/reliability'),
        ('kubernetes', f'/api/v1/scans/{scan_id}/kubernetes'),
        ('agents', '/api/v1/agents/tasks?limit=10'),
        ('workloads', '/api/v1/engineering/workloads'),
        ('gitops', '/api/v1/gitops/targets'),
    ]
    if resource_key:
        paths.append(('resource', f'/api/v1/scans/{scan_id}/resources/{resource_key}'))
    out: list[dict] = []
    for page, path in paths:
        status, body = http_get(GATEWAY, path, key)
        ok = 200 <= status < 400
        row: dict[str, Any] = {'page': page, 'path': path, 'status': status, 'ok': ok}
        if not ok:
            row['error'] = str(body)[:180]
        elif isinstance(body, dict):
            if 'total' in body:
                row['total'] = body['total']
            if 'findings' in body and isinstance(body['findings'], list):
                row['findings'] = len(body['findings'])
        out.append(row)
    return out


def ui_bff_parity(scan_id: str, key: str, sample_keys: list[str] | None = None) -> list[dict]:
    if not CHECK_UI or UI_ORIGIN == GATEWAY:
        return []
    samples = [
        '/api/v1/me',
        f'/api/v1/scans/{scan_id}/resources?limit=5&cost_scope=all',
    ]
    for rk in (sample_keys or [])[:2]:
        samples.append(f'/api/v1/scans/{scan_id}/resources/{rk}')
    rows: list[dict] = []
    for path in samples:
        g_st, g_body = http_get(GATEWAY, path, key)
        u_st, u_body = http_get(UI_ORIGIN, path, key)
        match = g_st == u_st == 200 and g_body == u_body
        rows.append({'path': path, 'gateway_status': g_st, 'ui_status': u_st, 'ok': match})
    return rows


def fetch_api_inventory_page(scan_id: str, key: str, *, limit: int) -> tuple[list[dict], int]:
    st, page = http_get(
        GATEWAY,
        f'/api/v1/scans/{scan_id}/resources?limit={limit}&offset=0&cost_scope=all',
        key,
    )
    if st >= 400 or not isinstance(page, dict):
        raise RuntimeError(f'resources API failed: {st}')
    items = page.get('items') or []
    total = int(page.get('total') or len(items))
    return items, total


def load_db_scan(scan_id: str, tenant_id: str) -> dict:
    import os
    import psycopg

    url = os.environ['CLOUDSAVER_DATABASE_URL']
    with psycopg.connect(url) as db:
        db.execute("SELECT set_config('app.current_tenant_id', %s, true)", (str(UUID(tenant_id)),))
        row = db.execute(
            'SELECT payload FROM public.scans WHERE id=%s AND tenant_id=%s',
            (scan_id, tenant_id),
        ).fetchone()
    if not row:
        raise RuntimeError('scan not found in postgres')
    return row[0]


def compare_api_db(api_items: list[dict], db_payload: dict) -> dict[str, Any]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from validation_scan_db import compare_api_db as _compare

    return _compare(api_items, db_payload)


def azure_arg_batch(
    tenant_id: str,
    identity_map: dict,
    subs: list[str],
    resource_ids: list[str],
) -> dict[str, dict]:
    from app.cloud_identity import CredentialError, azure_credential, identity_mode
    from app.scanner import execute_pages

    def cred():
        workspace = {'tenant_id': tenant_id, 'identity': identity_map}
        try:
            return azure_credential(workspace)
        except CredentialError:
            if identity_mode() != 'developer':
                raise
            from azure.identity import AzureCliCredential

            return AzureCliCredential(process_timeout=60)

    by_id: dict[str, dict] = {}
    with cred() as credential:
        for start in range(0, len(resource_ids), 80):
            chunk = resource_ids[start : start + 80]
            quoted = ','.join("'" + i.replace("'", "''") + "'" for i in chunk)
            query = (
                'Resources | where id in (' + quoted + ') '
                '| project id, name, type, resourceGroup, subscriptionId'
            )
            for row in execute_pages(credential, query, subs):
                by_id[row['id'].lower()] = row
    return by_id


def validate_findings_in_azure(credential, subs: list[str], findings: list[dict]) -> tuple[int, list[str]]:
    from app.collectors.azure_resource_graph import _post_page, build_query_body
    from app.scanner import ScanError

    by_rule: dict[str, list[str]] = defaultdict(list)
    for f in findings:
        if f.get('rule_id') in RULE_PREDICATES:
            by_rule[f['rule_id']].append(f['resource_id'])
    ok_ids: set[str] = set()
    issues: list[str] = []

    def run_query(query: str) -> list[dict]:
        body = build_query_body(query, subs, allow_partial_scopes=True)
        response = _post_page(credential, body)
        rows = response.get('data')
        if not isinstance(rows, list):
            raise ScanError('unexpected ARG response')
        return [r for r in rows if isinstance(r, dict)]

    for rule_id, rids in by_rule.items():
        pred = RULE_PREDICATES[rule_id]
        for start in range(0, len(rids), 40):
            chunk = rids[start : start + 40]
            quoted = ','.join("'" + i.replace("'", "''") + "'" for i in chunk)
            query = f"Resources | where id in ({quoted}) | where {pred} | project id"
            try:
                for row in run_query(query):
                    rid = (row.get('id') or '').lower()
                    if rid:
                        ok_ids.add(rid)
            except ScanError as exc:
                issues.append(f'batch {rule_id}: {exc}')

    ok = 0
    for f in findings:
        rid = (f.get('resource_id') or '').lower()
        if f.get('rule_id') not in RULE_PREDICATES:
            continue
        if rid in ok_ids:
            ok += 1
        else:
            issues.append(f"{f.get('rule_id')}:{rid[:48]}")
    return ok, issues


tenant_id_ws = ''
identity: dict = {}


def main() -> int:
    key = load_key()
    _, me = http_get(GATEWAY, '/api/v1/me', key)
    if not isinstance(me, dict):
        print(json.dumps({'error': 'me failed'}), file=sys.stderr)
        return 1
    tenant_id = me['tenant_id']
    identity_map = me.get('identity') or {}

    _, scans = http_get(GATEWAY, '/api/v1/scans?limit=5', key)
    if not isinstance(scans, list) or not scans:
        print(json.dumps({'error': 'no scans'}), file=sys.stderr)
        return 1
    scan_id = scans[0]['scan_id']
    _, scan_get = http_get(GATEWAY, f'/api/v1/scans/{scan_id}', key)
    list_page, inventory_total = fetch_api_inventory_page(scan_id, key, limit=LIST_LIMIT)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from validation_scan_db import expand_subscription_ids, pick_resource_samples, sample_findings

    api_items = pick_resource_samples(list_page, max_types=SAMPLE_TYPES, max_per_type=PER_TYPE)
    rk = api_items[0]['resource_key'] if api_items else None

    db_payload = load_db_scan(scan_id, tenant_id)
    api_db = compare_api_db(api_items, db_payload)
    api_db['inventory_total_reported'] = inventory_total
    api_db['sampled_for_deep_check'] = len(api_items)

    subs = [str(UUID(s)) for s in (me.get('subscription_ids') or [])]
    if not subs:
        sub = os.getenv('AUDIT_SUBSCRIPTION_ID', '93ca908b-5732-440d-b712-f6d7951951c0')
        subs = [str(UUID(sub))]
    resource_ids = [r['resource_id'] for r in api_items if r.get('resource_id')]
    arg_subs = expand_subscription_ids(subs, resource_ids)
    az_by_id = azure_arg_batch(tenant_id, identity_map, arg_subs, resource_ids)
    arg_missing = [rid for rid in resource_ids if rid.lower() not in az_by_id]
    arg_mismatch = 0
    for row in api_items:
        az = az_by_id.get((row.get('resource_id') or '').lower())
        if not az:
            continue
        if az.get('name') != row.get('resource_name') or (az.get('type') or '').lower() != (row.get('resource_type') or '').lower():
            arg_mismatch += 1

    findings = sample_findings(
        [f for f in (db_payload.get('findings') or []) if f.get('rule_id') in RULE_PREDICATES],
        max_items=FINDING_SAMPLE,
    )
    findings_ok, finding_issues = 0, []
    if findings:
        from app.cloud_identity import azure_credential, identity_mode, CredentialError

        def cred():
            workspace = {'tenant_id': tenant_id, 'identity': identity_map}
            try:
                return azure_credential(workspace)
            except CredentialError:
                if identity_mode() != 'developer':
                    raise
                from azure.identity import AzureCliCredential

                return AzureCliCredential(process_timeout=60)

        with cred() as credential:
            f_subs = expand_subscription_ids(subs, [f['resource_id'] for f in findings if f.get('resource_id')])
            try:
                findings_ok, finding_issues = validate_findings_in_azure(credential, f_subs, findings)
            except Exception as exc:  # noqa: BLE001
                finding_issues = [f'findings validation: {type(exc).__name__}: {exc}']
                findings_ok = 0

    detail_issues: list[str] = []
    sample_keys = [r['resource_key'] for r in api_items]

    def check_detail(rk_val: str) -> str | None:
        st, detail = http_get(GATEWAY, f'/api/v1/scans/{scan_id}/resources/{rk_val}', key)
        if st >= 400:
            return f'detail {st} for {rk_val[:12]}'
        if not isinstance(detail, dict):
            return 'detail not json'
        a = detail.get('assessment') or {}
        list_row = next((x for x in api_items if x['resource_key'] == rk_val), None)
        if list_row and (a.get('resource_id') or '').lower() != (list_row.get('resource_id') or '').lower():
            return f'id mismatch {rk_val[:12]}'
        return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        for err in pool.map(check_detail, sample_keys):
            if err:
                detail_issues.append(err)

    pages = page_checks(scan_id, rk, key)
    ui_rows = ui_bff_parity(scan_id, key, [r['resource_key'] for r in api_items])

    scan_findings_api = len(scan_get.get('findings') or []) if isinstance(scan_get, dict) else None
    report = {
        'scan_id': scan_id,
        'tenant_id': tenant_id,
        'gateway_pages': {
            'passed': sum(1 for p in pages if p['ok']),
            'failed': sum(1 for p in pages if not p['ok']),
            'results': pages,
        },
        'ui_bff': ui_rows,
        'db_ingestion': {
            'scan_status': db_payload.get('status'),
            'db_inventory_count': api_db['db_inventory_count'],
            'db_findings_count': api_db['db_findings_count'],
            'api_scan_findings': scan_findings_api,
        },
        'api_vs_db': api_db,
        'sample_config': {
            'types': SAMPLE_TYPES,
            'per_type': PER_TYPE,
            'finding_sample': FINDING_SAMPLE,
            'list_limit': LIST_LIMIT,
        },
        'azure_arg': {
            'resources_checked': len(resource_ids),
            'arg_found': len(az_by_id),
            'arg_missing_count': len(arg_missing),
            'arg_missing_sample': arg_missing[:5],
            'identity_mismatch_count': arg_mismatch,
        },
        'findings_vs_azure': {
            'findings_total': len(db_payload.get('findings') or []),
            'findings_sampled': len(findings),
            'findings_ok': findings_ok,
            'issues_sample': finding_issues[:10],
        },
        'resource_detail_spot_check': {'sampled': len(sample_keys), 'issues': detail_issues},
    }
    predicate_findings = [f for f in findings if f.get('rule_id') in RULE_PREDICATES]
    failed = (
        report['gateway_pages']['failed']
        or report['api_vs_db']['issues_count']
        or report['azure_arg']['identity_mismatch_count']
        or (predicate_findings and findings_ok < len(predicate_findings))
        or detail_issues
        or any(not r['ok'] for r in ui_rows)
    )
    if report['azure_arg']['arg_missing_count'] > 0:
        report['azure_arg']['arg_missing_note'] = 'Resource absent in live Azure ARG (deleted or wrong sub); not a DB/API sync failure.'
    report['ok'] = not failed
    print(json.dumps(report, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
