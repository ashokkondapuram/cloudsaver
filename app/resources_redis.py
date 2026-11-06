"""Redis copy of scan resources until Postgres inventory reads catch up."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from app.assessment_policy import timestamp

logger = logging.getLogger('cloudsaver.resources_redis')

TTL_SECONDS = int(
    os.getenv(
        'CLOUDSAVER_RESOURCES_REDIS_TTL_SECONDS',
        os.getenv('CLOUDSAVER_RESOURCE_CACHE_TTL_SECONDS', '900'),
    )
)
KEY_PREFIX = 'cloudsaver:resources:v1:'


def _redis_url() -> str:
    return (os.getenv('REDIS_URL') or '').strip()


def _iso(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.isoformat().replace('+00:00', 'Z')


def redis_key(tenant_id: str, scan_id: str, provider: str, resource_id: str) -> str:
    rid = (resource_id or '').lower()
    provider = provider or 'azure'
    return f'{KEY_PREFIX}{tenant_id}:{scan_id}:{provider}:{rid}'


def _db_resource_updated(observation: dict | None) -> datetime | None:
    if not observation:
        return None
    ev = observation.get('evidence') or {}
    stamps = [
        timestamp(ev.get('last_analyzed_at')),
        timestamp(ev.get('azure_status_fetched_at')),
        timestamp(observation.get('observed_at')),
    ]
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


def redis_is_newer(cached: dict | None, observation: dict | None) -> bool:
    if not cached:
        return False
    resource = cached.get('resource') or cached.get('observation') or {}
    if not resource:
        return False
    if cached.get('refresh_in_progress'):
        return True
    cache_at = timestamp(cached.get('updated_at')) or _db_resource_updated(resource)
    db_at = _db_resource_updated(observation)
    if cache_at is None:
        return False
    if db_at is None:
        return True
    return cache_at >= db_at


def _resource_from_cached(cached: dict | None) -> dict | None:
    if not cached:
        return None
    resource = cached.get('resource') or cached.get('observation')
    return dict(resource) if resource else None


def put_scan_resource(
    tenant_id: str,
    scan_id: str,
    resource: dict,
    *,
    findings: list[dict] | None = None,
    evaluations: list[dict] | None = None,
    refresh_in_progress: bool = False,
) -> None:
    url = _redis_url()
    if not url or not resource.get('resource_id'):
        return
    provider = resource.get('cloud_provider', 'azure')
    payload = {
        'resource': resource,
        'findings': list(findings) if findings is not None else None,
        'evaluations': list(evaluations) if evaluations is not None else None,
        'updated_at': _iso(),
        'refresh_in_progress': refresh_in_progress,
    }
    key = redis_key(tenant_id, scan_id, provider, resource['resource_id'])
    try:
        import redis

        client = redis.from_url(url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)
        with client:
            client.set(key, json.dumps(payload, separators=(',', ':'), default=str), ex=TTL_SECONDS)
    except Exception:
        logger.debug('Resources redis write failed key=%s', key, exc_info=True)


def get_scan_resource(tenant_id: str, scan_id: str, provider: str, resource_id: str) -> dict | None:
    url = _redis_url()
    if not url or not resource_id:
        return None
    key = redis_key(tenant_id, scan_id, provider or 'azure', resource_id)
    try:
        import redis

        client = redis.from_url(url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)
        with client:
            raw = client.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        logger.debug('Resources redis read failed key=%s', key, exc_info=True)
        return None


def _fetch_cached_by_observations(tenant_id: str, scan_id: str, observations: list[dict]) -> list[dict | None]:
    if not observations or not _redis_url():
        return [None] * len(observations)
    url = _redis_url()
    keys = [
        redis_key(tenant_id, scan_id, obs.get('cloud_provider', 'azure'), obs.get('resource_id') or '')
        for obs in observations
    ]
    try:
        import redis

        client = redis.from_url(url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)
        with client:
            values = client.mget(keys) if keys else []
        out: list[dict | None] = []
        for raw in values:
            if not raw:
                out.append(None)
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                out.append(None)
        return out
    except Exception:
        logger.debug('Resources redis mget failed scan_id=%s', scan_id, exc_info=True)
        return [None] * len(observations)


def apply_scan_resources_page(
    tenant_id: str,
    scan_id: str,
    observations: list[dict],
    findings_by_key: dict[str, list[dict]],
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Prefer Redis resource rows over DB inventory for one page."""
    from app.resource_assessment import inventory_observation, resource_key

    if not observations:
        return observations, findings_by_key
    findings_by_key = dict(findings_by_key)
    cached_rows = _fetch_cached_by_observations(tenant_id, scan_id, observations)
    merged_obs: list[dict] = []
    for obs, cached in zip(observations, cached_rows):
        if not redis_is_newer(cached, obs):
            merged_obs.append(obs)
            continue
        resource = _resource_from_cached(cached)
        if not resource:
            merged_obs.append(obs)
            continue
        merged_obs.append(resource)
        if cached and cached.get('findings') is not None:
            key = resource_key(inventory_observation(resource))
            cached_findings = list(cached['findings'])
            if cached_findings:
                findings_by_key[key] = cached_findings
            else:
                findings_by_key.pop(key, None)
    return merged_obs, findings_by_key


def apply_scan_resource(
    tenant_id: str,
    scan_id: str,
    resource: dict | None,
) -> dict | None:
    if not resource:
        return resource
    cached = get_scan_resource(
        tenant_id,
        scan_id,
        resource.get('cloud_provider', 'azure'),
        resource.get('resource_id') or '',
    )
    if not redis_is_newer(cached, resource):
        return resource
    return _resource_from_cached(cached) or resource


def apply_scan_resource_bundle(
    tenant_id: str,
    scan_id: str,
    resource: dict | None,
    findings: list[dict],
) -> tuple[dict | None, list[dict]]:
    if not resource:
        return resource, findings
    cached = get_scan_resource(
        tenant_id,
        scan_id,
        resource.get('cloud_provider', 'azure'),
        resource.get('resource_id') or '',
    )
    if not redis_is_newer(cached, resource):
        return resource, findings
    merged = _resource_from_cached(cached) or resource
    out_findings = findings
    if cached and cached.get('findings') is not None:
        out_findings = list(cached['findings'])
    return merged, out_findings


def apply_scan_inventory_map(
    tenant_id: str,
    scan_id: str,
    inventory_by_key: dict[str, dict],
    findings_by_key: dict[str, list[dict]],
) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Overlay Redis resources onto an in-memory inventory map."""
    from app.resource_assessment import inventory_observation, resource_key

    if not inventory_by_key or not _redis_url():
        return inventory_by_key, findings_by_key
    observations = list(inventory_by_key.values())
    keys = list(inventory_by_key.keys())
    cached_rows = _fetch_cached_by_observations(tenant_id, scan_id, observations)
    inventory_by_key = dict(inventory_by_key)
    findings_by_key = dict(findings_by_key)
    for key, obs, cached in zip(keys, observations, cached_rows):
        if not redis_is_newer(cached, obs):
            continue
        resource = _resource_from_cached(cached)
        if not resource:
            continue
        inventory_by_key[key] = resource
        if cached and cached.get('findings') is not None:
            cached_findings = list(cached['findings'])
            if cached_findings:
                findings_by_key[key] = cached_findings
            else:
                findings_by_key.pop(key, None)
    return inventory_by_key, findings_by_key
