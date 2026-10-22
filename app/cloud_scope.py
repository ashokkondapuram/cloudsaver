"""Operator-owned cloud scopes. Request bodies never supply account IDs or URLs."""
import re
from urllib.parse import urlsplit
from uuid import UUID

PROJECT = r'[a-z][a-z0-9-]{4,28}[a-z0-9]'
NAME = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
POD_NAME = r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?'
REGION = r'[a-z]+(?:-[a-z]+)+-?[0-9]+'


def matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def normalize_sources(tenant):
    result = {}
    specs = (
        ('aws_accounts', ('account_id', 'region', 'credential_profile')),
        ('gcp_projects', ('project_id', 'regions')),
        ('kubernetes_clusters', ('cluster_id', 'prometheus_url', 'bearer_token_env')),
    )
    for key, fields in specs:
        entries = tenant.get(key, [])
        if not isinstance(entries, list) or len(entries) > 100:
            raise ValueError('Cloud sources must be bounded lists')
        normalized, seen = [], set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - set(fields):
                raise ValueError('Unknown cloud source configuration field')
            if key == 'aws_accounts':
                if not matches(r'[0-9]{12}', entry.get('account_id')) or not matches(REGION, entry.get('region')):
                    raise ValueError('Invalid AWS account/region')
                if not matches(r'[A-Za-z0-9_-]{1,100}', entry.get('credential_profile')):
                    raise ValueError('An explicit AWS credential profile is required')
                identity = (entry['account_id'], entry['region'])
            elif key == 'gcp_projects':
                if not matches(PROJECT, entry.get('project_id')):
                    raise ValueError('Invalid GCP project ID')
                regions = entry.get('regions')
                if not isinstance(regions, list) or not 1 <= len(regions) <= 50 or any(not matches(REGION, r) for r in regions) or len(set(regions)) != len(regions):
                    raise ValueError('Explicit unique GCP regions are required for regional disks')
                identity = entry['project_id']
            else:
                if not matches(NAME, entry.get('cluster_id')):
                    raise ValueError('Invalid Kubernetes cluster ID')
                url = urlsplit(entry.get('prometheus_url', ''))
                if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ValueError('Prometheus requires an operator-configured HTTPS URL')
                if not matches(r'CLOUDSAVER_PROMETHEUS_TOKEN_[A-Z0-9_]{1,80}', entry.get('bearer_token_env', '')):
                    raise ValueError('Explicit Prometheus bearer-token environment binding required')
                identity = entry['cluster_id']
            if identity in seen:
                raise ValueError('Duplicate cloud source')
            seen.add(identity)
            normalized.append(dict(entry))
        result[key] = normalized
    return result


def configured_providers(tenant):
    return [p for p, key in [('azure', 'subscription_ids'), ('aws', 'aws_accounts'),
                            ('gcp', 'gcp_projects'), ('kubernetes', 'kubernetes_clusters')] if tenant.get(key)]


def validate_finding_scope(finding, tenant):
    """Validate normalized identity independently at ingestion/export boundaries."""
    provider = finding.get('cloud_provider', 'azure')
    rid, scope = finding.get('resource_id', ''), finding.get('scope_id')
    if provider != 'azure':
        types = {
            'AWS_UNATTACHED_EBS': ('aws', 'aws:ec2:volume'), 'AWS_UNASSOCIATED_EIP': ('aws', 'aws:ec2:elastic-ip'),
            'AWS_IDLE_RDS': ('aws', 'aws:rds:db'), 'GCP_UNATTACHED_DISK': ('gcp', 'compute.googleapis.com/Disk'),
            'GCP_UNASSIGNED_ADDRESS': ('gcp', 'compute.googleapis.com/Address'), 'GCP_IDLE_CLOUD_SQL': ('gcp', 'sqladmin.googleapis.com/Instance'),
            'K8S_CPU_OVERSIZED': ('kubernetes', 'kubernetes.io/Container'), 'K8S_MEMORY_OVERSIZED': ('kubernetes', 'kubernetes.io/Container')}
        if types.get(finding.get('rule_id')) != (provider, finding.get('resource_type')):
            raise ValueError('Finding rule and cloud resource type are inconsistent')
    if provider == 'azure':
        if finding.get('rule_id', '').startswith(('AWS_', 'GCP_', 'K8S_')):
            raise ValueError('Finding rule does not belong to Azure')
        sub = str(UUID(finding['subscription_id']))
        valid = sub in tenant['subscription_ids'] and rid.lower().startswith(f'/subscriptions/{sub}/')
    elif provider == 'aws':
        match = re.fullmatch(r'arn:aws:(ec2|rds):(' + REGION + r'):([0-9]{12}):(volume/vol-[0-9a-f]{8,17}|elastic-ip/eipalloc-[0-9a-f]{8,17}|db:[A-Za-z][A-Za-z0-9-]{0,62})', rid)
        valid = bool(match and scope == match[3] and finding['subscription_id'] == scope
                     and finding.get('region') == match[2]
                     and any(a['account_id'] == scope and a['region'] == match[2] for a in tenant.get('aws_accounts', [])))
        if valid:
            expected_service, expected_prefix = {'AWS_UNATTACHED_EBS': ('ec2', 'volume/'),
                'AWS_UNASSOCIATED_EIP': ('ec2', 'elastic-ip/'), 'AWS_IDLE_RDS': ('rds', 'db:')}[finding['rule_id']]
            valid = match[1] == expected_service and match[4].startswith(expected_prefix)
    elif provider == 'gcp':
        match = re.fullmatch(r'//(compute|sqladmin)\.googleapis\.com/projects/(' + PROJECT + r')/(?:(zones|regions)/(' + NAME + r')/(disks|addresses)/(' + NAME + r')|instances/(' + NAME + r'))', rid)
        valid = bool(match and (match[1] == 'sqladmin') == bool(match[7])
                     and matches(REGION, finding.get('region')) and scope == match[2] and finding['subscription_id'] == scope
                     and scope in {p['project_id'] for p in tenant.get('gcp_projects', [])})
        if valid and match[3] == 'regions':
            valid = match[4] in next(p['regions'] for p in tenant['gcp_projects'] if p['project_id'] == scope)
        if valid:
            expected_kind = {'GCP_UNATTACHED_DISK':'disks', 'GCP_UNASSIGNED_ADDRESS':'addresses', 'GCP_IDLE_CLOUD_SQL':None}[finding['rule_id']]
            valid = match[5] == expected_kind and finding.get('resource_name') == (match[6] or match[7])
            if match[3]:
                expected_region = match[4] if match[3] == 'regions' else match[4].rsplit('-', 1)[0]
                valid = valid and finding['region'] == expected_region
    elif provider == 'kubernetes':
        match = re.fullmatch(r'k8s://(' + NAME + r')/namespaces/(' + NAME + r')/pods/(' + POD_NAME + r')/containers/(' + NAME + r')', rid)
        valid = bool(match and scope == match[1] and finding['subscription_id'] == scope
                     and scope in {c['cluster_id'] for c in tenant.get('kubernetes_clusters', [])})
    else:
        valid = False
    if not valid:
        raise ValueError('Finding is outside the configured cloud scope')
