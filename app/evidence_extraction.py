"""Extract JSON evidence snapshots for assessment checks and action items."""
from __future__ import annotations

from typing import Any


def _public_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    """Drop internal check/rule codes from user-facing evidence JSON."""
    out = dict(data)
    out.pop('check', None)
    return out


def effective_observation_evidence(observation: dict | None) -> dict[str, Any]:
    """Merge snapshot + dependency edges and project configuration like assessment does."""
    if not observation:
        return {}
    evidence = dict(observation.get('evidence') or {})
    snapshot = observation.get('configuration_snapshot')
    if isinstance(snapshot, dict):
        for key, value in snapshot.items():
            if key in ('metrics', 'state_history'):
                continue
            if evidence.get(key) is None and value is not None:
                evidence[key] = value
    from app.resource_assessment import _dependency_evidence_from_observation

    evidence.update(_dependency_evidence_from_observation(observation))
    stub = dict(
        cloud_provider=observation.get('cloud_provider', 'azure'),
        resource_type=observation.get('resource_type') or '',
        resource_id=observation.get('resource_id'),
        dependency_refs=observation.get('dependency_refs'),
        evidence=evidence,
    )
    from app.collectors.azure_configuration_evidence import enrich_configuration_evidence

    enrich_configuration_evidence(stub)
    return stub.get('evidence') or evidence


def _get_nested(mapping: dict, path: str) -> Any:
    if not path:
        return None
    if path.startswith('metrics.'):
        rest = path.split('.', 1)[1]
        metrics = mapping.get('metrics') or {}
        if rest in metrics:
            return metrics[rest]
        summaries = mapping.get('metric_summaries') or {}
        return summaries.get(rest)
    return mapping.get(path)


def snapshot_for_fields(
    evidence: dict,
    fields: list[str] | None,
    *,
    observation: dict | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    """Build a JSON object of saved values backing a check or action item."""
    evidence = evidence or {}
    fields = list(fields or [])
    out: dict[str, Any] = {}

    if code == 'DEPENDENCY_GRAPH':
        refs = (observation or {}).get('dependency_refs') or []
        out['dependency_refs'] = refs[:50]
        out['verified_dependencies'] = evidence.get('verified_dependencies')
        out['dependency_inventory_complete'] = evidence.get('dependency_inventory_complete')
        out['state_history'] = evidence.get('state_history')
        return out

    if code == 'BILLED_COST':
        out['billed_cost_usd'] = evidence.get('billed_cost_usd')
        out['effective_cost_usd'] = evidence.get('effective_cost_usd')
        out['currency'] = evidence.get('currency')
        out['commitment_locked'] = evidence.get('commitment_locked')
        out['commitment_lock_conflict'] = evidence.get('commitment_lock_conflict')
        out['billing_coverage'] = evidence.get('billing_coverage')
        return out

    if code in ('ACCESS_AND_EXPOSURE', 'INSTANCE_METADATA', 'ADMIN_INGRESS'):
        for field in (
            'public_admin_ingress',
            'imds_v2_required',
            'unrestricted_ingress',
            'ddos_or_waf_enabled',
            'https_only',
        ):
            if field in evidence:
                out[field] = evidence[field]
        tc = evidence.get('typed_configuration')
        if isinstance(tc, dict):
            configuration = {
                k: tc.get(k)
                for k in ('httpsOnly', 'siteConfig', 'networkProfile', 'publicNetworkAccess', 'securityProfile')
                if tc.get(k) is not None
            }
            if configuration:
                out['configuration'] = configuration
        if out:
            return out
        return {'status': 'not_collected'}

    if code == 'HEALTH_PROBES':
        for key in ('health_probes_enabled', 'health_check_paths', 'hosted_app_count'):
            if key in evidence:
                out[key] = evidence[key]
        tc = evidence.get('typed_configuration')
        if isinstance(tc, dict):
            sc = tc.get('siteConfig')
            if isinstance(sc, dict) and sc.get('healthCheckPath'):
                out['healthCheckPath'] = sc['healthCheckPath']
        if out:
            return out
        return {'status': 'not_collected'}

    if code == 'MANAGED_SECRETS':
        for key in ('managed_secrets', 'disableLocalAuth'):
            if key in evidence:
                out[key] = evidence[key]
        tc = evidence.get('typed_configuration')
        if isinstance(tc, dict):
            if tc.get('keyVaultReferenceIdentity'):
                out['keyVaultReferenceIdentity'] = tc['keyVaultReferenceIdentity']
            sc = tc.get('siteConfig')
            if isinstance(sc, dict) and sc.get('appSettings'):
                out['appSettings'] = [
                    {'name': s.get('name')}
                    for s in sc['appSettings'][:20]
                    if isinstance(s, dict) and s.get('name')
                ]
        if out:
            return out
        return {'status': 'not_collected'}

    if code == 'COMMITMENT_LOCK':
        out['commitment_locked'] = evidence.get('commitment_locked')
        out['commitment_lock_conflict'] = evidence.get('commitment_lock_conflict')
        return out

    if code == 'FLOW_LOGS':
        if 'flow_logs_enabled' in evidence:
            out['flow_logs_enabled'] = evidence['flow_logs_enabled']
        if out:
            return out
        return {'status': 'not_collected'}

    if code == 'MONITORING_AGENT':
        for key in ('monitoring_enabled', 'live_sources'):
            if key in evidence:
                out[key] = evidence[key]
        if out:
            return out
        return {'status': 'not_collected'}

    if code == 'PATCH_CURRENCY':
        if evidence.get('patch_age_days') is not None:
            out['patch_age_days'] = evidence['patch_age_days']
        if evidence.get('created_at'):
            out['created_at'] = evidence['created_at']
        if out:
            return out
        return {'status': 'not_collected'}

    if code == 'UNATTACHED_DURATION':
        for key in ('unattached_days', 'disk_state', 'created_at', 'state_history'):
            if key in evidence:
                out[key] = evidence[key]
        if out:
            return out
        return {'status': 'not_collected'}

    if code == 'SNAPSHOT_FRESHNESS':
        for key in ('snapshot_age_hours', 'recent_snapshot_verified', 'state_history'):
            if key in evidence:
                out[key] = evidence[key]
        if out:
            return out
        return {'status': 'not_collected'}

    if code == 'SNAPSHOT_EXPOSURE':
        if 'public_snapshot' in evidence:
            out['public_snapshot'] = evidence['public_snapshot']
        if type(evidence.get('allow_blob_public_access')) is bool:
            out['allow_blob_public_access'] = evidence['allow_blob_public_access']
        if out:
            return out
        return {'status': 'not_collected'}

    if code == 'FIVE_MINUTE_UTILIZATION' or code == 'UTILIZATION_WINDOW':
        metrics = evidence.get('metrics') or {}
        summaries = evidence.get('metric_summaries') or {}
        keys = ('cpu_percent', 'memory_percent', 'iops', 'throughput', 'normalized_ru_consumption', 'ptu_utilization')
        out['metrics'] = {k: metrics[k] for k in keys if k in metrics}
        out['metric_summaries'] = {k: summaries[k] for k in keys if k in summaries}
        out['window_start'] = evidence.get('window_start')
        out['window_end'] = evidence.get('window_end')
        out['p95_usage'] = evidence.get('p95_usage')
        out['minimum_request'] = evidence.get('minimum_request')
        if out.get('metrics') or out.get('metric_summaries') or out.get('p95_usage') is not None:
            return out
        return out or {'status': 'not_collected'}

    if code == 'ENCRYPTION_AT_REST':
        for key in ('encrypted', 'tls_required', 'customer_managed_key_verified'):
            if key in evidence:
                out[key] = evidence[key]
        tc = evidence.get('typed_configuration')
        if isinstance(tc, dict) and isinstance(tc.get('encryption'), dict):
            out['encryption'] = tc['encryption']
        if out:
            return out

    for field in fields:
        if field in out:
            continue
        value = _get_nested(evidence, field)
        if value is not None:
            out[field] = value

    if not out and code:
        out['status'] = 'not_collected'
    return _public_snapshot(out)


def snapshot_for_finding(finding: dict, observation: dict | None = None) -> dict[str, Any]:
    """Observation-backed JSON for a finding action (no internal rule ids)."""
    out: dict[str, Any] = {}
    ev = finding.get('evidence') or {}
    for key in (
        'pricing_evidence',
        'minimum_days',
        'numberOfSites',
        'sku',
        'tier',
        'capacity',
        'provisioningState',
        'powerState',
    ):
        if key in ev:
            out[key] = ev[key]
    if finding.get('details'):
        out['details'] = finding['details']
    if finding.get('estimated_monthly_waste_usd') is not None:
        out['estimated_monthly_waste_usd'] = finding['estimated_monthly_waste_usd']
    obs_ev = ((observation or {}).get('evidence') or {}) if observation else {}
    tc = obs_ev.get('typed_configuration')
    if isinstance(tc, dict) and tc:
        out['typed_configuration'] = tc
    snapshot = (observation or {}).get('configuration_snapshot')
    if isinstance(snapshot, dict) and snapshot:
        out['configuration_snapshot'] = snapshot
    metrics = obs_ev.get('metrics') or obs_ev.get('metric_summaries')
    if metrics:
        out['metrics'] = metrics
    return out


def attach_check_evidence(assessment: dict, observation: dict | None) -> dict:
    obs_evidence = effective_observation_evidence(observation)
    for pillar in assessment.get('pillars') or []:
        for check in pillar.get('checks') or []:
            check['evidence_json'] = snapshot_for_fields(
                obs_evidence,
                check.get('evidence_fields'),
                observation=observation,
                code=check.get('code'),
            )
    return assessment


def attach_action_item_evidence(action_items: list[dict], assessment: dict, observation: dict | None) -> list[dict]:
    checks = {}
    for pillar in assessment.get('pillars') or []:
        for check in pillar.get('checks') or []:
            checks[check['code']] = check
    obs_evidence = effective_observation_evidence(observation)
    enriched = []
    for item in action_items:
        row = dict(item)
        finding = row.pop('finding_evidence', None)
        if finding is not None:
            row['evidence_json'] = snapshot_for_finding(finding, observation)
        else:
            codes = item.get('evidence_codes') or []
            if len(codes) == 1 and codes[0] in checks and checks[codes[0]].get('evidence_json'):
                row['evidence_json'] = checks[codes[0]]['evidence_json']
            else:
                merged: dict[str, Any] = {}
                for code in codes:
                    check = checks.get(code) or {}
                    snapshot = check.get('evidence_json') or snapshot_for_fields(
                        obs_evidence,
                        check.get('evidence_fields'),
                        observation=observation,
                        code=code,
                    )
                    if snapshot:
                        merged.update(snapshot if isinstance(snapshot, dict) else {'value': snapshot})
                row['evidence_json'] = merged if merged else snapshot_for_fields(
                    obs_evidence,
                    codes,
                    observation=observation,
                )
        row['evidence_codes'] = []
        enriched.append(row)
    return enriched
