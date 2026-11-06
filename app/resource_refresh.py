"""Refresh one resource in a saved scan when analysis is stale."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from app.resource_timestamps import evidence_needs_refresh

logger = logging.getLogger('cloudsaver.resource_refresh')

AUTO_REFRESH = os.getenv('CLOUDSAVER_RESOURCE_AUTO_REFRESH', 'true').lower() == 'true'


def _arg_findings_for_scan(scan: dict, resource_id: str) -> list[dict]:
    rid = resource_id.lower()
    return [
        f
        for f in scan.get('findings') or []
        if isinstance(f.get('resource_id'), str) and f['resource_id'].lower() == rid
    ]


def refresh_resource_observation(
    tenant: dict,
    scan: dict,
    observation: dict,
    *,
    store,
    policies: dict | None = None,
) -> tuple[dict, list[dict]]:
    """Fetch current Azure status and re-analyze one resource; persist into the scan payload."""
    from app.cloud_identity import CredentialError, azure_credential
    from app.cloud_http import BearerTokenCache, JSONReader
    from app.collectors.resource_pipeline import enrich_single_resource
    from app.config import Settings

    settings = Settings.load()
    subscriptions = [str(s) for s in tenant.get('subscription_ids') or []]
    if not subscriptions:
        raise ValueError('No authorized Azure subscriptions are configured.')
    try:
        credential = azure_credential(tenant)
    except CredentialError as exc:
        raise ValueError(str(exc) or 'Azure credential is unavailable.') from exc

    resource = dict(observation)
    arg_findings = _arg_findings_for_scan(scan, resource['resource_id'])
    stamp = scan.get('timestamp')
    now = datetime.now(timezone.utc)
    tenant_id = tenant['tenant_id']
    scan_id = scan['scan_id']

    from app.resources_redis import put_scan_resource
    from app.resource_fetch_stages import set_stage

    evidence = resource.setdefault('evidence', {})
    set_stage(evidence, 'analysis', 'running')
    put_scan_resource(
        tenant_id,
        scan_id,
        resource,
        refresh_in_progress=True,
    )

    with credential:
        arm_auth = BearerTokenCache(credential, 'https://management.azure.com/.default')
        reader = JSONReader(headers_factory=arm_auth)
        try:
            analysis = enrich_single_resource(
                reader,
                resource,
                settings=settings,
                arg_findings=arg_findings,
                policies=policies,
                observed_at=stamp,
                now=now,
            )
        finally:
            reader.close()

    put_scan_resource(
        tenant_id,
        scan_id,
        resource,
        findings=analysis['findings'],
        evaluations=analysis['evaluations'],
        refresh_in_progress=True,
    )

    if hasattr(store, 'upsert_running_scan_resource'):
        store.upsert_running_scan_resource(
            tenant['tenant_id'],
            scan['scan_id'],
            resource,
            workspace=tenant,
            observed_at=stamp or now.isoformat().replace('+00:00', 'Z'),
            findings=analysis['findings'],
            evaluations=analysis['evaluations'],
        )
    elif hasattr(store, 'upsert_inventory_observation'):
        store.upsert_inventory_observation(
            tenant['tenant_id'],
            scan['scan_id'],
            resource,
            workspace=tenant,
            observed_at=stamp or now.isoformat().replace('+00:00', 'Z'),
        )

    put_scan_resource(
        tenant_id,
        scan_id,
        resource,
        findings=analysis['findings'],
        evaluations=analysis['evaluations'],
        refresh_in_progress=False,
    )

    logger.info(
        'Refreshed resource resource_id=%s scan_id=%s findings=%s',
        resource.get('resource_id'),
        scan.get('scan_id'),
        len(analysis['findings']),
    )
    return resource, analysis['findings']


def maybe_refresh_observation(
    tenant: dict,
    scan: dict,
    observation: dict | None,
    *,
    store,
    policies: dict | None = None,
) -> dict | None:
    if not observation or not AUTO_REFRESH:
        return observation
    from app.resources_redis import apply_scan_resource, get_scan_resource

    cached = get_scan_resource(
        tenant['tenant_id'],
        scan['scan_id'],
        observation.get('cloud_provider', 'azure'),
        observation.get('resource_id') or '',
    )
    if cached and cached.get('refresh_in_progress'):
        return apply_scan_resource(
            tenant['tenant_id'],
            scan['scan_id'],
            observation,
        )
    evidence = observation.get('evidence') or {}
    if not evidence_needs_refresh(evidence):
        return observation
    try:
        refreshed, _ = refresh_resource_observation(
            tenant,
            scan,
            observation,
            store=store,
            policies=policies,
        )
        return refreshed
    except Exception:
        logger.warning(
            'Resource refresh failed resource_id=%s scan_id=%s',
            observation.get('resource_id'),
            scan.get('scan_id'),
            exc_info=True,
        )
        return observation
