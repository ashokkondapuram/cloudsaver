"""Azure Resource Graph inventory queries via documented REST (not the mgmt SDK).

Microsoft Learn: POST /providers/Microsoft.ResourceGraph/resources
https://learn.microsoft.com/en-us/rest/api/azureresourcegraph/resourcegraph/resources/resources

Reliability note (same backend as the Python SDK):
- The SDK is a thin wrapper over this REST API; neither is "more authoritative" for data.
- CloudSaver uses REST here so inventory shares one transport with ARM and Cost Management:
  provider_retry pacing, quota keys, bounded POST bodies, and a single retry policy (see F11).
- The SDK's built-in retries can stack with job-level retries; REST avoids that duplication.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from app.azure_rest_catalog import resource_graph_query_url
from app.collectors.azure_endpoint import ARM_RESOURCE
from app.cloud_http import BearerTokenCache, _json_reader_pacing_interval
from app.provider_retry import read_json
from app.scan_errors import ScanError


def build_query_body(
    query: str,
    subscriptions: list[str],
    *,
    skip_token: str | None = None,
    allow_partial_scopes: bool = False,
) -> dict[str, Any]:
    allowed = sorted({str(UUID(s)) for s in subscriptions})
    options: dict[str, Any] = {
        '$top': 1000,
        'resultFormat': 'objectArray',
        'allowPartialScopes': allow_partial_scopes,
    }
    if skip_token:
        options['$skipToken'] = skip_token
    return {'query': query, 'subscriptions': allowed, 'options': options}


def _post_page(credential, body: dict[str, Any]) -> dict[str, Any]:
    """Single Resource Graph POST; tests patch this hook."""
    url = resource_graph_query_url()
    headers_factory = BearerTokenCache(credential, ARM_RESOURCE)
    headers = dict(headers_factory(url))
    with httpx.Client(timeout=httpx.Timeout(45, connect=10), follow_redirects=False) as client:
        result = read_json(
            client,
            'POST',
            url,
            json=body,
            headers=headers,
            quota_key='azure:resourcegraph',
            interval=_json_reader_pacing_interval(),
            read_only_post=True,
            deadline_seconds=60,
        )
    if not isinstance(result, dict):
        raise ScanError('Azure returned an unexpected inventory format.')
    return result


def execute_pages(credential, query: str, subscriptions: list[str]) -> list[dict]:
    """Fetch every ARG page or fail. Never return a silently incomplete inventory."""
    if not subscriptions:
        raise ScanError('At least one authorized Azure subscription is required.')
    allowed = {str(UUID(s)).lower() for s in subscriptions}
    token = None
    seen_tokens: set[str] = set()
    by_id: dict[str, dict] = {}
    for _ in range(1000):
        body = build_query_body(query, subscriptions, skip_token=token)
        response = _post_page(credential, body)
        if not isinstance(response, dict):
            raise ScanError('Azure returned an unexpected inventory format.')
        rows = response.get('data')
        if not isinstance(rows, list):
            raise ScanError('Azure returned an unexpected inventory format.')
        for row in rows:
            if not isinstance(row, dict):
                raise ScanError('Azure returned a malformed inventory row.')
            subscription = str(row.get('subscriptionId', '')).lower()
            resource_id = row.get('id')
            if subscription not in allowed or not isinstance(resource_id, str):
                raise ScanError('Azure returned a resource outside the authorized scope.')
            if not resource_id.lower().startswith(f'/subscriptions/{subscription}/'):
                raise ScanError('Azure returned an inconsistent resource identifier.')
            for field in ('name', 'type', 'resourceGroup'):
                if not isinstance(row.get(field), str) or not row[field]:
                    raise ScanError('Azure returned a malformed resource identity.')
            by_id[resource_id.lower()] = row
            if len(by_id) > 100_000:
                raise ScanError('Inventory exceeds this MVP scan limit; split the workspace Azure subscriptions.')
        next_token = response.get('$skipToken') or response.get('skipToken')
        truncated_raw = response.get('resultTruncated', False)
        truncated = str(truncated_raw).lower()
        is_truncated = truncated in ('true', 'resulttruncated.true')
        if not next_token:
            if is_truncated:
                raise ScanError('Azure truncated the result without a continuation token.')
            return list(by_id.values())
        if not isinstance(next_token, str) or next_token in seen_tokens:
            raise ScanError('Azure returned an invalid or repeated continuation token.')
        seen_tokens.add(next_token)
        token = next_token
    raise ScanError('Azure inventory exceeded the pagination limit.')
