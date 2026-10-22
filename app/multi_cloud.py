"""Explicit, read-only provider coordination. Any provider failure aborts the scan."""
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


def scan_multi_cloud(tenant, providers):
    if not providers or len(providers) != len(set(providers)) or not set(providers) <= set(configured_providers(tenant)):
        raise ScanError('Provider selection is not configured for this workspace')
    from app.scanner_aws import scan_account
    from app.scanner_gcp import scan_gcp_project
    from app.scanner_kubernetes import scan_cluster
    findings = []
    def collect(batch):
        if len(findings) + len(batch) > 100000:
            raise ScanError('Multi-cloud inventory finding limit exceeded')
        findings.extend(batch)
    if 'azure' in providers:
        collect(scan_live(tenant))
    if 'aws' in providers:
        for source in tenant.get('aws_accounts', []):
            collect(scan_account(source))
    if 'gcp' in providers:
        for source in tenant.get('gcp_projects', []):
            collect(scan_gcp_project(source))
    if 'kubernetes' in providers:
        for source in tenant.get('kubernetes_clusters', []):
            collect(scan_cluster(source))
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
    return findings
