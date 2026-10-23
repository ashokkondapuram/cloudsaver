"""Explicit, read-only provider coordination. Any provider failure aborts the scan."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json

from app.cloud_scope import configured_providers, validate_finding_scope
from app.scanner import ScanError, scan_live


def scope_fingerprint(tenant, providers):
    scope = {'azure': sorted(tenant.get('subscription_ids', [])),
             'aws': sorted((a['account_id'], a['region']) for a in tenant.get('aws_accounts', [])),
             'gcp': sorted((p['project_id'], sorted(p['regions'])) for p in tenant.get('gcp_projects', [])),
             'kubernetes': sorted(c['cluster_id'] for c in tenant.get('kubernetes_clusters', []))}
    return hashlib.sha256(json.dumps({p: scope[p] for p in sorted(providers)}, sort_keys=True).encode()).hexdigest()


def scan_multi_cloud(tenant, providers, *, enabled_rule_ids=None):
    if not providers or len(providers) != len(set(providers)) or not set(providers) <= set(configured_providers(tenant)):
        raise ScanError('Provider selection is not configured for this workspace')
    from app.scanner_aws import scan_account
    from app.scanner_gcp import scan_gcp_project
    from app.scanner_kubernetes import scan_cluster
    collectors=[]
    azure_inventory = []
    if 'azure' in providers:
        def collect_azure():
            findings, inventory = scan_live(tenant, enabled_rule_ids=enabled_rule_ids)
            azure_inventory.extend(inventory)
            return findings
        collectors.append(collect_azure)
    if 'aws' in providers:
        for source in tenant.get('aws_accounts',[]):
            bound=dict(source,external_id=tenant['tenant_id'])
            collectors.append(lambda bound=bound:scan_account(bound))
    if 'gcp' in providers:
        account=(tenant.get('identity') or {}).get('gcp_service_account')
        for source in tenant.get('gcp_projects',[]):
            bound=dict(source,service_account=account) if account else dict(source)
            collectors.append(lambda bound=bound:scan_gcp_project(bound))
    if 'kubernetes' in providers:
        for source in tenant.get('kubernetes_clusters',[]):
            collectors.append(lambda source=dict(source):scan_cluster(source))
    findings=[]
    if collectors:
        # Fixed concurrency bounds cloud pressure. Any failed collector discards the whole result.
        batches={};count=0
        with ThreadPoolExecutor(max_workers=min(4,len(collectors)),thread_name_prefix='cloudsaver-reader') as pool:
            futures={pool.submit(collect):index for index,collect in enumerate(collectors)}
            try:
                for future in as_completed(futures):
                    batch=future.result()
                    if not isinstance(batch,list):
                        raise ScanError('Scanner returned an invalid finding batch')
                    count+=len(batch)
                    if count>100000:
                        raise ScanError('Multi-cloud inventory finding limit exceeded')
                    batches[futures[future]]=batch
            except BaseException:
                for future in futures: future.cancel()
                raise
        # Completion order never changes snapshot ordering or fingerprints.
        findings=[finding for index in sorted(batches) for finding in batches[index]]
    seen = set()
    for finding in findings:
        if finding.get('cloud_provider', 'azure') not in providers:
            raise ScanError('Scanner returned an unrequested provider')
        validate_finding_scope(finding, tenant)
        identity = (finding['rule_id'], finding['resource_id'])
        if identity in seen:
            raise ScanError('Scanner returned a duplicate finding')
        seen.add(identity)
        if len(seen) > 100000:
            raise ScanError('Multi-cloud inventory finding limit exceeded')
    return findings, azure_inventory
