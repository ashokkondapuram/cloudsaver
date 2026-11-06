"""Per-resource Azure fetch orchestration: enrich one row, analyze, persist, next."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.collectors.azure_arm_detail import enrich_arm_detail_row, enabled as arm_detail_enabled
from app.collectors.azure_configuration_evidence import enrich_configuration_evidence, live_collection_priority
from app.collectors.azure_live import METRICS, enrich_live_row
from app.collectors.azure_storage_policy import enrich_storage_row
from app.collectors.live_common import enabled as live_enabled
from app.analysis_client import analyze_resource
from app.resource_fetch_stages import init_fetch_stages, set_stage

logger = logging.getLogger('cloudsaver.resource_pipeline')


def _dedupe_findings(findings: list[dict]) -> list[dict]:
    merged: dict[tuple, dict] = {}
    for finding in findings:
        rid = finding.get('resource_id')
        if not isinstance(rid, str):
            continue
        key = (finding.get('cloud_provider', 'azure'), rid.lower(), finding.get('rule_id'))
        merged[key] = finding
    return list(merged.values())


def _live_candidates(inventory, settings):
    from app.collectors.azure_live import _live_resource_limit

    limit = _live_resource_limit(settings)
    candidates = [r for r in inventory if r['resource_type'].lower() in METRICS]
    candidates.sort(key=live_collection_priority)
    if limit is None:
        return set(id(r) for r in candidates), limit
    selected = candidates[:limit]
    for r in candidates[limit:]:
        r.setdefault('evidence', {}).setdefault('live_sources', {})['telemetry'] = 'resource_budget_exceeded'
        enrich_configuration_evidence(r)
    return {id(r) for r in selected}, limit


def _finding_key(finding: dict) -> tuple:
    return (
        finding.get('cloud_provider', 'azure'),
        (finding.get('resource_id') or '').lower(),
        finding.get('rule_id'),
    )


def _merge_findings(index: dict[tuple, dict], findings: list[dict]) -> None:
    for finding in findings:
        key = _finding_key(finding)
        if key[1]:
            index[key] = finding


def _run_resource_analysis(
    resource,
    *,
    arg_findings,
    policies,
    observed_at,
    now,
    progress,
    finding_index: dict[tuple, dict],
):
    """Re-evaluate rules and recommendations from the resource's current evidence."""
    enrich_configuration_evidence(resource)
    analysis = analyze_resource(
        resource,
        arg_findings=arg_findings,
        policies=policies,
        observed_at=observed_at,
        now=now,
    )
    _merge_findings(finding_index, analysis['findings'])
    if progress is not None:
        progress.record_resource_bundle(
            resource,
            findings=analysis['findings'],
            evaluations=analysis['evaluations'],
        )
    return analysis


def _collect_resource_evidence(
    reader,
    resource,
    *,
    settings,
    now,
    stats,
    version_cache,
    recovery,
    live_selected: bool,
):
    """ARM, policy, governance, and live collection before a single analysis pass."""
    if arm_detail_enabled(settings) and (resource.get('evidence') or {}).get('arm_detail') != 'collected':
        enrich_arm_detail_row(
            reader,
            resource,
            settings=settings,
            now=now,
            stats=stats,
            version_cache=version_cache,
            progress=None,
        )
    enrich_storage_row(reader, resource)
    if (resource.get('cloud_provider') or 'azure') == 'azure':
        from app.collectors.azure_governance import enrich_azure_governance_row, governance_on_scan

        if governance_on_scan(settings):
            enrich_azure_governance_row(reader, resource)
    if live_enabled(settings) and live_selected and resource['resource_type'].lower() in METRICS:
        enrich_live_row(reader, resource, now=now, recovery=recovery)
    from app.resource_timestamps import touch_azure_status_fetched

    touch_azure_status_fetched(resource.setdefault('evidence', {}), now=now)


def enrich_single_resource(
    reader,
    resource,
    *,
    settings,
    arg_findings=None,
    policies=None,
    observed_at=None,
    now=None,
    recovery=None,
    version_cache=None,
    stats=None,
    live_selected=True,
):
    """Re-fetch Azure evidence and re-run analysis for one inventory row."""
    now = now or datetime.now(timezone.utc)
    stamp = observed_at or now.isoformat().replace('+00:00', 'Z')
    version_cache = version_cache if version_cache is not None else {}
    stats = stats if stats is not None else dict(attempted=0, succeeded=0, failed=0, not_attempted=0)
    recovery = recovery if recovery is not None else {}
    init_fetch_stages(resource.setdefault('evidence', {}))
    _collect_resource_evidence(
        reader,
        resource,
        settings=settings,
        now=now,
        stats=stats,
        version_cache=version_cache,
        recovery=recovery,
        live_selected=live_selected,
    )
    enrich_configuration_evidence(resource)
    return analyze_resource(
        resource,
        arg_findings=arg_findings,
        policies=policies,
        observed_at=stamp,
        now=now,
    )


def enrich_inventory_pipeline(
    reader,
    inventory,
    *,
    settings,
    progress=None,
    arg_findings=None,
    policies=None,
    observed_at=None,
):
    """Strict per-resource pass: fetch evidence, run analysis service, upsert DB, advance."""
    arg_findings = list(arg_findings or [])
    version_cache: dict = {}
    stats = dict(attempted=0, succeeded=0, failed=0, not_attempted=0)
    recovery: dict = {}
    live_selected, _limit = _live_candidates(inventory, settings) if live_enabled(settings) else (set(), None)
    now = datetime.now(timezone.utc)
    stamp = observed_at or now.isoformat().replace('+00:00', 'Z')
    total = len(inventory)
    finding_index: dict[tuple, dict] = {}

    for index, resource in enumerate(inventory, start=1):
        if index == 1 or index % 100 == 0 or index == total:
            logger.info('Resource pipeline %s/%s resource_id=%s', index, total, resource.get('resource_id'))
        evidence = resource.setdefault('evidence', {})
        init_fetch_stages(evidence)

        if live_enabled(settings) and id(resource) not in live_selected and _limit is not None:
            if resource['resource_type'].lower() in METRICS:
                set_stage(evidence, 'activity_log', 'skipped')

        _collect_resource_evidence(
            reader,
            resource,
            settings=settings,
            now=now,
            stats=stats,
            version_cache=version_cache,
            recovery=recovery,
            live_selected=id(resource) in live_selected if live_enabled(settings) else False,
        )
        _run_resource_analysis(
            resource,
            arg_findings=arg_findings,
            policies=policies,
            observed_at=stamp,
            now=now,
            progress=progress,
            finding_index=finding_index,
        )

    all_findings = list(finding_index.values())
    logger.info('Resource pipeline finished resources=%s findings=%s', total, len(all_findings))
    return inventory, _dedupe_findings(all_findings)
