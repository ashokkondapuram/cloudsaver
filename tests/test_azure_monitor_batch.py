"""Azure Monitor metrics:getBatch live enrichment."""
from datetime import datetime, timedelta, timezone

import pytest

from app.azure_rest_catalog import monitor_metrics_batch_url
from app.collectors.azure_live import enrich
from app.collectors.azure_monitor_batch import (
    BATCH_GROUP_MIN_SIZE,
    MAX_RESOURCES_PER_BATCH,
    batch_group_key,
    prefetch_batch_metrics,
)
from app.collectors.live_common import window

SUB = '33333333-3333-4333-8333-333333333333'
NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)
NOW -= timedelta(minutes=NOW.minute % 5)


def _disk_resource(index: int, *, region: str = 'eastus') -> dict:
    return dict(
        cloud_provider='azure',
        subscription_id=SUB,
        resource_id=f'/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Compute/disks/d{index}',
        resource_type='microsoft.compute/disks',
        resource_group='rg',
        region=region,
        evidence={},
    )


def _batch_metric_payload(resource_id: str, *, metric_name: str, aggregation: str, value: float):
    agg_key = aggregation.lower()
    start, end = window(NOW)
    return {
        'starttime': start.isoformat(),
        'endtime': end.isoformat(),
        'interval': 'PT5M',
        'namespace': 'microsoft.compute/disks',
        'resourceid': resource_id,
        'value': [
            {
                'name': {'value': metric_name},
                'errorCode': 'Success',
                'timeseries': [
                    {
                        'metadatavalues': [],
                        'data': [{'timeStamp': start.isoformat(), agg_key: value}],
                    }
                ],
            }
        ],
    }


def test_monitor_metrics_batch_url_uses_regional_endpoint():
    url = monitor_metrics_batch_url('East US', SUB)
    assert url == (
        f'https://eastus.metrics.monitor.azure.com/subscriptions/{SUB}/metrics:getBatch'
    )


def test_batch_group_key_requires_region():
    resource = _disk_resource(1)
    resource.pop('region')
    assert batch_group_key(resource) is None


def test_prefetch_uses_batch_when_group_exceeds_ten(monkeypatch):
    calls = []

    def fake_post_batch(reader, **kwargs):
        calls.append(kwargs)
        return {
            'values': [
                _batch_metric_payload(
                    rid,
                    metric_name=kwargs['metric_name'],
                    aggregation=kwargs['aggregation'],
                    value=12.0,
                )
                for rid in kwargs['resource_ids']
            ]
        }

    monkeypatch.setattr('app.collectors.azure_monitor_batch._post_batch', fake_post_batch)
    resources = [_disk_resource(i) for i in range(BATCH_GROUP_MIN_SIZE)]
    reader = object()
    cache = prefetch_batch_metrics(reader, resources, NOW)
    assert len(cache) == BATCH_GROUP_MIN_SIZE
    assert calls
    assert calls[0]['resource_ids'] == [resource['resource_id'] for resource in resources]
    assert calls[0]['resource_type'] == 'microsoft.compute/disks'
    assert len(calls[0]['resource_ids']) <= MAX_RESOURCES_PER_BATCH
    assert all(call['subscription_id'] == SUB.lower() for call in calls)


def test_prefetch_skips_small_groups(monkeypatch):
    monkeypatch.setattr(
        'app.collectors.azure_monitor_batch._post_batch',
        lambda *args, **kwargs: pytest.fail('batch should not run'),
    )
    resources = [_disk_resource(i) for i in range(BATCH_GROUP_MIN_SIZE - 1)]
    assert prefetch_batch_metrics(object(), resources, NOW) == {}


def test_enrich_uses_batch_cache_for_large_groups(monkeypatch):
    batch_calls = []
    get_calls = []

    def fake_post_batch(reader, **kwargs):
        batch_calls.append(kwargs)
        return {
            'values': [
                _batch_metric_payload(
                    rid,
                    metric_name=kwargs['metric_name'],
                    aggregation=kwargs['aggregation'],
                    value=5.0,
                )
                for rid in kwargs['resource_ids']
            ]
        }

    class Reader:
        def get(self, url, params=None):
            get_calls.append((url, params))
            return {'value': []}

    monkeypatch.setattr('app.collectors.azure_monitor_batch._post_batch', fake_post_batch)
    monkeypatch.setattr(
        'app.collectors.azure_live.fetch_backup_replication',
        lambda *args, **kwargs: (set(), set()),
    )
    monkeypatch.setattr(
        'app.collectors.azure_live.fetch_azure_operational_guards',
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        'app.collectors.azure_live.fetch_azure_state_history',
        lambda *args, **kwargs: None,
    )
    inventory = [_disk_resource(i) for i in range(BATCH_GROUP_MIN_SIZE)]
    enrich(Reader(), inventory, now=NOW, settings={'integrations': {'live_evidence_max_resources': 0}})
    assert batch_calls
    assert not get_calls


def test_enrich_falls_back_to_get_for_small_groups(monkeypatch):
    monkeypatch.setattr(
        'app.collectors.azure_monitor_batch._post_batch',
        lambda *args, **kwargs: pytest.fail('batch should not run'),
    )
    get_calls = []

    class Reader:
        def get(self, url, params=None):
            get_calls.append((url, params))
            start, end = window(NOW)
            return {
                'value': [
                    {
                        'name': {'value': 'Composite Disk Read Operations/sec'},
                        'errorCode': 'Success',
                        'timeseries': [
                            {
                                'metadatavalues': [],
                                'data': [{'timeStamp': start.isoformat(), 'maximum': 1.0}],
                            }
                        ],
                    }
                ]
            }

    monkeypatch.setattr(
        'app.collectors.azure_live.fetch_backup_replication',
        lambda *args, **kwargs: (set(), set()),
    )
    monkeypatch.setattr(
        'app.collectors.azure_live.fetch_azure_operational_guards',
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        'app.collectors.azure_live.fetch_azure_state_history',
        lambda *args, **kwargs: None,
    )
    inventory = [_disk_resource(0)]
    enrich(Reader(), inventory, now=NOW, settings={'integrations': {'live_evidence_max_resources': 0}})
    assert get_calls
    assert inventory[0]['evidence'].get('metrics')
