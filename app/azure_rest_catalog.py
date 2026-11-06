"""Azure public-cloud REST operations used for read-only JSON inventory and cost evidence.

Endpoint shapes follow Microsoft REST reference (ARM, Cost Management, Retail Prices).
"""
from __future__ import annotations

# Stable api-version for subscription provider metadata (Resources — Providers — Get).
PROVIDER_METADATA_API_VERSION = '2022-09-01'

# Cost Management — Query — Usage (subscription scope).
COST_MANAGEMENT_QUERY_API_VERSION = '2023-11-01'

# Azure Monitor — Metrics — List (resource scope).
MONITOR_METRICS_API_VERSION = '2023-10-01'

# Azure Monitor — Metrics — Batch (regional endpoint; prefer when polling many resources).
MONITOR_METRICS_BATCH_API_VERSION = '2024-02-01'

# Monitor — Activity Logs — List (management events).
ACTIVITY_LOG_EVENTS_API_VERSION = '2015-04-01'

# Authorization — Management Locks — List at scope.
AUTHORIZATION_LOCKS_API_VERSION = '2016-09-01'

# Resource Graph — Resources — Resources (tenant inventory query).
RESOURCE_GRAPH_API_VERSION = '2024-04-01'

# Advisor — Recommendations — List (subscription scope).
ADVISOR_RECOMMENDATIONS_API_VERSION = '2023-01-01'

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
    'monitor_metrics_list': {
        'doc': 'https://learn.microsoft.com/en-us/rest/api/monitor/metrics/list',
        'method': 'GET',
        'host': 'management.azure.com',
        'path': '{resource_id}/providers/microsoft.insights/metrics',
        'query': {
            'api-version': MONITOR_METRICS_API_VERSION,
            'timespan': '{start}/{end}',
            'interval': 'PT5M',
            'metricnames': '{metric_name}',
            'aggregation': '{aggregation}',
        },
        'applies_to': 'Azure Monitor platform metrics for live evidence windows.',
    },
    'monitor_metrics_batch': {
        'doc': 'https://learn.microsoft.com/en-us/rest/api/monitor/metrics-batch/batch',
        'method': 'POST',
        'host': '{region}.metrics.monitor.azure.com',
        'path': '/subscriptions/{subscription_id}/metrics:getBatch',
        'query': {'api-version': MONITOR_METRICS_BATCH_API_VERSION},
        'applies_to': 'Batch metrics for up to 50 resources per subscription/region (prefer over N× GET).',
    },
    'activity_log_events': {
        'doc': 'https://learn.microsoft.com/en-us/rest/api/monitor/activity-logs/list',
        'method': 'GET',
        'host': 'management.azure.com',
        'path': '/subscriptions/{subscription_id}/providers/microsoft.insights/eventtypes/management/values',
        'query': {'api-version': ACTIVITY_LOG_EVENTS_API_VERSION, '$filter': '{odata_filter}'},
        'applies_to': 'Resource-scoped management activity for state history.',
    },
    'advisor_recommendations_list': {
        'doc': 'https://learn.microsoft.com/en-us/rest/api/advisor/recommendations/list',
        'method': 'GET',
        'host': 'management.azure.com',
        'path': '/subscriptions/{subscription_id}/providers/Microsoft.Advisor/recommendations',
        'query': {'api-version': ADVISOR_RECOMMENDATIONS_API_VERSION},
        'applies_to': 'Subscription-scoped Azure Advisor recommendations (Stream E).',
    },
    'resource_graph_query': {
        'doc': 'https://learn.microsoft.com/en-us/rest/api/azureresourcegraph/resourcegraph/resources/resources',
        'method': 'POST',
        'host': 'management.azure.com',
        'path': '/providers/Microsoft.ResourceGraph/resources',
        'query': {'api-version': RESOURCE_GRAPH_API_VERSION},
        'body': {
            'query': '{kusto_query}',
            'subscriptions': ['{subscription_id}'],
            'options': {
                '$top': 1000,
                'resultFormat': 'objectArray',
                'allowPartialScopes': False,
                '$skipToken': '{optional_skip_token}',
            },
        },
        'applies_to': 'Workspace inventory and rule queries (same service as azure-mgmt-resourcegraph SDK).',
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
    idx = next((i for i, part in enumerate(parts) if part.lower() == 'providers'), None)
    if idx is None:
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


def cost_management_query_path_lower(subscription_id: str) -> str:
    """Lowercase ARM path for Cost Management query (pagination validation)."""
    from uuid import UUID

    return f'/subscriptions/{str(UUID(subscription_id))}/providers/microsoft.costmanagement/query'


def cost_management_query_url(subscription_id: str) -> str:
    """POST target for Cost Management Query/Usage (Microsoft Learn REST)."""
    from uuid import UUID
    from app.collectors.azure_endpoint import arm_url

    sid = str(UUID(subscription_id))
    return (
        f"{arm_url(f'/subscriptions/{sid}/providers/Microsoft.CostManagement/query')}"
        f"?api-version={COST_MANAGEMENT_QUERY_API_VERSION}"
    )


def provider_metadata_params() -> dict[str, str]:
    return {'api-version': PROVIDER_METADATA_API_VERSION}


def resource_metrics_url(resource_id: str) -> str:
    from app.collectors.azure_endpoint import arm_url

    return arm_url(f'{resource_id}/providers/microsoft.insights/metrics')


def resource_metrics_params(
    *,
    timespan: str,
    metricnames: str,
    aggregation: str,
    interval: str = 'PT5M',
) -> dict[str, str]:
    return {
        'api-version': MONITOR_METRICS_API_VERSION,
        'timespan': timespan,
        'interval': interval,
        'metricnames': metricnames,
        'aggregation': aggregation,
    }


def activity_log_events_url(subscription_id: str) -> str:
    from app.collectors.azure_endpoint import arm_url

    return arm_url(
        f'/subscriptions/{subscription_id}/providers/Microsoft.Insights/eventtypes/management/values'
    )


def retail_prices_base_url() -> str:
    meta = AZURE_REST_CATALOG['retail_prices']
    return f"https://{meta['host']}{meta['path']}"


def resource_graph_query_url() -> str:
    """POST target for Resource Graph Resources/Resources (Microsoft Learn REST)."""
    from app.collectors.azure_endpoint import arm_url

    return arm_url(
        f'/providers/Microsoft.ResourceGraph/resources?api-version={RESOURCE_GRAPH_API_VERSION}'
    )


def advisor_recommendations_url(subscription_id: str) -> str:
    """GET target for Advisor Recommendations/List (Microsoft Learn REST)."""
    from uuid import UUID

    from app.collectors.azure_endpoint import arm_url

    sid = str(UUID(subscription_id))
    return arm_url(f'/subscriptions/{sid}/providers/Microsoft.Advisor/recommendations')


def monitor_metrics_batch_url(region: str, subscription_id: str) -> str:
    """Regional metrics data-plane POST target (Microsoft Learn: metrics:getBatch)."""
    from uuid import UUID

    sid = str(UUID(subscription_id))
    endpoint = (region or '').strip().lower().replace(' ', '')
    if not endpoint:
        raise ValueError('Azure metrics batch requires a resource region')
    return f'https://{endpoint}.metrics.monitor.azure.com/subscriptions/{sid}/metrics:getBatch'
