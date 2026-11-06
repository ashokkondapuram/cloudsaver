"""Fetch full Azure ARM resource documents (read-only GET) for every Microsoft.* inventory row."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.azure_resource_registry import normalize_arm_body, resolve_arm_api_version
from app.collectors.azure_endpoint import arm_url, validate_arm_resource_path
from app.collectors.live_common import collect
from app.collectors.azure_configuration_evidence import enrich_configuration_evidence

logger = logging.getLogger('cloudsaver.scanner')


def enabled(settings=None) -> bool:
    from app.cloudsaver_platform_settings import integration_flag
    return integration_flag(settings, 'azure_arm_detail_enabled', 'CLOUDSAVER_AZURE_ARM_DETAIL_ENABLED', default='true')


def _max_attempts(settings=None) -> int | None:
    """Maximum ARM HTTP attempts (metadata + resource GET), not successful rows."""
    from app.cloudsaver_platform_settings import integration_int
    value = integration_int(settings, 'azure_arm_detail_max', 'CLOUDSAVER_AZURE_ARM_DETAIL_MAX', default=0)
    if value == 0:
        return None
    if not 1 <= value <= 50000:
        raise ValueError('ARM detail bound must be 0 (all resources) or 1–50000')
    return value


def _azure_arm_resource(resource: dict) -> bool:
    rtype = (resource.get('resource_type') or '').lower()
    rid = (resource.get('resource_id') or '').lower()
    return rtype.startswith('microsoft.') and '/providers/' in rid


def _attempt_budget_exceeded(attempt_budget: int | None, stats: dict) -> bool:
    return attempt_budget is not None and stats['attempted'] >= attempt_budget


def enrich_arm_detail_row(
    reader,
    resource,
    *,
    now=None,
    settings=None,
    stats=None,
    version_cache=None,
    progress=None,
):
    """ARM GET for one inventory row."""
    now = now or datetime.now(timezone.utc)
    attempt_budget = _max_attempts(settings)
    stats = stats if stats is not None else dict(attempted=0, succeeded=0, failed=0, not_attempted=0)
    version_cache = version_cache if version_cache is not None else {}
    evidence = resource.setdefault('evidence', {})
    if not _azure_arm_resource(resource):
        evidence['arm_detail'] = 'unsupported_type'
        stats['not_attempted'] += 1
        enrich_configuration_evidence(resource)
        if progress is not None:
            progress.record_observation(resource)
        return resource
    if _attempt_budget_exceeded(attempt_budget, stats):
        evidence['arm_detail'] = 'resource_budget_exceeded'
        stats['not_attempted'] += 1
        enrich_configuration_evidence(resource)
        if progress is not None:
            progress.record_observation(resource)
        return resource

    outcome: dict[str, str | None] = {'detail': None, 'version': None, 'fetched_at': None}

    def load():
        stats['attempted'] += 1
        try:
            rtype = (resource.get('resource_type') or '').lower()
            subscription_id = resource['subscription_id']
            version = resolve_arm_api_version(reader, subscription_id, rtype, version_cache)
            if not version:
                outcome['error'] = 'api_version_unresolved'
                raise ValueError('api_version_unresolved')
            rid = resource['resource_id']
            scope = rid.split('/providers/')[0].lower()
            validate_arm_resource_path(rid, scope_path_lower=scope)
            body = reader.get(arm_url(rid), {'api-version': version})
            if (body.get('id') or '').lower() != rid.lower():
                raise ValueError('ARM resource id mismatch')
            outcome['version'] = version
            outcome['fetched_at'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            return normalize_arm_body(body)
        except Exception as error:
            if outcome.get('error') is None:
                outcome['error'] = 'api_version_unresolved' if str(error) == 'api_version_unresolved' else 'fetch_failed'
            raise

    detail = collect(evidence, 'arm_resource', load)
    if detail:
        stats['succeeded'] += 1
        evidence['typed_configuration'] = detail.get('typed_configuration')
        evidence['arm_provisioning_state'] = detail.get('provisioning_state')
        evidence['arm_sku'] = detail.get('sku')
        evidence['arm_document'] = detail
        evidence['arm_detail'] = 'collected'
        evidence['arm_api_version'] = outcome['version']
        evidence['arm_fetched_at'] = outcome['fetched_at']
    else:
        stats['failed'] += 1
        evidence['arm_detail'] = outcome.get('error') or 'fetch_failed'
    enrich_configuration_evidence(resource)
    from app.resource_timestamps import touch_azure_status_fetched

    touch_azure_status_fetched(evidence, now=now)
    if progress is not None:
        progress.record_observation(resource)
    return resource


def enrich_arm_details(reader, inventory, *, now=None, settings=None, progress=None):
    """Attach full ARM-normalized configuration to inventory rows (mutates list)."""
    now = now or datetime.now(timezone.utc)
    attempt_budget = _max_attempts(settings)
    stats = dict(attempted=0, succeeded=0, failed=0, not_attempted=0)
    version_cache: dict = {}
    total = len(inventory)
    logger.info('ARM detail enrichment starting resources=%s attempt_budget=%s', total, attempt_budget or 'all')
    for index, resource in enumerate(inventory, start=1):
        if index == 1 or index % 250 == 0 or index == total:
            logger.info(
                'ARM detail progress %s/%s attempted=%s succeeded=%s',
                index,
                total,
                stats['attempted'],
                stats['succeeded'],
            )
        enrich_arm_detail_row(
            reader,
            resource,
            now=now,
            settings=settings,
            stats=stats,
            version_cache=version_cache,
            progress=progress,
        )
    logger.info('ARM detail enrichment finished stats=%s', stats)
    return inventory
