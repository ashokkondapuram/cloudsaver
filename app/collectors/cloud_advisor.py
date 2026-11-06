"""Stream E — cloud advisor / recommender signals (optional, read-only)."""
from __future__ import annotations

import logging
from uuid import UUID

from app.azure_rest_catalog import (
    ADVISOR_RECOMMENDATIONS_API_VERSION,
    advisor_recommendations_url,
)
from app.collectors.azure_live import pages
from app.domain.resource.identity import canonical_resource_id

logger = logging.getLogger('cloudsaver.scanner')


def enabled(settings=None) -> bool:
    from app.cloudsaver_platform_settings import integration_flag

    return integration_flag(
        settings,
        'cloud_advisor_enabled',
        'CLOUDSAVER_CLOUD_ADVISOR_ENABLED',
        default='false',
    )


def normalize_azure_advisor_recommendation(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    props = item.get('properties') or {}
    meta = props.get('resourceMetadata') or {}
    short = props.get('shortDescription') or {}
    rec_id = item.get('name') or item.get('id')
    if not rec_id:
        return None
    return dict(
        source='azure_advisor',
        recommendation_id=str(rec_id),
        resource_id=str(meta.get('resourceId') or ''),
        category=str(props.get('category') or ''),
        impact=str(props.get('impact') or ''),
        recommendation_type_id=str(props.get('recommendationTypeId') or ''),
        problem=str(short.get('problem') or ''),
        solution=str(short.get('solution') or ''),
        last_updated=str(props.get('lastUpdated') or ''),
    )


def fetch_azure_advisor_recommendations(reader, scope: str) -> list[dict]:
    """List normalized Advisor recommendations for a subscription scope."""
    sid = str(UUID(scope))
    url = advisor_recommendations_url(sid)
    params = {'api-version': ADVISOR_RECOMMENDATIONS_API_VERSION}
    out: list[dict] = []
    for item in pages(reader, url, params):
        normalized = normalize_azure_advisor_recommendation(item)
        if normalized:
            out.append(normalized)
    return out


def fetch_aws_trusted_advisor_recommendations(client, scope: str) -> list[dict]:
    """TODO: Stream E — AWS Trusted Advisor / Compute Optimizer recommendation APIs."""
    del client, scope
    return []


def fetch_gcp_recommender_recommendations(reader, scope: str) -> list[dict]:
    """TODO: Stream E — GCP Recommender API (google.cloud.recommender.v1)."""
    del reader, scope
    return []


def enrich_inventory_advisor_signals(
    reader,
    inventory,
    *,
    subscriptions: list[str],
    settings=None,
) -> list[dict]:
    """Attach advisor_signals[] on inventory evidence rows keyed by resource id."""
    if not enabled(settings):
        return inventory
    by_resource: dict[str, list[dict]] = {}
    for subscription_id in subscriptions:
        try:
            signals = fetch_azure_advisor_recommendations(reader, subscription_id)
        except Exception:
            logger.exception(
                'Azure Advisor enrichment failed subscription=%s',
                subscription_id,
            )
            continue
        for signal in signals:
            rid = signal.get('resource_id') or ''
            if not rid:
                continue
            key = canonical_resource_id('azure', rid)
            by_resource.setdefault(key, []).append(
                {k: v for k, v in signal.items() if k != 'resource_id'}
            )
    for resource in inventory:
        key = canonical_resource_id('azure', resource.get('resource_id') or '')
        matched = by_resource.get(key)
        if matched:
            resource.setdefault('evidence', {})['advisor_signals'] = matched
    return inventory
