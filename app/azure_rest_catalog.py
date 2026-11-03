"""Azure public-cloud REST operations used for read-only JSON inventory and cost evidence.

Endpoint shapes follow Microsoft REST reference (ARM, Cost Management, Retail Prices).
"""
from __future__ import annotations

# Stable api-version for subscription provider metadata (Resources — Providers — Get).
PROVIDER_METADATA_API_VERSION = '2022-09-01'

# Cost Management — Query — Usage (subscription scope).
COST_MANAGEMENT_QUERY_API_VERSION = '2023-11-01'

AZURE_REST_CATALOG = {
    'arm_resource_get': {
        'doc': 'https://learn.microsoft.com/en-us/rest/api/resources/resources/get',
        'method': 'GET',
        'host': 'management.azure.com',
        'path': '{resource_id}',
        'query': {'api-version': '{arm_api_version}'},
        'applies_to': 'All Microsoft.* ARM resource IDs returned by Resource Graph.',
    },
    'provider_get': {
        'doc': 'https://learn.microsoft.com/en-us/rest/api/resources/providers/get',
        'method': 'GET',
        'host': 'management.azure.com',
        'path': '/subscriptions/{subscription_id}/providers/{resource_provider_namespace}',
        'query': {'api-version': PROVIDER_METADATA_API_VERSION},
        'applies_to': 'Resolve api-version when resource type is not in the pinned catalog.',
    },
    'cost_management_query': {
        'doc': 'https://learn.microsoft.com/en-us/rest/api/cost-management/query/usage',
        'method': 'POST',
        'host': 'management.azure.com',
        'path': '/subscriptions/{subscription_id}/providers/Microsoft.CostManagement/query',
        'query': {'api-version': COST_MANAGEMENT_QUERY_API_VERSION},
        'body': {
            'type': '{cost_type}',
            'timeframe': 'Custom',
            'timePeriod': {
                'from': '{window_start}T00:00:00Z',
                'to': '{window_end_inclusive}T23:59:59Z',
            },
            'dataset': {
                'granularity': 'Daily',
                'aggregation': {'cost': {'name': 'PreTaxCost', 'function': 'Sum'}},
                'filter': {
                    'dimensions': {
                        'name': 'ResourceId',
                        'operator': 'In',
                        'values': ['{resource_id}'],
                    }
                },
            },
        },
        'applies_to': 'Per-resource ActualCost (billed) and AmortizedCost (effective).',
    },
    'retail_prices': {
        'doc': 'https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices',
        'method': 'GET',
        'host': 'prices.azure.com',
        'path': '/api/retail/prices',
        'query': {'$filter': '{odata_filter}'},
        'applies_to': 'Azure list-price meters (USD catalog); OData JSON response.',
    },
}


def catalog_operations():
    return [
        dict(operation=key, **{k: v for k, v in meta.items() if k != 'body'})
        for key, meta in AZURE_REST_CATALOG.items()
    ]


def parse_arm_resource_type(resource_id: str) -> str | None:
    """Return lowercase ARM type (microsoft.compute/disks) from a resource ID."""
    parts = (resource_id or '').split('/')
    try:
        idx = parts.index('providers')
    except ValueError:
        return None
    if idx + 2 >= len(parts):
        return None
    namespace = parts[idx + 1].lower()
    if not namespace.startswith('microsoft.'):
        return None
    segments = parts[idx + 2 :]
    type_parts = [segments[i].lower() for i in range(0, len(segments), 2)]
    if not type_parts:
        return None
    return f'{namespace}/{'/'.join(type_parts)}'
