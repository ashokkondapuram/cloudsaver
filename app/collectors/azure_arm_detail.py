"""Fetch full Azure ARM resource documents (read-only GET) for every Microsoft.* inventory row."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from app.azure_resource_registry import normalize_arm_body, resolve_arm_api_version
from app.collectors.azure_endpoint import arm_url, validate_arm_resource_path
from app.collectors.live_common import collect
from app.collectors.azure_configuration_evidence import enrich_configuration_evidence

logger = logging.getLogger('cloudsaver.scanner')


def enabled(settings=None) -> bool:
    from app.cloudsaver_platform_settings import integration_flag
    return integration_flag(settings, 'azure_arm_detail_enabled', 'CLOUDSAVER_AZURE_ARM_DETAIL_ENABLED', default='true')


def _max_resources(settings=None) -> int | None:
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


def enrich_arm_details(reader, inventory, *, now=None, settings=None, progress=None):
    """Attach full ARM-normalized configuration to inventory rows (mutates list)."""
    now = now or datetime.now(timezone.utc)
    limit = _max_resources(settings)
    fetched = 0
    version_cache: dict = {}
    total = len(inventory)
    logger.info('ARM detail enrichment starting resources=%s max=%s', total, limit or 'all')
    for index, resource in enumerate(inventory, start=1):
        if index == 1 or index % 250 == 0 or index == total:
            logger.info('ARM detail progress %s/%s fetched=%s', index, total, fetched)
        if not _azure_arm_resource(resource):
            resource.setdefault('evidence', {})['arm_detail'] = 'unsupported_type'
            enrich_configuration_evidence(resource)
            if progress is not None:
                progress.record_observation(resource)
            continue
        if limit is not None and fetched >= limit:
            resource.setdefault('evidence', {})['arm_detail'] = 'resource_budget_exceeded'
            enrich_configuration_evidence(resource)
            if progress is not None:
                progress.record_observation(resource)
            continue
        rtype = resource['resource_type']
        subscription_id = resource['subscription_id']
        version = resolve_arm_api_version(reader, subscription_id, rtype, version_cache)
        if not version:
            resource.setdefault('evidence', {})['arm_detail'] = 'api_version_unresolved'
            enrich_configuration_evidence(resource)
            if progress is not None:
                progress.record_observation(resource)
            continue
        rid = resource['resource_id']
        scope = rid.split('/providers/')[0].lower()
        def load():
            validate_arm_resource_path(rid, scope_path_lower=scope)
            body = reader.get(arm_url(rid), {'api-version': version})
            if (body.get('id') or '').lower() != rid.lower():
                raise ValueError('ARM resource id mismatch')
            return normalize_arm_body(body)

        evidence = resource.setdefault('evidence', {})
        detail = collect(evidence, 'arm_resource', load)
        if detail:
            evidence['typed_configuration'] = detail.get('typed_configuration')
            evidence['arm_provisioning_state'] = detail.get('provisioning_state')
            evidence['arm_sku'] = detail.get('sku')
            evidence['arm_document'] = detail
            evidence['arm_detail'] = 'collected'
            evidence['arm_api_version'] = version
            evidence['arm_fetched_at'] = now.isoformat().replace('+00:00', 'Z')
            fetched += 1
        else:
            evidence['arm_detail'] = 'fetch_failed'
        enrich_configuration_evidence(resource)
        if progress is not None:
            progress.record_observation(resource)
    return inventory
