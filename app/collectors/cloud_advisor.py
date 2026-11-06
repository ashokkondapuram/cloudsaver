"""Stream E — cloud advisor / recommender signals (optional, read-only)."""
from __future__ import annotations

import logging
from uuid import UUID

from app.azure_rest_catalog import (
    ADVISOR_RECOMMENDATIONS_API_VERSION,
    advisor_recommendations_url,
)
from app.cloud_http import pages as cloud_pages
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


def normalize_aws_trusted_advisor_flag(check_id: str, check_name: str, row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    rid = row.get('resourceId') or row.get('resource_id')
    if not rid:
        return None
    meta = row.get('metadata') if isinstance(row.get('metadata'), list) else []
    return dict(
        source='aws_trusted_advisor',
        check_id=str(check_id),
        check_name=str(check_name or ''),
        resource_id=str(rid),
        region=str(row.get('region') or ''),
        status=str(row.get('status') or ''),
        metadata=meta,
    )


def fetch_aws_trusted_advisor_recommendations(client, scope: str) -> list[dict]:
    """List normalized Trusted Advisor flags for *scope* (AWS account id)."""
    del scope
    if client is None:
        return []
    try:
        checks_resp = client.describe_trusted_advisor_checks(language='en')
    except Exception:
        logger.exception('AWS Trusted Advisor describe_checks failed')
        return []
    checks = checks_resp.get('checks') or []
    if not isinstance(checks, list):
        return []
    costish = {'cost_optimizing', 'performance', 'fault_tolerance', 'service_limits'}
    check_ids = [c['id'] for c in checks if isinstance(c, dict) and c.get('id') and (c.get('category') in costish)]
    if not check_ids:
        check_ids = [c['id'] for c in checks if isinstance(c, dict) and c.get('id')][:40]
    if not check_ids:
        return []
    try:
        summaries = client.describe_trusted_advisor_check_summaries(checkIds=check_ids)
    except Exception:
        logger.exception('AWS Trusted Advisor check_summaries failed')
        return []
    by_sum = {s['checkId']: s for s in (summaries.get('summaries') or []) if isinstance(s, dict) and s.get('checkId')}
    by_name = {c['id']: c.get('name', '') for c in checks if isinstance(c, dict) and c.get('id')}
    out: list[dict] = []
    calls = 0
    for cid in check_ids:
        summ = by_sum.get(cid) or {}
        status = summ.get('status')
        if status in (None, 'not_available', 'enqueued', 'processing'):
            continue
        if status == 'ok' and not summ.get('resourcesFlagged'):
            continue
        if calls >= 35:
            break
        calls += 1
        try:
            result = client.describe_trusted_advisor_check_result(checkId=cid, language='en')
        except Exception:
            logger.debug('Trusted Advisor check_result unavailable check_id=%s', cid, exc_info=True)
            continue
        flagged = (result.get('result') or {}).get('flaggedResources') or []
        if not isinstance(flagged, list):
            continue
        for fr in flagged:
            if not isinstance(fr, dict):
                continue
            if fr.get('isSuppressed'):
                continue
            norm = normalize_aws_trusted_advisor_flag(cid, by_name.get(cid, ''), fr)
            if norm:
                out.append(norm)
    return out


def normalize_gcp_recommendation(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    name = item.get('name') or ''
    content = item.get('content') or {}
    overview = content.get('overview') if isinstance(content.get('overview'), dict) else {}
    rid = str(overview.get('resourceName') or overview.get('resourceNames', [''])[0] or '')
    if not rid and name:
        parts = name.split('/recommendations/')
        if len(parts) == 2 and parts[0]:
            rid = f'{parts[0]}/recommendations/{parts[1]}'
    rec_label = ''
    if '/recommenders/' in name:
        try:
            rec_label = name.split('/recommenders/')[1].split('/recommendations/')[0]
        except (IndexError, AttributeError):
            rec_label = ''
    return dict(
        source='gcp_recommender',
        recommendation_id=str(name or item.get('etag') or ''),
        resource_id=rid,
        state=str(item.get('state') or ''),
        description=str(overview.get('shortDescription') or overview.get('summary') or '')[:2000],
        recommender=rec_label,
        last_refresh_time=str(item.get('lastRefreshTime') or ''),
    )


def fetch_gcp_recommender_recommendations(
    reader,
    project_id: str,
    regions: list[str] | None = None,
) -> list[dict]:
    """List normalized recommendations for *project_id* (optionally per *regions* zones)."""
    if reader is None or not project_id:
        return []
    regions = regions or []
    locations: list[str] = ['global']
    for r in regions:
        if isinstance(r, str) and r:
            locations.append(f'{r}-a')
    seen_loc: set[str] = set()
    uniq_locations = []
    for loc in locations:
        if loc not in seen_loc:
            seen_loc.add(loc)
            uniq_locations.append(loc)
    recommenders = (
        'google.compute.instance.MachineTypeRecommender',
        'google.compute.disk.IdleDiskRecommender',
        'google.cloudsql.instance.IdleRecommender',
    )
    out: list[dict] = []
    for loc in uniq_locations:
        for rec_id in recommenders:
            parent = (
                f'https://recommender.googleapis.com/v1/projects/{project_id}/locations/{loc}'
                f'/recommenders/{rec_id}/recommendations'
            )
            try:
                for page in cloud_pages(reader, parent, {'pageSize': 200}):
                    for item in page.get('recommendations') or []:
                        norm = normalize_gcp_recommendation(item)
                        if norm and norm.get('resource_id'):
                            out.append(norm)
            except Exception:
                logger.debug(
                    'GCP Recommender list failed project=%s location=%s recommender=%s',
                    project_id,
                    loc,
                    rec_id,
                    exc_info=True,
                )
                continue
    return out


def enrich_inventory_advisor_signals(
    reader,
    inventory,
    *,
    subscriptions: list[str] | None = None,
    aws_support_client=None,
    aws_account_ids: list[str] | None = None,
    gcp_projects: list[tuple[str, list[str]]] | None = None,
    settings=None,
) -> list[dict]:
    """Attach advisor_signals[] on inventory evidence rows keyed by resource id."""
    if not enabled(settings):
        return inventory
    by_resource: dict[str, list[dict]] = {}
    for subscription_id in subscriptions or []:
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
    for account_id in aws_account_ids or []:
        try:
            signals = fetch_aws_trusted_advisor_recommendations(aws_support_client, str(account_id))
        except Exception:
            logger.exception('AWS Trusted Advisor enrichment failed account=%s', account_id)
            continue
        for signal in signals:
            rid = signal.get('resource_id') or ''
            if not rid:
                continue
            key = canonical_resource_id('aws', rid)
            by_resource.setdefault(key, []).append(
                {k: v for k, v in signal.items() if k != 'resource_id'}
            )
    for project_id, regions in gcp_projects or []:
        try:
            signals = fetch_gcp_recommender_recommendations(reader, str(project_id), regions)
        except Exception:
            logger.exception('GCP Recommender enrichment failed project=%s', project_id)
            continue
        for signal in signals:
            rid = signal.get('resource_id') or ''
            if not rid:
                continue
            key = canonical_resource_id('gcp', rid)
            by_resource.setdefault(key, []).append(
                {k: v for k, v in signal.items() if k != 'resource_id'}
            )
    for resource in inventory:
        provider = resource.get('cloud_provider') or 'azure'
        key = canonical_resource_id(provider, resource.get('resource_id') or '')
        matched = by_resource.get(key)
        if matched:
            resource.setdefault('evidence', {})['advisor_signals'] = matched
    return inventory
