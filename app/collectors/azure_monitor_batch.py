"""Azure Monitor metrics:getBatch for live enrichment at subscription/region scale."""
from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from app.azure_rest_catalog import MONITOR_METRICS_BATCH_API_VERSION, monitor_metrics_batch_url
from app.cloud_http import JSONReader, _json_reader_pacing_interval
from app.collectors.azure_live import METRICS, _AZURE_AGG_VALUE, _series_from_platform_metric
from app.collectors.live_common import window
from app.provider_retry import read_json


BATCH_GROUP_MIN_SIZE = 11  # use batch when more than 10 resources share sub+region+type
MAX_RESOURCES_PER_BATCH = 50


def _resource_region(resource: dict) -> str | None:
    region = resource.get('region')
    if isinstance(region, str) and region.strip():
        return region.strip()
    return None


def batch_group_key(resource: dict) -> tuple[str, str, str] | None:
    region = _resource_region(resource)
    if region is None:
        return None
    try:
        sub = str(UUID(resource['subscription_id']))
    except (ValueError, TypeError, KeyError):
        return None
    rtype = resource.get('resource_type')
    if not isinstance(rtype, str) or not rtype.strip():
        return None
    return sub.lower(), region.lower(), rtype.lower()


def _metric_specs(resource_type: str) -> list[tuple[str, str, str]]:
    specs: list[tuple[str, str, str]] = []
    for key, spec in METRICS.get(resource_type.lower(), {}).items():
        name, aggregation = spec if isinstance(spec, tuple) else (spec, 'Maximum')
        specs.append((key, name, aggregation))
    return specs


def _parse_batch_response(payload: dict, *, resource_type: str, now) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    values = payload.get('values')
    if not isinstance(values, list):
        return by_id
    name_to_key = {name: key for key, name, _ in _metric_specs(resource_type)}
    for entry in values:
        if not isinstance(entry, dict):
            continue
        rid = entry.get('resourceid') or entry.get('resourceId')
        if not isinstance(rid, str) or not rid:
            continue
        bucket = by_id.setdefault(rid.lower(), {})
        metrics = entry.get('value')
        if not isinstance(metrics, list):
            continue
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            azure_name = (metric.get('name') or {}).get('value')
            if not isinstance(azure_name, str):
                continue
            key = name_to_key.get(azure_name)
            if key is None:
                continue
            _, _, aggregation = next(item for item in _metric_specs(resource_type) if item[0] == key)
            parsed = _series_from_platform_metric(
                metric,
                name=azure_name,
                aggregation=aggregation,
                now=now,
            )
            if parsed is not None:
                bucket[key] = parsed
    return by_id


def _post_batch(
    reader,
    *,
    subscription_id: str,
    region: str,
    resource_type: str,
    resource_ids: list[str],
    metric_name: str,
    aggregation: str,
    now,
) -> dict[str, Any]:
    start, end = window(now)
    url = monitor_metrics_batch_url(region, subscription_id)
    params = {
        'api-version': MONITOR_METRICS_BATCH_API_VERSION,
        'starttime': start.isoformat(),
        'endtime': end.isoformat(),
        'interval': 'PT5M',
        'metricNamespace': resource_type.lower(),
        'metricnames': metric_name,
        'aggregation': _AZURE_AGG_VALUE.get(aggregation, aggregation.lower()),
    }
    body = {'resourceids': list(resource_ids)}
    headers_factory = reader.headers_factory
    if headers_factory is None:
        raise ValueError('Azure metrics batch requires a bearer token factory')
    headers = dict(headers_factory(url))
    return read_json(
        reader.client,
        'POST',
        url,
        params=params,
        json=body,
        headers=headers,
        quota_key=JSONReader.quota_key(url),
        interval=_json_reader_pacing_interval(),
        read_only_post=True,
    )


def prefetch_batch_metrics(reader, resources: list[dict], now) -> dict[str, dict]:
    """Fetch metrics:getBatch results for large same-region groups; map resource_id.lower() -> series dict."""
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for resource in resources:
        key = batch_group_key(resource)
        if key is None:
            continue
        groups[key].append(resource)
    cache: dict[str, dict] = {}
    for key, members in groups.items():
        if len(members) < BATCH_GROUP_MIN_SIZE:
            continue
        sub, region, resource_type = key
        for offset in range(0, len(members), MAX_RESOURCES_PER_BATCH):
            chunk = members[offset : offset + MAX_RESOURCES_PER_BATCH]
            ids = [member['resource_id'] for member in chunk]
            merged: dict[str, dict] = {rid.lower(): {} for rid in ids}
            for _key, metric_name, aggregation in _metric_specs(resource_type):
                try:
                    payload = _post_batch(
                        reader,
                        subscription_id=sub,
                        region=region,
                        resource_type=resource_type,
                        resource_ids=ids,
                        metric_name=metric_name,
                        aggregation=aggregation,
                        now=now,
                    )
                except Exception:
                    merged = {}
                    break
                parsed = _parse_batch_response(payload, resource_type=resource_type, now=now)
                for rid, metrics in parsed.items():
                    if rid in merged:
                        merged[rid].update(metrics)
            if not merged:
                continue
            for rid, metrics in merged.items():
                if metrics:
                    cache[rid] = metrics
    return cache
