"""Explicit, read-only provider coordination. Any provider failure aborts the scan."""
import hashlib
import json

from app.cloud_scope import configured_providers, demo_workspace, validate_finding_scope
from app.scanner import ScanError, demo_findings, scan_live


def scope_fingerprint(tenant, providers, *, demo=False):
    tenant = demo_workspace(tenant) if demo else tenant
    scope = {'azure': sorted(tenant.get('subscription_ids', [])),
             'aws': sorted((a['account_id'], a['region']) for a in tenant.get('aws_accounts', [])),
             'gcp': sorted((p['project_id'], sorted(p['regions'])) for p in tenant.get('gcp_projects', [])),
             'kubernetes': sorted(c['cluster_id'] for c in tenant.get('kubernetes_clusters', []))}
    return hashlib.sha256(json.dumps({p: scope[p] for p in sorted(providers)}, sort_keys=True).encode()).hexdigest()


def demo_cloud_findings(tenant, providers):
    values = []
    if 'azure' in providers:
        for item in demo_findings(expanded=True):
            sub = tenant['subscription_ids'][0]
            item.update(cloud_provider='azure', subscription_id=sub,
                        resource_id=f"/subscriptions/{sub}/resourceGroups/{item['resource_group']}/providers/{item['resource_type']}/{item['resource_name']}")
            values.append(item)
    def add(provider, rule, rid, kind, scope, name, amount, region=None, evidence=None):
        values.append(dict(cloud_provider=provider, rule_id=rule, severity='MEDIUM',
            resource_id=rid, resource_type=kind, scope_id=scope, subscription_id=scope,
            resource_name=name, resource_group='demo', region=region,
            estimated_monthly_waste_usd=amount, evidence=evidence or {},
            details='DEMO: synthetic inventory and telemetry. Amounts are illustrative, not billing data or verified savings.'))
    if 'aws' in providers:
        for name, amount in [('vol-08a9c2b4d1ef50123', 8.0), ('vol-0b73e512c98a34211', 62.5)]:
            add('aws', 'AWS_UNATTACHED_EBS', f'arn:aws:ec2:us-east-1:123456789012:volume/{name}', 'aws:ec2:volume', '123456789012', name, amount, 'us-east-1')
        for name in ['eipalloc-01f2a3b4c5d6e7f80', 'eipalloc-09a8b7c6d5e4f3a21']:
            add('aws', 'AWS_UNASSOCIATED_EIP', f'arn:aws:ec2:us-east-1:123456789012:elastic-ip/{name}', 'aws:ec2:elastic-ip', '123456789012', name, 3.65, 'us-east-1')
        add('aws', 'AWS_IDLE_RDS', 'arn:aws:rds:us-east-1:123456789012:db:staging-postgres', 'aws:rds:db', '123456789012', 'staging-postgres', 23.0, 'us-east-1')
    if 'gcp' in providers:
        for rule, path, kind, name, amount in [
            ('GCP_UNATTACHED_DISK', 'zones/us-central1-a/disks/archive', 'compute.googleapis.com/Disk', 'archive', 16.0),
            ('GCP_UNASSIGNED_ADDRESS', 'regions/us-central1/addresses/unused-ip', 'compute.googleapis.com/Address', 'unused-ip', 7.3),
            ('GCP_IDLE_CLOUD_SQL', 'instances/staging-db', 'sqladmin.googleapis.com/Instance', 'staging-db', None)]:
            host = 'sqladmin' if path.startswith('instances') else 'compute'
            add('gcp', rule, f'//{host}.googleapis.com/projects/demo-cloudsaver/{path}', kind,
                'demo-cloudsaver', name, amount, 'us-central1')
    if 'kubernetes' in providers:
        for dimension, baseline, usage, unit in [('CPU', 2, .4, 'cores'), ('MEMORY', 4294967296, 1073741824, 'bytes')]:
            add('kubernetes', f'K8S_{dimension}_OVERSIZED', 'k8s://demo-cluster/namespaces/staging/pods/api-worker/containers/api',
                'kubernetes.io/Container', 'demo-cluster', 'api', None,
                evidence=dict(dimension=dimension.lower(), minimum_request=baseline, p95_usage=usage, unit=unit,
                              samples=337, suggested_request_with_50pct_headroom=usage * 1.5, source='synthetic demo'))
    return values


def scan_multi_cloud(tenant, providers, *, mode):
    if not providers or len(providers) != len(set(providers)) or not set(providers) <= set(configured_providers(tenant, demo=mode == 'demo')):
        raise ScanError('Provider selection is not configured for this workspace')
    if mode == 'demo':
        findings = demo_cloud_findings(tenant, providers)
        effective = demo_workspace(tenant)
    else:
        from app.scanner_aws import scan_account
        from app.scanner_gcp import scan_gcp_project
        from app.scanner_kubernetes import scan_cluster
        findings, effective = [], tenant
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
        validate_finding_scope(finding, effective)
        identity = (finding['rule_id'], finding['resource_id'])
        if identity in seen:
            raise ScanError('Scanner returned a duplicate finding')
        seen.add(identity)
        if len(seen) > 100000:
            raise ScanError('Multi-cloud inventory finding limit exceeded')
    return findings
