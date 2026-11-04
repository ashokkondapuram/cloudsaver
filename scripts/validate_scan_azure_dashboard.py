"""Compare saved scan + dashboard APIs to live Azure Resource Graph (read-only)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = Path(os.getenv('AUDIT_KEY_OUT', str(ROOT / '.env.audit-workspace-key')))
GATEWAY = os.getenv('AUDIT_GATEWAY_URL', 'http://127.0.0.1:8000').rstrip('/')
SUB = os.getenv('AUDIT_SUBSCRIPTION_ID', '93ca908b-5732-440d-b712-f6d7951951c0')

RULE_PREDICATES = {
    'AZURE_DISK_UNATTACHED_RETENTION': "type =~ 'microsoft.compute/disks' and tostring(properties.diskState) == 'Unattached'",
    'AZURE_PUBLIC_IP_UNASSOCIATED': "type =~ 'microsoft.network/publicipaddresses' and isempty(properties.ipConfiguration.id) and isempty(properties.natGateway.id)",
    'AZURE_VM_STOPPED_RESIDUAL_COST': "type =~ 'microsoft.compute/virtualmachines' and tostring(properties.extended.instanceView.powerState.code) in ('PowerState/stopped','PowerState/deallocated')",
    'AZURE_ASP_EMPTY_PAID_PLAN': "type =~ 'microsoft.web/serverfarms' and toint(properties.numberOfSites) == 0",
    'ORPHANED_NIC': "type =~ 'microsoft.network/networkinterfaces' and isempty(properties.virtualMachine.id) and isempty(properties.privateEndpoint.id)",
    'ORPHANED_NSG': "type =~ 'microsoft.network/networksecuritygroups' and coalesce(array_length(properties.networkInterfaces), 0) == 0 and coalesce(array_length(properties.subnets), 0) == 0",
    'AZURE_APPGW_EMPTY_OR_HIGH_AUTOSCALE_FLOOR': "type =~ 'microsoft.network/applicationgateways' and (properties.operationalState =~ 'Stopped' or coalesce(array_length(properties.backendAddressPools), 0) == 0)",
}


def validate_findings_batch(rg_client, subs: list[str], findings: list[dict]) -> tuple[int, list[dict]]:
    """Return (ok_count, issues) using batched ARG queries per rule."""
    from collections import defaultdict

    from app.scanner import execute_pages

    by_rule: dict[str, list[str]] = defaultdict(list)
    for f in findings:
        if f.get('rule_id') in RULE_PREDICATES:
            by_rule[f['rule_id']].append(f['resource_id'])

    ok_ids: set[str] = set()
    issues: list[dict] = []
    for rule_id, rids in by_rule.items():
        pred = RULE_PREDICATES[rule_id]
        for start in range(0, len(rids), 40):
            chunk = rids[start : start + 40]
            quoted = ','.join("'" + i.replace("'", "''") + "'" for i in chunk)
            query = f"Resources | where id in ({quoted}) | where {pred} | project id"
            for row in execute_pages(rg_client, query, subs):
                ok_ids.add(row['id'].lower())

    ok = 0
    for f in findings:
        rid = (f.get('resource_id') or '').lower()
        if f.get('rule_id') not in RULE_PREDICATES:
            issues.append({'kind': 'finding', 'rule_id': f.get('rule_id'), 'resource_id': f.get('resource_id'), 'error': 'no predicate mapping'})
        elif rid in ok_ids:
            ok += 1
        else:
            issues.append({
                'kind': 'finding',
                'rule_id': f.get('rule_id'),
                'resource_id': f.get('resource_id'),
                'error': 'finding predicate fails in live Azure ARG',
            })
    return ok, issues


def main() -> int:
    if not KEY_FILE.exists():
        print('Missing workspace key', file=sys.stderr)
        return 2
    key = KEY_FILE.read_text().strip()
    headers = {'Authorization': f'Bearer {key}'}
    issues: list[dict] = []
    stats = {'resources': 0, 'identity_ok': 0, 'detail_ok': 0, 'analysis_ok': 0, 'findings': 0, 'findings_ok': 0}

    with httpx.Client(timeout=120, trust_env=False) as client:
        scans = client.get(f'{GATEWAY}/api/v1/scans?limit=5', headers=headers).json()
        if not scans:
            print('No scans', file=sys.stderr)
            return 1
        scan_id = scans[0]['scan_id']
        scan = client.get(f'{GATEWAY}/api/v1/scans/{scan_id}', headers=headers).json()
        workspace = client.get(f'{GATEWAY}/api/v1/me', headers=headers).json()
        findings = scan.get('findings') or []
        stats['findings'] = len(findings)

        items: list[dict] = []
        offset = 0
        while True:
            page = client.get(
                f'{GATEWAY}/api/v1/scans/{scan_id}/resources',
                headers=headers,
                params={'limit': 250, 'offset': offset, 'cost_scope': 'all'},
            ).json()
            batch = page.get('items') or []
            items.extend(batch)
            if offset + len(batch) >= page.get('total', len(batch)):
                break
            offset += len(batch)
        stats['resources'] = len(items)

        from azure.mgmt.resourcegraph import ResourceGraphClient
        from app.scanner import execute_pages

        tenant = workspace
        subs = [str(UUID(s)) for s in (workspace.get('subscription_ids') or [SUB])]

        def _azure_credential():
            from app.cloud_identity import CredentialError, azure_credential, identity_mode

            try:
                return azure_credential(tenant)
            except CredentialError:
                if identity_mode() != 'developer':
                    raise
                from azure.identity import AzureCliCredential

                return AzureCliCredential(process_timeout=60)

        with _azure_credential() as credential:
            with ResourceGraphClient(credential, retry_total=2) as rg:
                by_id: dict[str, dict] = {}
                ids = [row['resource_id'] for row in items if row.get('resource_id')]
                for start in range(0, len(ids), 80):
                    chunk = ids[start : start + 80]
                    quoted = ','.join("'" + i.replace("'", "''") + "'" for i in chunk)
                    query = (
                        'Resources | where id in (' + quoted + ') '
                        '| project id, name, type, resourceGroup, subscriptionId'
                    )
                    for row in execute_pages(rg, query, subs):
                        by_id[row['id'].lower()] = row

                for row in items:
                    rid = (row.get('resource_id') or '').lower()
                    az = by_id.get(rid)
                    if not az:
                        issues.append({'kind': 'identity', 'resource_key': row.get('resource_key'), 'error': 'missing in Azure ARG'})
                        continue
                    ok = (
                        az['name'] == row.get('resource_name')
                        and az['type'].lower() == (row.get('resource_type') or '').lower()
                        and az['resourceGroup'] == row.get('resource_group')
                    )
                    if ok:
                        stats['identity_ok'] += 1
                    else:
                        issues.append({
                            'kind': 'identity',
                            'resource_key': row.get('resource_key'),
                            'error': 'name/type/group mismatch',
                            'azure': {'name': az['name'], 'type': az['type'], 'rg': az['resourceGroup']},
                            'dashboard': {
                                'name': row.get('resource_name'),
                                'type': row.get('resource_type'),
                                'rg': row.get('resource_group'),
                            },
                        })

                f_ok, f_issues = validate_findings_batch(rg, subs, findings)
                stats['findings_ok'] = f_ok
                issues.extend(f_issues)

                from app.assessment import assess
                from concurrent.futures import ThreadPoolExecutor, as_completed

                findings_by_rid: dict[str, list] = {}
                for f in findings:
                    findings_by_rid.setdefault(f['resource_id'].lower(), []).append(f)

                def fetch_detail(rk: str) -> tuple[str, dict]:
                    with httpx.Client(timeout=120, trust_env=False) as c:
                        r = c.get(
                            f'{GATEWAY}/api/v1/scans/{scan_id}/resources/{rk}',
                            headers=headers,
                        )
                        r.raise_for_status()
                        return rk, r.json()

                details: dict[str, dict] = {}
                with ThreadPoolExecutor(max_workers=16) as pool:
                    futs = {pool.submit(fetch_detail, row['resource_key']): row for row in items}
                    for fut in as_completed(futs):
                        rk, detail = fut.result()
                        details[rk] = detail

                for row in items:
                    rk = row['resource_key']
                    detail = details[rk]
                    a = detail.get('assessment') or {}
                    detail_ok = True
                    if a.get('resource_id', '').lower() != row.get('resource_id', '').lower():
                        issues.append({'kind': 'detail', 'resource_key': rk, 'error': 'list vs detail resource_id'})
                        detail_ok = False
                    if a.get('resource_name') != row.get('resource_name'):
                        issues.append({'kind': 'detail', 'resource_key': rk, 'error': 'list vs detail resource_name'})
                        detail_ok = False
                    saved = findings_by_rid.get((row.get('resource_id') or '').lower(), [])
                    detail_findings = detail.get('findings') or []
                    if len(saved) != len(detail_findings):
                        issues.append({
                            'kind': 'detail',
                            'resource_key': rk,
                            'error': 'finding count mismatch',
                            'scan': len(saved),
                            'detail': len(detail_findings),
                        })
                        detail_ok = False
                    if detail_ok:
                        stats['detail_ok'] += 1
                    for f in saved:
                        assessed = assess(f, observed_at=scan.get('timestamp'))
                        if len(assessed.get('pillars') or []) != 5:
                            issues.append({'kind': 'analysis', 'resource_id': f['resource_id'], 'error': 'expected 5 pillars'})
                        else:
                            stats['analysis_ok'] += 1
                    if not saved:
                        pillars = a.get('pillars') or []
                        if pillars and len(pillars) != 5:
                            issues.append({'kind': 'analysis', 'resource_key': rk, 'error': 'inventory pillar count'})
                        elif pillars:
                            stats['analysis_ok'] += 1

        summary = client.get(f'{GATEWAY}/api/v1/scans/{scan_id}/analysis', headers=headers).json()

    out = {
        'scan_id': scan_id,
        'stats': stats,
        'analysis_summary_keys': list(summary.keys()) if isinstance(summary, dict) else [],
        'issues_count': len(issues),
        'issues_sample': issues[:25],
    }
    print(json.dumps(out, indent=2))
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())
