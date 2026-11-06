"""Optional AWS Resource Explorer 2 inventory (Search API).

IAM (customer reader role): ``resource-explorer-2:Search`` on the account default
view in each scanned Region; index creation is a customer prerequisite.
https://docs.aws.amazon.com/resource-explorer/latest/userguide/security_iam_id-based-policy-examples.html

Enabled when ``CLOUDSAVER_AWS_RESOURCE_EXPLORER=true`` (or platform
``aws_resource_explorer_enabled``).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.cloudsaver_platform_settings import integration_flag

# Resource Explorer ``ResourceType`` values that differ from CloudSaver catalog ids.
_TYPE_ALIASES: dict[str, str] = {
    'elasticloadbalancing:loadbalancer': 'aws:elbv2:loadbalancer',
}


def enabled(settings=None) -> bool:
    return integration_flag(
        settings,
        'aws_resource_explorer_enabled',
        'CLOUDSAVER_AWS_RESOURCE_EXPLORER',
    )


def merge_by_arn(primary: list[dict], supplemental: list[dict]) -> list[dict]:
    """Keep detailed API rows; append Resource Explorer rows for unseen ARNs."""
    seen = {row['resource_id'] for row in primary if row.get('resource_id')}
    merged = list(primary)
    for row in supplemental:
        rid = row.get('resource_id')
        if not rid or rid in seen:
            continue
        merged.append(row)
        seen.add(rid)
    return merged


def _catalog_type(resource_type: str, arn: str) -> str:
    alias = _TYPE_ALIASES.get(resource_type or '')
    if alias:
        return alias
    if ':' in resource_type:
        service, suffix = resource_type.split(':', 1)
        return f'aws:{service}:{suffix}'
    return f'aws:unknown:{resource_type or "resource"}'


def _resource_name(arn: str) -> str:
    if arn.startswith('arn:aws:s3:::'):
        return arn.split(':::')[-1]
    if '/' in arn:
        return arn.rsplit('/', 1)[-1]
    return arn.split(':')[-1]


def _in_scope(arn: str, account: str, region: str, *, reported_region: str | None) -> bool:
    if not arn.startswith('arn:aws:'):
        return False
    if arn.startswith('arn:aws:s3:::'):
        bucket_region = reported_region or 'us-east-1'
        if bucket_region == 'EU':
            bucket_region = 'eu-west-1'
        return bucket_region == region
    parts = arn.split(':')
    return len(parts) >= 6 and parts[4] == account and parts[3] == region


def _search_pages(explorer, *, query: str):
    token = None
    seen: set[str] = set()
    count = 0
    for _ in range(200):
        kwargs = {'QueryString': query, 'MaxResults': 1000}
        if token:
            kwargs['NextToken'] = token
        response = explorer.search(**kwargs)
        resources = response.get('Resources')
        if not isinstance(resources, list):
            raise ValueError('Malformed AWS Resource Explorer response')
        count += len(resources)
        if count > 20000:
            raise ValueError('AWS Resource Explorer inventory bound exceeded')
        yield from resources
        token = response.get('NextToken')
        if not token:
            return
        if not isinstance(token, str) or token in seen:
            raise ValueError('Repeated AWS Resource Explorer continuation')
        seen.add(token)
    raise ValueError('AWS Resource Explorer page bound exceeded')


def inventory_rows(client, account: str, region: str, *, now: datetime | None = None) -> list[dict]:
    """Search the Regional index and emit canonical inventory observations."""
    if not enabled():
        return []
    now = now or datetime.now(timezone.utc)
    explorer = client('resource-explorer-2')
    query = f'region:{region}'
    rows: list[dict] = []
    for item in _search_pages(explorer, query=query):
        if not isinstance(item, dict):
            raise ValueError('Malformed AWS Resource Explorer row')
        arn = item.get('Arn')
        resource_type = item.get('ResourceType')
        if not isinstance(arn, str) or not isinstance(resource_type, str):
            continue
        reported_region = item.get('Region') if isinstance(item.get('Region'), str) else None
        if not _in_scope(arn, account, region, reported_region=reported_region):
            continue
        kind = _catalog_type(resource_type, arn)
        name = _resource_name(arn)
        evidence = {
            'source': 'AWS Resource Explorer 2',
            'aws_resource_type': resource_type,
            'aws_service': item.get('Service'),
            'last_reported_at': str(item.get('LastReportedAt')) if item.get('LastReportedAt') else None,
        }
        rows.append(
            dict(
                cloud_provider='aws',
                scope_id=account,
                subscription_id=account,
                region=region,
                resource_id=arn,
                resource_name=name,
                resource_group=region,
                resource_type=kind,
                inventory_rule_id='MULTICLOUD_INVENTORY',
                evidence=evidence,
                dependency_refs=[],
                collector_version='aws-resource-explorer-1.0.0',
                observed_at=now.isoformat(),
            )
        )
    return rows
