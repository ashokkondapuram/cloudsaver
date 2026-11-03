"""One deterministic five-pillar assessment per resource, merged from all of its findings."""
import csv
import hashlib
import io
import json
import re
from decimal import Decimal

from app.assessment import PILLARS, ai_context, assess, category as service_category
from app.ai_resource_context import build_resource_ai_context
from app.assessment_policy import POLICY_VERSION

SEVERITY = {'risk': 2, 'unknown': 1, 'observed': 0}
PRIORITY = ('critical', 'high', 'evidence_required')
HISTORY_SCANS = 10
_BILLING_FIELDS = ('billed_cost_usd', 'effective_cost_usd', 'currency', 'commitment_locked', 'billing_coverage')


def overlay_inventory_billing(assessment, obs):
    """Resources with findings skip merge_inventory; copy billed evidence from the inventory row."""
    if not obs:
        return assessment
    evidence = obs.get('evidence') or {}
    patch = {field: evidence[field] for field in _BILLING_FIELDS if evidence.get(field) is not None and assessment.get(field) is None}
    if not patch:
        return assessment
    updated = dict(assessment, **patch)
    if updated.get('billed_cost_usd') is not None or updated.get('effective_cost_usd') is not None:
        for pillar in updated.get('pillars', []):
            if pillar.get('pillar') != 'cost':
                continue
            for check in pillar.get('checks', []):
                if check.get('code') == 'BILLED_COST' and check.get('status') == 'unknown':
                    check['status'] = 'risk' if updated.get('commitment_locked') else 'observed'
    return updated


def identity(finding):
    provider = finding.get('cloud_provider', 'azure')
    resource = finding['resource_id'].lower() if provider == 'azure' else finding['resource_id']
    return provider, resource


def resource_key(finding):
    provider, resource = identity(finding)
    return hashlib.sha256((provider + '|' + resource).encode()).hexdigest()


def group(findings):
    groups = {}
    for finding in findings:
        groups.setdefault(resource_key(finding), []).append(finding)
    return groups


def merge(key, findings, *, observed_at=None, now=None):
    """Return (assessment, sanitized AI context) for one resource."""
    from app.rule_id_canonical import normalize_finding

    if not findings:
        raise ValueError('At least one finding observation is required to merge an assessment')
    deduped = []
    for finding in findings:
        if not isinstance(finding, dict) or not finding.get('resource_id'):
            raise ValueError('Each finding must include a resource_id')
        deduped.append(normalize_finding(finding))
    findings = sorted(deduped, key=lambda f: f['rule_id'])
    results = [assess(f, observed_at=observed_at, now=now) for f in findings]
    if not results:
        raise ValueError('Assessment produced no results')
    checks = {}
    for result in results:
        for pillar in result['pillars']:
            for check in pillar['checks']:
                slot = (check['pillar'], check['code'])
                current = checks.get(slot)
                if current is None:
                    checks[slot] = dict(check, evidence_fields=list(check['evidence_fields']))
                else:
                    if SEVERITY[check['status']] > SEVERITY[current['status']]:
                        current.update(status=check['status'], explanation=check['explanation'])
                    current['evidence_fields'] = sorted(set(current['evidence_fields']) | set(check['evidence_fields']))
    merged_checks = list(checks.values())
    pillars = []
    for name in PILLARS:
        items = [c for c in merged_checks if c['pillar'] == name]
        status = max((c['status'] for c in items), key=SEVERITY.get, default='unknown')
        pillars.append(dict(pillar=name, status=status, checks=items))
    guardrails = list(dict.fromkeys(g for r in results for g in r['guardrails']))
    protected = sorted({reason for r in results for reason in r['protected_reasons']})
    waste_amounts = [Decimal(str(r['retail_estimate_usd'])) for r in results if r['retail_estimate_usd'] is not None]
    from app.azure_pricing_evidence import resource_retail_run_rate_usd

    run_rate = resource_retail_run_rate_usd(findings)
    if run_rate is not None:
        retail_estimate = float(Decimal(str(run_rate)).quantize(Decimal('0.01')))
    elif waste_amounts:
        retail_estimate = float(max(waste_amounts).quantize(Decimal('0.01')))
    else:
        retail_estimate = None

    def _first_cost(field):
        for result in results:
            value = result.get(field)
            if value is not None:
                return value
        return None

    risk_codes = sorted({c['code'] for c in merged_checks if c['status'] == 'risk'})
    first = findings[0]
    provider, _ = identity(first)
    categories = {r['service_category'] for r in results}
    category = categories.pop() if len(categories) == 1 else 'mixed'
    observation = results[0]['observation']
    assessment = dict(
        resource_key=key, provider=provider, resource_id=first['resource_id'], resource_name=first.get('resource_name', ''),
        resource_type=first.get('resource_type', ''), resource_group=first.get('resource_group', ''),
        scope_id=first.get('scope_id') or first.get('subscription_id', ''), service_category=category,
        finding_count=len(findings), rule_ids=[f['rule_id'] for f in findings], policy_version=POLICY_VERSION,
        observation=observation, review_priority=min((r['review_priority'] for r in results), key=PRIORITY.index),
        disposition='protected' if protected else 'requires_review', protected_reasons=protected,
        risk_level='high' if any(code!='OBSERVATION_FRESHNESS' for code in risk_codes) else 'unknown', risk_check_codes=risk_codes,
        evidence_gap_codes=sorted({c['code'] for c in merged_checks if c['status'] == 'unknown'}),
        pillars=pillars, guardrails=guardrails,
        evidence_coverage=dict(observed=sum(c['status'] != 'unknown' for c in merged_checks), total=len(merged_checks)),
        retail_estimate_usd=retail_estimate,
        billed_cost_usd=_first_cost('billed_cost_usd'), effective_cost_usd=_first_cost('effective_cost_usd'),
        commitment_locked=any(r.get('commitment_locked') for r in results), currency=_first_cost('currency'),
        realizable_savings_usd=None, automatic_execution=False)
    context = build_resource_ai_context(assessment, findings, per_finding_assessments=results)
    from app.ai_resource_context import stable_digest_context

    stable = stable_digest_context(context)
    assessment['evidence_digest'] = hashlib.sha256(json.dumps(
        dict(context=stable, retail_estimate_usd=assessment['retail_estimate_usd']),
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return assessment, context


def inventory_observation(obs):
    """Normalize a saved inventory row into a finding-shaped dict (no waste rule)."""
    result = dict(
        cloud_provider=obs.get('cloud_provider', 'azure'),
        resource_id=obs['resource_id'],
        resource_name=obs.get('resource_name', ''),
        resource_type=obs.get('resource_type', ''),
        resource_group=obs.get('resource_group', ''),
        subscription_id=obs.get('subscription_id') or obs.get('scope_id', ''),
        scope_id=obs.get('scope_id') or obs.get('subscription_id', ''),
        rule_id='INVENTORY_OBSERVATION',
        severity='LOW',
        details='Resource observed in inventory scan.',
        evidence=obs.get('evidence') or {},
        estimated_monthly_waste_usd=None,
    )
    for key in ('reconciliation_status', 'data_sources', 'collector_version', 'evidence_schema_version'):
        if obs.get(key) is not None:
            result[key] = obs[key]
    return result


def merge_inventory(key, obs, *, observed_at=None, now=None):
    """Assessment for a resource present in inventory but without a finding rule hit."""
    if not isinstance(obs, dict) or not obs.get('resource_id'):
        raise ValueError('Inventory observation must include resource_id')
    result, context = merge(key, [inventory_observation(obs)], observed_at=observed_at, now=now)
    result.update(
        finding_count=0,
        rule_ids=[],
        disposition='protected' if result['protected_reasons'] else 'inventory_only',
    )
    from app.azure_pricing_evidence import inventory_retail_usd
    retail = inventory_retail_usd(obs)
    if retail is not None and result.get('retail_estimate_usd') is None:
        result['retail_estimate_usd'] = retail
    if result['disposition'] == 'inventory_only':
        result['guardrails'] = list(dict.fromkeys([*(result.get('guardrails') or []), 'INVENTORY_ONLY']))
    return result, context


def assessments(scan, *, now=None):
    merged = {key: merge(key, items, observed_at=scan.get('timestamp'), now=now) for key, items in group(scan['findings']).items()}
    for obs in scan.get('inventory') or []:
        key = resource_key(inventory_observation(obs))
        if key in merged:
            assessment, context = merged[key]
            merged[key] = (overlay_inventory_billing(assessment, obs), context)
            continue
        merged[key] = merge_inventory(key, obs, observed_at=scan.get('timestamp'), now=now)
    from app.ai_scan_context import augment_ai_context_from_scan
    from app.ai_resource_context import stable_digest_context

    finished = {}
    for key, (assessment, context) in merged.items():
        findings = group(scan['findings']).get(key, [])
        context = augment_ai_context_from_scan(scan, assessment, findings, context)
        stable = stable_digest_context(context)
        assessment = dict(assessment)
        assessment['evidence_digest'] = hashlib.sha256(json.dumps(
            dict(context=stable, retail_estimate_usd=assessment['retail_estimate_usd']),
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        finished[key] = (assessment, context)
    return finished


def row(assessment):
    """The list projection: pillar statuses without check detail."""
    keys = ('resource_key', 'provider', 'resource_id', 'resource_name', 'resource_type', 'resource_group', 'scope_id',
            'service_category', 'finding_count', 'rule_ids', 'review_priority', 'disposition', 'protected_reasons',
            'risk_level', 'risk_check_codes', 'evidence_gap_codes', 'evidence_coverage', 'retail_estimate_usd', 'evidence_digest')
    return dict({k: assessment[k] for k in keys}, billed_cost_usd=assessment.get('billed_cost_usd'),effective_cost_usd=assessment.get('effective_cost_usd'),commitment_locked=assessment.get('commitment_locked',False), pillars={p['pillar']: p['status'] for p in assessment['pillars']})


def observation_arm_detail(observation):
    if not observation:
        return None
    return (observation.get('evidence') or {}).get('arm_detail')


def summarize_resource_rows(items):
    """Aggregate summary for resource list rows (matches explorer KPI cards)."""
    counts = lambda field: {k: sum(1 for i in items if field(i) == k) for k in sorted({field(i) for i in items})}
    return dict(total=len(items), ai_status=counts(lambda i: i['ai']['status']), ai_risk=counts(lambda i: i['ai']['risk_level'] or 'none'),
                decision=counts(lambda i: (i['decision'] or {}).get('decision', 'none')),
                review_priority=counts(lambda i: i['review_priority']))


def ai_state(assessment, result, item):
    """Combine the latest AI result and batch item into one display state."""
    if item and item['status'] in ('queued', 'running'):
        status = item['status']
    elif result and result['evidence_digest'] == assessment['evidence_digest']:
        status = 'completed'
    elif item and item['status'] in ('failed', 'uncertain', 'skipped') and not result:
        status = 'failed'
    elif result:
        status = 'stale'
    else:
        status = 'not_run'
    return dict(status=status, risk_level=result['risk_level'] if result else None,
                summary=result['summary'] if result else None, actions=result['actions'] if result else [],
                assessment_id=result['assessment_id'] if result else None, created_at=result['created_at'] if result else None,
                evidence_digest=result['evidence_digest'] if result else None,
                reason=item.get('reason') if item and status == 'failed' else None)


def decision_state(assessment, decision, *, now=None):
    if not decision:
        return None
    from datetime import datetime, timezone, date
    expired = decision.get('decision') == 'defer' and decision.get('defer_until') and date.fromisoformat(str(decision['defer_until'])) <= (now or datetime.now(timezone.utc)).date()
    return dict(decision, decision='none' if expired else decision['decision'],reopened=bool(expired),previous_decision=decision['decision'],evidence_changed=decision['evidence_digest'] != assessment['evidence_digest'])


FILTERS = ('provider', 'service_category', 'review_priority', 'ai_status', 'ai_risk', 'decision', 'pillar_status')
ARM_DETAIL_VALUES = frozenset({'collected', 'unsupported_type', 'resource_budget_exceeded', 'api_version_unresolved', 'fetch_failed'})


def matches(item, filters):
    checks = dict(provider=item['provider'], service_category=item['service_category'], review_priority=item['review_priority'],
                  ai_status=item['ai']['status'], ai_risk=item['ai']['risk_level'] or 'none',
                  decision=(item['decision'] or {}).get('decision', 'none'),pillar_status=filters.get('pillar_status') if filters.get('pillar_status') in item['pillars'].values() else None)
    return all(not filters.get(name) or checks[name] == filters[name] for name in FILTERS)


def history(scans, key):
    """Deterministic assessments of one resource across the most recent completed scans, newest first."""
    entries = []
    for scan in scans[:HISTORY_SCANS]:
        items = [f for f in scan.get('findings', []) if resource_key(f) == key]
        if items:
            merged, _ = merge(key, items, observed_at=scan.get('timestamp'))
            entries.append(dict(scan_id=scan['scan_id'], timestamp=scan.get('timestamp'), present=True,
                                review_priority=merged['review_priority'], risk_level=merged['risk_level'],
                                rule_ids=merged['rule_ids'], pillars={p['pillar']: p['status'] for p in merged['pillars']},
                                evidence_digest=merged['evidence_digest'], retail_estimate_usd=merged['retail_estimate_usd']))
            continue
        inventory_rows = [obs for obs in scan.get('inventory') or [] if resource_key(inventory_observation(obs)) == key]
        if inventory_rows:
            merged, _ = merge_inventory(key, inventory_rows[0], observed_at=scan.get('timestamp'))
            entries.append(dict(scan_id=scan['scan_id'], timestamp=scan.get('timestamp'), present=True,
                                review_priority=merged['review_priority'], risk_level=merged['risk_level'],
                                rule_ids=merged['rule_ids'], pillars={p['pillar']: p['status'] for p in merged['pillars']},
                                evidence_digest=merged['evidence_digest'], retail_estimate_usd=merged['retail_estimate_usd']))
            continue
        entries.append(dict(scan_id=scan['scan_id'], timestamp=scan.get('timestamp'), present=False))
    for newer, older in zip(entries, entries[1:]):
        newer['changes'] = changes(older, newer)
    if entries:
        entries[-1].setdefault('changes', [])
    return entries


def changes(older, newer):
    if not older['present'] and newer['present']:
        return ['appeared']
    if older['present'] and not newer['present']:
        return ['no_longer_flagged']
    if not newer['present']:
        return []
    found = []
    if older['risk_level'] != newer['risk_level']:
        found.append('risk_changed')
    if older['review_priority'] != newer['review_priority']:
        found.append('priority_changed')
    found += [f'{pillar}_changed' for pillar in PILLARS if older['pillars'][pillar] != newer['pillars'][pillar]]
    if older['rule_ids'] != newer['rule_ids']:
        found.append('findings_changed')
    if older['evidence_digest'] != newer['evidence_digest'] and not found:
        found.append('evidence_changed')
    return found


def csv_report(items):
    fields = ['provider', 'scope_id', 'resource_name', 'resource_type', 'resource_group', 'resource_id', 'service_category',
              'rule_ids', 'review_priority', 'disposition', *PILLARS, 'billed_cost_usd', 'effective_cost_usd', 'retail_estimate_usd', 'lifecycle_delta', 'ai_status', 'ai_risk',
              'ai_summary', 'decision', 'decision_at', 'evidence_digest']

    def cell(value):
        text = '' if value is None else str(value)
        return "'" + text if re.match(r"^\s*[=+@-]|^[\t\r\n]", text) else text

    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\r\n')
    writer.writerow(fields)
    for item in items:
        decision = item['decision'] or {}
        values = dict({k: item[k] for k in fields if k in item}, rule_ids=';'.join(item['rule_ids']),
                      **{p: item['pillars'][p] for p in PILLARS}, ai_status=item['ai']['status'],
                      ai_risk=item['ai']['risk_level'], ai_summary=item['ai']['summary'],
                      decision=decision.get('decision'), decision_at=decision.get('created_at'))
        writer.writerow([cell(values.get(f)) for f in fields])
    return '\ufeff' + out.getvalue()


def lifecycle(current, previous):
    """Compare only an already authorized, comparable saved observation."""
    if previous is None:return {key:'new' for key in current},dict(comparison_scan_id=None,resolved_count=None,no_longer_observed_count=None)
    older=assessments(previous)
    states={key:'new' if key not in older else 'regressed' if set(value[0]['rule_ids'])-set(older[key][0]['rule_ids']) or set(value[0]['risk_check_codes'])-set(older[key][0]['risk_check_codes']) else 'persisting' for key,value in current.items()}
    resolved=sum(bool(value[0]['rule_ids']) and key in current and not current[key][0]['rule_ids'] for key,value in older.items())
    return states,dict(comparison_scan_id=previous['scan_id'],resolved_count=resolved,no_longer_observed_count=len(set(older)-set(current)))


def planning_summary(scan):
    """Run clean-before-commit math automatically only over saved homogeneous hourly evidence."""
    from app.commitment_arbitrage import calculate_clean_commitment_baseline,hourly_p10
    from app.nextgen_engines import hourly_profile
    result=dict(status='insufficient_evidence',purchase_authorized=False,clean_steady_state_hr=None,recommended_new_commitment_hr=None,
        warning='A monthly total cannot establish a steady hourly commitment floor. Complete hourly billing, compatible cleanup and existing-commitment coverage are required.')
    evidence=scan.get('commitment_evidence')
    if not isinstance(evidence,dict) or evidence.get('source_verified') is not True:return result
    try:
        hours=hourly_profile(evidence['usage_series'])
        clean=hourly_profile(evidence['cleanup_series'])
        if hours[:2]!=clean[:2] or evidence.get('commitment_coverage_verified') is not True:return result
        # Compute the percentile after hour-by-hour cleanup, avoiding percentile subtraction.
        if any(w>v for v,w in zip(hours[2],clean[2])):return result
        values=[format(v-w,'f') for v,w in zip(hours[2],clean[2])]
        result=calculate_clean_commitment_baseline(hourly_p10(values),'0',evidence['existing_commitments_hr'])
        return dict(result,status='modeled_saved_hourly_evidence',verified_realized_savings_usd=None)
    except (ValueError,TypeError,KeyError):return result
