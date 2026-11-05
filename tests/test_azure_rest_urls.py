from uuid import UUID

from app.azure_rest_catalog import (
    ACTIVITY_LOG_EVENTS_API_VERSION,
    COST_MANAGEMENT_QUERY_API_VERSION,
    MONITOR_METRICS_API_VERSION,
    activity_log_events_url,
    cost_management_query_path_lower,
    cost_management_query_url,
    provider_metadata_params,
    resource_metrics_params,
    resource_metrics_url,
    retail_prices_base_url,
)


SUB = '33333333-3333-4333-8333-333333333333'


def test_cost_management_query_matches_official_shape():
    url = cost_management_query_url(SUB)
    assert url.startswith('https://management.azure.com/subscriptions/')
    assert f'api-version={COST_MANAGEMENT_QUERY_API_VERSION}' in url
    assert url.endswith('/providers/Microsoft.CostManagement/query?api-version=2023-11-01')
    assert cost_management_query_path_lower(SUB) == (
        f'/subscriptions/{SUB}/providers/microsoft.costmanagement/query'
    )


def test_monitor_and_activity_log_urls_use_documented_versions():
    rid = f'/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1'
    metrics = resource_metrics_url(rid)
    assert metrics.endswith('/providers/microsoft.insights/metrics')
    params = resource_metrics_params(timespan='2026-01-01/2026-02-01', metricnames='Percentage CPU', aggregation='Maximum')
    assert params['api-version'] == MONITOR_METRICS_API_VERSION
    assert activity_log_events_url(SUB).endswith('/eventtypes/management/values')
    assert provider_metadata_params()['api-version'] == '2022-09-01'
    assert ACTIVITY_LOG_EVENTS_API_VERSION == '2015-04-01'
    assert retail_prices_base_url() == 'https://prices.azure.com/api/retail/prices'
