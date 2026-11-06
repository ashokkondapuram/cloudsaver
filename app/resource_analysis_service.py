"""Per-resource analysis and recommendation materialization — one inventory row at a time."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.resource_fetch_stages import set_stage, sync_fetch_stages

logger = logging.getLogger('cloudsaver.resource_analysis')


def build_scan_rule_policies(rule_policy: dict | None, rule_ids: set[str] | None) -> dict:
    """Workspace rule policy map used by evaluate_inventory."""
    policies = {item['id']: item for item in (rule_policy or {}).get('items', [])}
    if rule_ids is None:
        return policies
    from app.kubernetes_rules import DEFINITIONS as KUBERNETES_RULES
    from app.resource_catalog import definitions

    for rid, *_ in (*KUBERNETES_RULES, *definitions()):
        policies.setdefault(rid, {'enabled': rid in rule_ids})
    return policies


def _price_findings(findings: list[dict], resource: dict) -> list[dict]:
    from app.azure_pricing_evidence import enrich_azure_pricing_evidence
    from app.pricing import attribute_finding_cost

    priced = []
    for finding in findings:
        enriched = enrich_azure_pricing_evidence(dict(finding), resource)
        priced.append(attribute_finding_cost(enriched))
    return priced


def _arg_findings_for_resource(arg_findings: list[dict], resource: dict) -> list[dict]:
    rid = (resource.get('resource_id') or '').lower()
    provider = resource.get('cloud_provider', 'azure')
    return [
        f
        for f in arg_findings
        if isinstance(f.get('resource_id'), str)
        and f['resource_id'].lower() == rid
        and (f.get('cloud_provider') or 'azure') == provider
    ]


def analyze_resource(
    resource: dict,
    *,
    arg_findings: list[dict] | None = None,
    policies: dict | None = None,
    observed_at: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate rules, materialize findings, price retail, and derive recommendations for one resource."""
    now = now or datetime.now(timezone.utc)
    stamp = observed_at or now.isoformat().replace('+00:00', 'Z')
    evidence = resource.setdefault('evidence', {})
    set_stage(evidence, 'analysis', 'running')
    set_stage(evidence, 'recommendations', 'pending')

    from app.analysis_rules import evaluate_inventory
    from app.multicloud_rules import materialize
    from app.resource_assessment import assess_resource, inventory_observation, resource_key

    evaluations = evaluate_inventory([resource], observed_at=stamp, policies=policies, now=now)
    set_stage(evidence, 'analysis', 'completed')

    from app.collectors.azure_configuration_evidence import enrich_configuration_evidence
    from app.evidence_derived_facts import apply_derived_facts

    enrich_configuration_evidence(resource)
    apply_derived_facts(resource)

    base = _arg_findings_for_resource(list(arg_findings or []), resource)
    merged = materialize(base, [resource], evaluations)
    findings = _price_findings(merged, resource)

    if findings:
        for finding in findings:
            pricing = finding.get('pricing_evidence')
            if isinstance(pricing, dict):
                evidence['pricing_evidence'] = pricing
                break
    elif (resource.get('cloud_provider') or 'azure') == 'azure':
        from app.azure_pricing_evidence import build_pricing_evidence

        built = build_pricing_evidence(inventory_observation(resource), resource)
        if isinstance(built, dict):
            evidence['pricing_evidence'] = built

    key = resource_key(inventory_observation(resource))
    stub = dict(
        timestamp=stamp,
        findings=findings,
        inventory=[resource],
        rule_evaluations=evaluations,
    )
    pair = assess_resource(stub, key, list_view=False)
    if pair is None:
        assessment = None
        recommendations: list[dict] = []
        set_stage(evidence, 'recommendations', 'failed')
    else:
        assessment, _context = pair
        from app.resource_action_items import derive_action_items

        recommendations = derive_action_items(assessment, findings, evaluations)
        resource['recommendations'] = recommendations
        set_stage(evidence, 'recommendations', 'completed')

    from app.resource_timestamps import touch_last_analyzed

    touch_last_analyzed(evidence, now=now)
    sync_fetch_stages(evidence, findings=findings)
    logger.info(
        'Resource analysis resource_id=%s evaluations=%s findings=%s recommendations=%s',
        resource.get('resource_id'),
        len(evaluations),
        len(findings),
        len(recommendations),
    )
    return dict(
        evaluations=evaluations,
        findings=findings,
        recommendations=recommendations,
        assessment=assessment,
    )


def reanalyze_scan_snapshot(scan: dict, *, policies: dict | None = None) -> dict:
    """Re-run analysis for every inventory row (for example after billing is attached)."""
    stamp = scan.get('timestamp')
    seed_findings = list(scan.get('findings') or [])
    finding_index: dict[tuple, dict] = {}
    for finding in seed_findings:
        rid = (finding.get('resource_id') or '').lower()
        if rid:
            finding_index[
                (
                    finding.get('cloud_provider', 'azure'),
                    rid,
                    finding.get('rule_id'),
                )
            ] = finding
    evaluations: list[dict] = []
    eval_keys: set[tuple] = set()
    for resource in scan.get('inventory') or []:
        from app.evidence_derived_facts import apply_derived_facts

        apply_derived_facts(resource)
        from app.collectors.azure_configuration_evidence import enrich_configuration_evidence

        enrich_configuration_evidence(resource)
        result = analyze_resource(
            resource,
            arg_findings=seed_findings,
            policies=policies,
            observed_at=stamp,
        )
        for finding in result['findings']:
            key = (
                finding.get('cloud_provider', 'azure'),
                (finding.get('resource_id') or '').lower(),
                finding.get('rule_id'),
            )
            if key[1]:
                finding_index[key] = finding
        for row in result['evaluations']:
            key = (row.get('cloud_provider', 'azure'), (row.get('resource_id') or '').lower(), row.get('rule_id'))
            if key not in eval_keys:
                eval_keys.add(key)
                evaluations.append(row)
    scan['findings'] = list(finding_index.values())
    scan['rule_evaluations'] = evaluations
    return scan
