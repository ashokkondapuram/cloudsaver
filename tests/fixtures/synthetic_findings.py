"""Synthetic inventory used only by unit tests — not available at runtime."""
from app.scanner import RULES


def demo_workspace(tenant):
    return dict(
        tenant,
        aws_accounts=[dict(account_id='123456789012', region='us-east-1', credential_profile='test')],
        gcp_projects=[dict(project_id='demo-cloudsaver', regions=['us-central1'])],
        kubernetes_clusters=[dict(cluster_id='demo-cluster', prometheus_url='https://prom.example', bearer_token_env='CLOUDSAVER_PROMETHEUS_TOKEN_PRIMARY')],
    )


def demo_findings(*, expanded=False) -> list[dict]:
    subscription = "00000000-0000-0000-0000-000000000001"
    fixtures = [
        (0, "archive-export-disk", 76.80), (0, "old-build-cache", 38.40),
        (0, "migration-snapshot-disk", 153.60), (1, "unused-edge-ip", 3.65),
        (1, "legacy-api-ip", 3.65), (2, "retired-build-agent", 12.80),
        (3, "staging-app-plan", 73.00), (3, "legacy-web-plan", 146.00),
        (4, "nic-legacy-worker-unattached", 0.00),
        (5, "nsg-dev-sandbox-orphaned", 0.00),
        (6, "agw-prod-ingress-idle", 178.85),
    ]
    results = []
    types = [
        "microsoft.compute/disks", "microsoft.network/publicipaddresses",
        "microsoft.compute/virtualmachines", "microsoft.web/serverfarms",
        "microsoft.network/networkinterfaces", "microsoft.network/networksecuritygroups",
        "microsoft.network/applicationgateways",
    ]
    for index, name, amount in (fixtures if expanded else fixtures[:8]):
        rule_id, severity, _, description = RULES[index]
        resource_type = types[index]
        results.append({
            "rule_id": rule_id, "severity": severity,
            "resource_name": name, "resource_type": resource_type,
            "resource_group": "demo-platform", "subscription_id": subscription,
            "resource_id": f"/subscriptions/{subscription}/resourceGroups/demo-platform/providers/{resource_type}/{name}",
            "estimated_monthly_waste_usd": amount,
            "details": "TEST FIXTURE: " + description,
        })
    return results


def demo_cloud_findings(tenant, providers):
    values = []
    if 'azure' in providers:
        for item in demo_findings(expanded=True):
            sub = tenant['subscription_ids'][0]
            item.update(
                cloud_provider='azure', subscription_id=sub,
                resource_id=f"/subscriptions/{sub}/resourceGroups/{item['resource_group']}/providers/{item['resource_type']}/{item['resource_name']}",
            )
            values.append(item)

    def add(provider, rule, rid, kind, scope, name, amount, region=None, evidence=None):
        values.append(dict(
            cloud_provider=provider, rule_id=rule, severity='MEDIUM',
            resource_id=rid, resource_type=kind, scope_id=scope, subscription_id=scope,
            resource_name=name, resource_group='demo', region=region,
            estimated_monthly_waste_usd=amount, evidence=evidence or {},
            details='TEST FIXTURE: synthetic inventory for unit tests.',
        ))

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
            ('GCP_IDLE_CLOUD_SQL', 'instances/staging-db', 'sqladmin.googleapis.com/Instance', 'staging-db', None),
        ]:
            host = 'sqladmin' if path.startswith('instances') else 'compute'
            add('gcp', rule, f'//{host}.googleapis.com/projects/demo-cloudsaver/{path}', kind, 'demo-cloudsaver', name, amount, 'us-central1')
    if 'kubernetes' in providers:
        for dimension, baseline, usage, unit in [('CPU', 2, .4, 'cores'), ('MEMORY', 4294967296, 1073741824, 'bytes')]:
            add(
                'kubernetes', f'K8S_{dimension}_OVERSIZED',
                'k8s://demo-cluster/namespaces/staging/pods/api-worker/containers/api',
                'kubernetes.io/Container', 'demo-cluster', 'api', None,
                evidence=dict(
                    dimension=dimension.lower(), minimum_request=baseline, p95_usage=usage, unit=unit,
                    samples=337, suggested_request_with_50pct_headroom=usage * 1.5, source='test fixture',
                ),
            )
    return values
