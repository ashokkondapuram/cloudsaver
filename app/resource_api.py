"""Per-resource analysis, AI batches, follow-up questions and reviewer decisions."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from app.ai_advisory import AIError
from app.auth import Role, require_workspace_role
from app.cloud_scope import validate_finding_scope
from app.schemas import bounded_json
from app.inference_ledger import attribution
from app.resource_assessment import (FILTERS, ai_state, assessments, assess_resource, csv_report, decision_state, group, history,
                                     inventory_observation, merge, merge_inventory, observation_arm_detail,
                                     observation_list_extras, overlay_inventory_billing, planning_summary, matches,
                                     prepare_observation, rebuild_assessment_from_observation, resource_key, row,
                                     scan_indexes, summarize_resource_rows)
from app.resource_store import ResourceConflict, ResourceStore

KEY = r'^[a-f0-9]{64}$'
MAX_BATCH = 500
MAX_QUESTIONS = 5


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    resource_keys: list[str] | None = Field(None, min_length=1, max_length=MAX_BATCH)
    all: StrictBool = False
    target_id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    idempotency_key: UUID
    acknowledge_external_processing: StrictBool


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    question: str = Field(min_length=3, max_length=500)
    target_id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    evidence_digest: str = Field(pattern=KEY)
    idempotency_key: UUID
    acknowledge_external_processing: StrictBool


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    scan_id: UUID
    decision: Literal['accept', 'dismiss', 'defer']
    note: str = Field('', max_length=1000)
    defer_until: date | None = None
    evidence_digest: str = Field(pattern=KEY)


class SignalIdentity(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    provider: str = Field(pattern=r'^(azure|aws|gcp|kubernetes)$')
    resource_id: str = Field(min_length=1, max_length=500)


class SignalLookupRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    identities: list[SignalIdentity] = Field(min_length=1, max_length=500)


async def payload(request, schema):
    try:
        # UUID and date parsing from JSON is intentional even though the remaining model is strict.
        return schema.model_validate_json(json.dumps(await bounded_json(request)))
    except ValidationError:
        raise HTTPException(422, 'Invalid request; check the selected resources and required fields') from None


def actor_for(tenant):
    return hashlib.sha256((tenant.get('user_id') or 'workspace-key:' + tenant['tenant_id']).encode()).hexdigest()


def create_router(settings, store, current_tenant, gateway, evidence_store):
    router = APIRouter(prefix='/api/v1')
    repo = ResourceStore(evidence_store)
    from app.inference_ledger import InferenceLedger
    ledger = InferenceLedger(evidence_store)

    def refresh_observation_if_stale(tenant, scan_id, observation):
        if not observation:
            return observation
        scan = store.get(tenant['tenant_id'], str(scan_id))
        if scan is None:
            return observation
        from app.effective_rules import policy_for_tenant
        from app.resource_refresh import maybe_refresh_observation

        return maybe_refresh_observation(
            tenant,
            scan,
            observation,
            store=store,
            policies=policy_for_tenant(tenant['tenant_id']),
        )

    def overlay_obs(tenant, scan_id, observation):
        from app.resources_redis import apply_scan_resource

        return apply_scan_resource(tenant['tenant_id'], str(scan_id), observation)

    def overlay_page(tenant, scan_id, observations, findings_by_key):
        from app.resources_redis import apply_scan_resources_page

        return apply_scan_resources_page(tenant['tenant_id'], str(scan_id), observations, findings_by_key)

    def owned(scan_id, tenant):
        scan = store.get(tenant['tenant_id'], str(scan_id))
        if scan is None:
            raise HTTPException(404, 'Scan not found')
        if scan['status'] not in ('completed', 'running') or scan.get('data_origin') == 'legacy_synthetic':
            raise HTTPException(409, 'Resource evidence requires a live scan snapshot')
        if scan['status'] == 'completed':
            try:
                for finding in scan['findings']:
                    validate_finding_scope(finding, tenant)
            except (ValueError, KeyError):
                raise HTTPException(409, 'The saved scan is outside the current workspace scope') from None
            from app.focus import FocusRepository
            return FocusRepository(evidence_store).attach(tenant, scan)
        return scan

    def inventory(scan, tenant, *, cost_scope='billable'):
        merged = assessments(scan, list_view=True)
        from app.resource_assessment import lifecycle
        from app.billable_resources import include_in_cost_workspace
        previous = None
        if scan['status'] != 'running':
            history = store.list_light(tenant['tenant_id'], 100) if hasattr(store, 'list_light') else store.list(tenant['tenant_id'], 100)
            previous = next(
                (
                    s
                    for s in history
                    if s['status'] == 'completed'
                    and s.get('data_origin') != 'legacy_synthetic'
                    and s['scan_id'] != scan['scan_id']
                    and s['timestamp'] < scan['timestamp']
                    and s.get('scope_fingerprint')
                    and s.get('scope_fingerprint') == scan.get('scope_fingerprint')
                ),
                None,
            )
        deltas, comparison = lifecycle(merged, previous)
        scan['_lifecycle_comparison']=comparison
        keys = set(merged)
        findings_by_key, _ = scan_indexes(scan)
        inventory_by_key = {}
        for obs in scan.get('inventory') or []:
            pseudo = inventory_observation(obs)
            inventory_by_key[resource_key(pseudo)] = obs
        from app.resources_redis import apply_scan_inventory_map

        inventory_by_key, findings_by_key = apply_scan_inventory_map(
            tenant['tenant_id'],
            scan['scan_id'],
            inventory_by_key,
            findings_by_key,
        )
        if scan['status'] == 'running':
            results, decisions = {}, {}
            states = {}
        else:
            results = repo.results(tenant['tenant_id'], keys)
            states = repo.item_states(tenant['tenant_id'], scan['scan_id'])
            decisions = repo.latest_decisions(tenant['tenant_id'], keys)
        items = []
        observed_at = scan.get('timestamp')
        for key, (_, _) in merged.items():
            obs = inventory_by_key.get(key)
            findings = findings_by_key.get(key, [])
            if obs and findings:
                assessment, _ = merge(
                    key,
                    findings,
                    observed_at=observed_at,
                    list_view=True,
                    observation=obs,
                )
            elif obs:
                assessment, _ = merge_inventory(key, obs, observed_at=observed_at, list_view=True)
            else:
                assessment, _ = merged[key]
            arm_detail = observation_arm_detail(obs)
            row_item = dict(row(assessment), lifecycle_delta=deltas[key], ai=ai_state(assessment, results.get(key), states.get(key)),
                              decision=decision_state(assessment, decisions.get(key)), arm_detail=arm_detail,
                              **observation_list_extras(obs))
            if cost_scope == 'billable' and not include_in_cost_workspace(row_item, observation=inventory_by_key.get(key)):
                continue
            items.append(row_item)
        order = {'critical': 0, 'high': 1, 'evidence_required': 2}
        items.sort(key=lambda i: (order[i['review_priority']], -(i['retail_estimate_usd'] or 0), i['resource_name'], i['resource_key']))
        return merged, items

    def filtered(items, filters, search, *, arm_detail=None):
        needle = (search or '').casefold()
        selected = [i for i in items if matches(i, filters) and (not needle or needle in (i['resource_name'] + ' ' + i['resource_id']).casefold())]
        if arm_detail:
            selected = [i for i in selected if i.get('arm_detail') == arm_detail]
        return selected

    def one(scan, key):
        pair = assess_resource(scan, key, list_view=False)
        if pair is None:
            raise HTTPException(404, 'Resource not found in this scan')
        findings_by_key, _ = scan_indexes(scan)
        return findings_by_key.get(key, []), *pair

    def resolve_resource_identity(scan_id, tenant, key):
        offset = 0
        limit = 100
        while offset < 10000:
            snap = store.running_inventory_page(tenant['tenant_id'], str(scan_id), offset=offset, limit=limit)
            if snap is None:
                return None
            for obs in snap.get('inventory') or []:
                pseudo = inventory_observation(obs)
                if resource_key(pseudo) == key:
                    return pseudo.get('cloud_provider', 'azure'), pseudo['resource_id']
            offset += limit
            if offset >= snap['inventory_total']:
                break
        return None

    def resource_from_bundle(scan_id, tenant, key, provider, resource_id):
        bundle = store.scan_resource_bundle(tenant['tenant_id'], str(scan_id), provider, resource_id)
        if bundle is None:
            raise HTTPException(404, 'Scan not found')
        if bundle['status'] not in ('completed', 'running') or bundle.get('data_origin') == 'legacy_synthetic':
            raise HTTPException(409, 'Resource evidence requires a live scan snapshot')
        observation = bundle.get('observation')
        findings = list(bundle.get('findings') or [])
        if observation:
            from app.resources_redis import apply_scan_resource_bundle

            observation, findings = apply_scan_resource_bundle(tenant['tenant_id'], str(scan_id), observation, findings)
            observation = refresh_observation_if_stale(tenant, scan_id, observation)
            bundle = store.scan_resource_bundle(tenant['tenant_id'], str(scan_id), provider, resource_id) or bundle
            observation, findings = apply_scan_resource_bundle(
                tenant['tenant_id'],
                str(scan_id),
                bundle.get('observation') or observation,
                list(bundle.get('findings') or findings),
            )
        if not findings and hasattr(store, 'findings_for_resource'):
            findings = store.findings_for_resource(tenant['tenant_id'], str(scan_id), provider, resource_id)
        elif not findings and hasattr(store, 'findings_for_resource_key'):
            findings = store.findings_for_resource_key(tenant['tenant_id'], str(scan_id), key)
        if not observation and not findings:
            raise HTTPException(404, 'Resource not found in this scan')
        if observation:
            expected = resource_key(inventory_observation(observation))
        else:
            expected = resource_key(findings[0])
        if expected != key:
            raise HTTPException(404, 'Resource not found in this scan')
        if bundle['status'] == 'completed':
            try:
                for finding in findings:
                    validate_finding_scope(finding, tenant)
            except (ValueError, KeyError):
                raise HTTPException(409, 'The saved scan is outside the current workspace scope') from None
        full_scan = store.get(tenant['tenant_id'], str(scan_id))
        stub = dict(
            scan_id=bundle['scan_id'],
            timestamp=bundle['timestamp'],
            status=bundle['status'],
            findings=findings,
            inventory=[observation] if observation else [],
            rule_evaluations=bundle.get('rule_evaluations') or [],
            pillar_analysis=(full_scan or {}).get('pillar_analysis'),
        )
        from app.focus import FocusRepository
        stub = FocusRepository(evidence_store).attach(tenant, stub)
        findings = list(stub.get('findings') or [])
        observation = (stub.get('inventory') or [None])[0] if observation else None
        pair = assess_resource(stub, key, list_view=False)
        if pair is None:
            raise HTTPException(404, 'Resource not found in this scan')
        assessment, context = pair
        findings_by_key, _ = scan_indexes(stub)
        findings = findings_by_key.get(key, [])
        scan = dict(stub, findings=findings)
        return scan, findings, assessment, context, observation

    def resource_payload(scan_id, scan, findings, assessment, context, observation, resource_key, tenant):
        if observation:
            observation = prepare_observation(observation)
            assessment, context = rebuild_assessment_from_observation(
                scan,
                resource_key,
                findings,
                observation,
                list_view=False,
            )
        result = repo.results(tenant['tenant_id'], {resource_key}).get(resource_key)
        state = repo.item_states(tenant['tenant_id'], scan['scan_id']).get(resource_key)
        decision = repo.latest_decisions(tenant['tenant_id'], {resource_key}).get(resource_key)
        followups = repo.followups(tenant['tenant_id'], scan['scan_id'], resource_key)
        from app.rule_detail import build_resource_rule_detail, evaluations_for_resource, normalize_resource_id

        provider = assessment['provider']
        selected_id = normalize_resource_id(provider, assessment['resource_id'])
        evaluations = evaluations_for_resource(
            scan.get('rule_evaluations') or [],
            provider=provider,
            resource_id=assessment['resource_id'],
        )
        from app.provider_rules import provider_label, rule_provider

        evaluation_groups = []
        buckets: dict[str, list] = {}
        for row in evaluations:
            bucket = row.get('cloud_provider') or rule_provider(row.get('rule_id', ''))
            buckets.setdefault(bucket, []).append(row)
        for bucket, rows in sorted(buckets.items()):
            evaluation_groups.append(
                dict(provider=bucket, label=f'{provider_label(bucket)} analysis rules', evaluations=rows)
            )
        groups = {row['opportunity_group_id'] for row in findings if row.get('opportunity_group_id')}
        opportunity_group_id = next(iter(groups), None) if len(groups) == 1 else None
        rule_detail = build_resource_rule_detail(
            assessment,
            findings,
            evaluations,
            observation,
            opportunity_group_id=opportunity_group_id,
        )
        overlaps = [dict(resource_id=row['resource_id'], resource_name=row.get('resource_name'), rule_id=row['rule_id'])
                    for row in scan['findings'] if row.get('opportunity_group_id') in groups and normalize_resource_id(provider, row['resource_id']) != selected_id]
        from app.pricing import opportunity_totals
        from app.financial_balance import resource_financial_balance
        billed_currency = assessment.get('currency')
        opportunity = opportunity_totals(findings)
        balance = resource_financial_balance(
            billed_cost_usd=assessment.get('billed_cost_usd'),
            effective_cost_usd=assessment.get('effective_cost_usd'),
            retail_run_rate_usd=assessment.get('retail_estimate_usd'),
            opportunity=opportunity,
        )
        costs = dict(
            billed_cost_usd=assessment.get('billed_cost_usd'),
            effective_cost_usd=assessment.get('effective_cost_usd'),
            retail_estimate_usd=assessment['retail_estimate_usd'],
            modeled_future_cost_usd=None,
            opportunity_usd=balance['retail_waste_opportunity_usd'],
            verified_realized_savings_usd=None,
            currency=billed_currency or 'USD',
            **balance,
            explanation=(
                'Billed/effective are FOCUS or Cost Management imports for the scan billing window. '
                'Retail run-rate and waste use Azure retail meters (USD list); waste is not verified savings. '
                'Balance fields compare billed payable to catalog run-rate and modeled waste.'
            ),
        )
        obs_evidence = ((observation or {}).get('evidence') or {}) if observation else {}
        configuration_detail = obs_evidence.get('typed_configuration') or (observation or {}).get('configuration_snapshot')
        region = assessment.get('region') or ((observation or {}).get('region') if observation else None) or ((observation or {}).get('location') if observation else None)
        assessment_payload = dict(assessment, arm_detail=observation_arm_detail(observation), region=region)
        if obs_evidence.get('drift_detected') and 'drift_detected' not in assessment_payload:
            assessment_payload['drift_detected'] = True
        from app.resource_action_items import derive_action_items

        action_items = (observation or {}).get('recommendations') if observation else None
        if not action_items:
            action_items = derive_action_items(assessment, findings, evaluations)
        from app.evidence_extraction import attach_action_item_evidence, attach_check_evidence
        from app.pillar_analysis_api import pillar_scores_for_resource

        assessment_payload = attach_check_evidence(dict(assessment_payload), observation)
        action_items = attach_action_item_evidence(action_items, assessment_payload, observation)
        live_sources = obs_evidence.get('live_sources') or {}
        azure_governance = None
        if provider == 'azure':
            azure_governance = dict(
                policy_states=obs_evidence.get('azure_policy_states') or [],
                advisor_recommendations=obs_evidence.get('azure_advisor_recommendations') or [],
                collection=dict(
                    azure_policy=live_sources.get('azure_policy'),
                    advisor=live_sources.get('advisor'),
                ),
            )
        pillar_scores = pillar_scores_for_resource(scan, provider, assessment['resource_id'])
        payload = dict(
            scan_id=scan['scan_id'],
            assessment=assessment_payload,
            findings=findings,
            ai_context=context,
            ai=ai_state(assessment, result, state),
            ai_result=result['response'] if result else None,
            decision=decision_state(assessment, decision),
            followups=followups,
            followups_remaining=max(0, MAX_QUESTIONS - len(followups)),
            observation=observation,
            configuration_detail=configuration_detail,
            evidence_schema_version=obs_evidence.get('evidence_schema_version')
            or (observation or {}).get('evidence_schema_version'),
            rule_evaluations=evaluations,
            rule_evaluation_groups=evaluation_groups,
            costs=costs,
            financial_overlaps=overlaps,
            rule_matches=rule_detail['rule_matches'],
            rule_conflicts=rule_detail['rule_conflicts'],
            reconciliation_status=rule_detail.get('reconciliation_status'),
            action_items=action_items,
            observability=next(
                (
                    r.get('evidence', {}).get('observed_signals')
                    for r in [observation or {}, *findings]
                    if r.get('evidence', {}).get('observed_signals')
                ),
                None,
            ),
            fetch_stages=obs_evidence.get('fetch_stages'),
            azure_governance=azure_governance,
            **observation_list_extras(observation),
        )
        if pillar_scores is not None:
            payload['pillar_scores'] = pillar_scores
        return payload

    def query_filters(provider, service_category, review_priority, ai_status, ai_risk, decision, pillar_status):
        return dict(zip(FILTERS, (provider, service_category, review_priority, ai_status, ai_risk, decision, pillar_status)))

    def inventory_db_page(scan_id, tenant, *, cost_scope, limit, offset, arm_detail=None):
        """Serve one inventory slice from Postgres without loading the full scan payload."""
        from app.billable_resources import include_in_cost_workspace

        def observation_rows(observations, findings_by_key, observed_at):
            observations, findings_by_key = overlay_page(tenant, scan_id, observations, findings_by_key)
            rows = []
            for obs in observations:
                pseudo = inventory_observation(obs)
                key = resource_key(pseudo)
                grouped = findings_by_key.get(key) or []
                if grouped:
                    assessment, _ = merge(
                        key,
                        grouped,
                        observed_at=observed_at,
                        list_view=True,
                        observation=obs,
                    )
                else:
                    assessment, _ = merge_inventory(key, obs, observed_at=observed_at, list_view=True)
                row_item = dict(
                    row(assessment),
                    lifecycle_delta='new',
                    ai=ai_state(assessment, None, None),
                    decision=None,
                    arm_detail=observation_arm_detail(obs),
                    **observation_list_extras(obs),
                )
                if cost_scope == 'billable' and not include_in_cost_workspace(row_item, observation=obs):
                    continue
                rows.append(row_item)
            return rows

        def attach_focus(stub):
            from app.focus import FocusRepository
            return FocusRepository(evidence_store).attach(tenant, stub)

        if arm_detail:
            chunk = max(limit, 100)
            filtered_obs = []
            snap = None
            inv_offset = 0
            inventory_total = 0
            while inv_offset < 10000:
                page_snap = store.running_inventory_page(tenant['tenant_id'], str(scan_id), offset=inv_offset, limit=chunk)
                if page_snap is None:
                    raise HTTPException(404, 'Scan not found')
                if page_snap.get('status') not in ('running', 'completed') or page_snap.get('data_origin') == 'legacy_synthetic':
                    return None
                inventory_total = int(page_snap.get('inventory_total') or 0)
                if snap is None:
                    snap = dict(
                        scan_id=page_snap['scan_id'],
                        status=page_snap.get('status'),
                        timestamp=page_snap.get('timestamp'),
                        data_origin=page_snap.get('data_origin'),
                        findings=list(page_snap.get('findings') or []),
                        inventory_total=inventory_total,
                    )
                for obs in page_snap.get('inventory') or []:
                    if observation_arm_detail(obs) == arm_detail:
                        filtered_obs.append(obs)
                inv_offset += chunk
                if inv_offset >= inventory_total:
                    break
            if snap is None:
                raise HTTPException(404, 'Scan not found')
            if snap['status'] == 'completed' and not snap.get('inventory_total'):
                return None
            if snap['status'] == 'completed':
                try:
                    for finding in snap['findings']:
                        validate_finding_scope(finding, tenant)
                except (ValueError, KeyError):
                    raise HTTPException(409, 'The saved scan is outside the current workspace scope') from None
                focused = attach_focus(dict(
                    scan_id=snap['scan_id'],
                    timestamp=snap['timestamp'],
                    status='completed',
                    findings=snap['findings'],
                    inventory=filtered_obs,
                ))
                snap = dict(snap, findings=focused['findings'])
            findings_by_key = group(snap['findings'])
            observed_at = snap.get('timestamp')
            all_items = observation_rows(filtered_obs, findings_by_key, observed_at)
            total = len(all_items)
            items = all_items[offset:offset + limit]
            summary_payload = summarize_resource_rows(all_items)
        else:
            snap = store.running_inventory_page(tenant['tenant_id'], str(scan_id), offset=offset, limit=limit)
            if snap is None:
                raise HTTPException(404, 'Scan not found')
            if snap.get('status') not in ('running', 'completed') or snap.get('data_origin') == 'legacy_synthetic':
                return None
            if snap['status'] == 'completed' and not snap.get('inventory_total'):
                return None
            if snap['status'] == 'completed':
                try:
                    for finding in snap['findings']:
                        validate_finding_scope(finding, tenant)
                except (ValueError, KeyError):
                    raise HTTPException(409, 'The saved scan is outside the current workspace scope') from None
                focused = attach_focus(dict(
                    scan_id=snap['scan_id'],
                    timestamp=snap['timestamp'],
                    status='completed',
                    findings=snap['findings'],
                    inventory=snap['inventory'],
                ))
                snap = dict(snap, findings=focused['findings'], inventory=focused.get('inventory') or snap['inventory'])
            findings_by_key = group(snap['findings'])
            observed_at = snap.get('timestamp')
            inventory_by_key = {
                resource_key(inventory_observation(o)): o for o in (snap.get('inventory') or [])
            }
            items = observation_rows(snap['inventory'], findings_by_key, observed_at)
            total = snap['inventory_total']
            review_priority = {'critical': 0, 'high': 0, 'evidence_required': 0}
            for key, grouped in findings_by_key.items():
                if not grouped:
                    continue
                assessment, _ = merge(
                    key,
                    grouped,
                    observed_at=observed_at,
                    list_view=True,
                    observation=inventory_by_key.get(key),
                )
                review_priority[assessment['review_priority']] = review_priority.get(assessment['review_priority'], 0) + 1
            review_priority['evidence_required'] += max(0, snap['inventory_total'] - len(findings_by_key))
            summary_payload = dict(
                total=total,
                ai_status={'not_run': total} if total else {},
                ai_risk={'none': total} if total else {},
                decision={'none': total} if total else {},
                review_priority={k: v for k, v in review_priority.items() if v} or ({'evidence_required': total} if total else {}),
                comparison_scan_id=None,
                resolved_count=None,
                no_longer_observed_count=None,
            )
        if snap['status'] == 'completed' and items:
            keys = {item['resource_key'] for item in items}
            results = repo.results(tenant['tenant_id'], keys)
            states = repo.item_states(tenant['tenant_id'], snap['scan_id'])
            decisions = repo.latest_decisions(tenant['tenant_id'], keys)
            items = [
                dict(
                    item,
                    ai=ai_state(item, results.get(item['resource_key']), states.get(item['resource_key'])),
                    decision=decision_state(item, decisions.get(item['resource_key'])),
                )
                for item in items
            ]
        baseline = (
            planning_summary(dict(scan_id=snap['scan_id'], timestamp=snap['timestamp'], status='completed'))
            if snap['status'] == 'completed'
            else dict(
                status='insufficient_evidence',
                purchase_authorized=False,
                clean_steady_state_hr=None,
                recommended_new_commitment_hr=None,
                warning='Commitment baseline is available after the scan completes.',
            )
        )
        return dict(
            scan_id=snap['scan_id'],
            observed_at=observed_at,
            summary=summary_payload,
            commitment_baseline=baseline,
            total=total,
            items=items,
        )

    def inventory_running_page(scan_id, tenant, *, cost_scope, limit, offset, arm_detail=None):
        """Backward-compatible alias for running scans."""
        return inventory_db_page(scan_id, tenant, cost_scope=cost_scope, limit=limit, offset=offset, arm_detail=arm_detail)

    filter_params = dict(
        provider=Query(None, pattern=r'^(azure|aws|gcp|kubernetes)$'), service_category=Query(None, max_length=40),
        review_priority=Query(None, pattern=r'^(critical|high|evidence_required)$'),
        ai_status=Query(None, pattern=r'^(not_run|queued|running|completed|stale|failed)$'),
        ai_risk=Query(None, pattern=r'^(low|medium|high|critical|none)$'),
        decision=Query(None, pattern=r'^(accept|dismiss|defer|none)$'),pillar_status=Query(None,pattern=r'^(observed|risk|unknown)$'),
        arm_detail=Query(None, pattern=r'^(collected|unsupported_type|resource_budget_exceeded|api_version_unresolved|fetch_failed)$'))

    @router.get('/resources/billable-catalog')
    def billable_catalog_route(tenant=Depends(current_tenant)):
        from app.billable_resources import billable_catalog
        return billable_catalog()

    @router.get('/catalog/azure-resource-types')
    def azure_resource_type_catalog(tenant=Depends(current_tenant)):
        from app.azure_resource_registry import catalog_entries
        return dict(items=catalog_entries(), evidence_schema_version='3')

    @router.get('/catalog/typed-resource-tables')
    def typed_resource_tables(tenant=Depends(current_tenant)):
        from app.typed_resources.persist import list_tables
        return dict(items=list_tables(), cost_columns=[
            'reporting_currency', 'cost_period_start', 'cost_period_end',
            'azure_billed', 'azure_effective', 'azure_list',
            'cost_center_billed', 'cost_center_effective', 'cost_center_list',
        ])

    @router.post('/scans/{scan_id}/resource-signals/lookup')
    async def resource_signals_lookup(scan_id: UUID, request: Request, tenant=Depends(current_tenant)):
        """Lightweight AI and decision state for findings grids without loading the full resource catalog."""
        body = await payload(request, SignalLookupRequest)
        scan = owned(scan_id, tenant)
        findings_by_key, inventory_by_key = scan_indexes(scan)
        keyed = {}
        for ident in body.identities:
            key = resource_key(dict(cloud_provider=ident.provider, resource_id=ident.resource_id))
            keyed[key] = dict(provider=ident.provider, resource_id=ident.resource_id)

        merged = {}
        for key in keyed:
            pair = assess_resource(
                scan,
                key,
                list_view=False,
                findings_by_key=findings_by_key,
                inventory_by_key=inventory_by_key,
            )
            if pair is not None:
                merged[key] = pair

        key_set = set(keyed) & set(merged)
        if scan['status'] == 'running':
            results, states, decisions = {}, {}, {}
        else:
            results = repo.results(tenant['tenant_id'], key_set)
            states = repo.item_states(tenant['tenant_id'], scan['scan_id'])
            decisions = repo.latest_decisions(tenant['tenant_id'], key_set)

        items = []
        for key, meta in keyed.items():
            if key in merged:
                assessment, _context = merged[key]
            else:
                assessment = dict(
                    provider=meta['provider'],
                    resource_id=meta['resource_id'],
                    evidence_digest='0' * 64,
                )
            items.append(dict(
                resource_key=key,
                provider=meta['provider'],
                resource_id=assessment.get('resource_id') or meta['resource_id'],
                ai=ai_state(assessment, results.get(key), states.get(key)),
                decision=decision_state(assessment, decisions.get(key)),
            ))
        return dict(scan_id=str(scan_id), items=items)

    @router.get('/scans/{scan_id}/resources')
    def resources(scan_id: UUID, provider: str | None = filter_params['provider'],
                  service_category: str | None = filter_params['service_category'],
                  review_priority: str | None = filter_params['review_priority'], ai_status: str | None = filter_params['ai_status'],
                  ai_risk: str | None = filter_params['ai_risk'], decision: str | None = filter_params['decision'],pillar_status: str | None = filter_params['pillar_status'],
                  arm_detail: str | None = filter_params['arm_detail'],
                  cost_scope: str = Query('billable', pattern=r'^(billable|all)$'),
                  q: str | None = Query(None, max_length=200), limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                  tenant=Depends(current_tenant)):
        filters = query_filters(provider, service_category, review_priority, ai_status, ai_risk, decision, pillar_status)
        if not q and not any(filters.values()):
            page = inventory_db_page(scan_id, tenant, cost_scope=cost_scope, limit=limit, offset=offset, arm_detail=arm_detail)
            if page is not None:
                return page
        scan = owned(scan_id, tenant)
        _, items = inventory(scan, tenant, cost_scope=cost_scope)
        selected = filtered(items, filters, q, arm_detail=arm_detail)
        return dict(scan_id=scan['scan_id'], observed_at=scan.get('timestamp'), summary=dict(summarize_resource_rows(selected),**scan.get('_lifecycle_comparison',{})),commitment_baseline=planning_summary(scan),
                    total=len(selected), items=selected[offset:offset + limit])

    @router.get('/scans/{scan_id}/resources/export')
    def export(scan_id: UUID, provider: str | None = filter_params['provider'],
               service_category: str | None = filter_params['service_category'],
               review_priority: str | None = filter_params['review_priority'], ai_status: str | None = filter_params['ai_status'],
               ai_risk: str | None = filter_params['ai_risk'], decision: str | None = filter_params['decision'],pillar_status: str | None = filter_params['pillar_status'],
               arm_detail: str | None = filter_params['arm_detail'],
               q: str | None = Query(None, max_length=200),
               cost_scope: str = Query('billable', pattern=r'^(billable|all)$'), tenant=Depends(current_tenant)):
        scan = owned(scan_id, tenant)
        _, items = inventory(scan, tenant, cost_scope=cost_scope)
        selected = filtered(items, query_filters(provider, service_category, review_priority, ai_status, ai_risk, decision, pillar_status), q, arm_detail=arm_detail)
        return dict(filename=f"cloudsaver-resources-{scan['scan_id']}.csv", rows=len(selected), content=csv_report(selected))

    @router.get('/scans/{scan_id}/resources/{resource_key}')
    def resource(scan_id: UUID, resource_key: str = Path(pattern=KEY),
                  provider: str | None = Query(None, pattern=r'^(azure|aws|gcp|kubernetes)$'),
                  resource_id: str | None = Query(None, max_length=500),
                  tenant=Depends(current_tenant)):
        identity = (provider, resource_id) if provider and resource_id else resolve_resource_identity(scan_id, tenant, resource_key)
        if identity:
            scan, findings, assessment, context, observation = resource_from_bundle(
                scan_id, tenant, resource_key, identity[0], identity[1],
            )
            return resource_payload(scan_id, scan, findings, assessment, context, observation, resource_key, tenant)
        scan = owned(scan_id, tenant)
        findings_by_key, inventory_by_key = scan_indexes(scan)
        findings = list(findings_by_key.get(resource_key, []))
        observation = inventory_by_key.get(resource_key)
        if observation:
            from app.resources_redis import apply_scan_resource_bundle

            observation, findings = apply_scan_resource_bundle(tenant['tenant_id'], str(scan_id), observation, findings)
            observation = refresh_observation_if_stale(tenant, scan_id, observation)
            scan = store.get(tenant['tenant_id'], str(scan_id)) or scan
            findings_by_key, inventory_by_key = scan_indexes(scan)
            observation, findings = apply_scan_resource_bundle(
                tenant['tenant_id'],
                str(scan_id),
                inventory_by_key.get(resource_key) or observation,
                list(findings_by_key.get(resource_key, findings)),
            )
            observed_at = scan.get('timestamp')
            if findings:
                assessment, context = merge(resource_key, findings, observed_at=observed_at, list_view=False, observation=observation)
            else:
                assessment, context = merge_inventory(resource_key, observation, observed_at=observed_at, list_view=False)
        else:
            findings, assessment, context = one(scan, resource_key)
        return resource_payload(scan_id, scan, findings, assessment, context, observation, resource_key, tenant)

    @router.post('/scans/{scan_id}/ai-batches', status_code=202)
    async def create_batch(scan_id: UUID, request: Request, tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        body = await payload(request, BatchRequest)
        if body.acknowledge_external_processing is not True:
            raise HTTPException(422, 'Acknowledge external processing of the sanitized resource context')
        if body.all == (body.resource_keys is not None):
            raise HTTPException(422, 'Select resources or choose all resources, not both')
        targets = {t['target_id']: t for t in gateway.available(tenant)['targets']}
        if body.target_id not in targets:
            raise HTTPException(404, 'AI target is unavailable for this workspace')
        scan = owned(scan_id, tenant)
        if body.all:
            merged = assessments(scan)
            keys = sorted(merged)
        else:
            keys = list(dict.fromkeys(body.resource_keys))
            if any(not re.fullmatch(KEY, k) for k in keys):
                raise HTTPException(404, 'One or more selected resources are not in this scan')
            findings_by_key, inventory_by_key = scan_indexes(scan)
            merged = {}
            for key in keys:
                pair = assess_resource(
                    scan,
                    key,
                    findings_by_key=findings_by_key,
                    inventory_by_key=inventory_by_key,
                )
                if pair is None:
                    raise HTTPException(404, 'One or more selected resources are not in this scan')
                merged[key] = pair
        if not 1 <= len(keys) <= MAX_BATCH:
            raise HTTPException(422, f'A batch must include between 1 and {MAX_BATCH} resources')
        allowed = set(targets[body.target_id]['allowed_source_providers'])
        if any(merged[k][0]['provider'] not in allowed for k in keys):
            raise HTTPException(403, 'AI target policy does not permit one or more selected source providers')
        try:
            return repo.create_batch(tenant['tenant_id'], scan_id=scan['scan_id'], target_id=body.target_id,
                                     request_key=str(body.idempotency_key), actor=actor_for(tenant),
                                     items=[(k, merged[k][0]['evidence_digest']) for k in keys])
        except ResourceConflict as error:
            raise HTTPException(409, str(error)) from None

    @router.get('/ai-batches')
    def list_batches(scan_id: UUID | None = None, limit: int = Query(20, ge=1, le=50), tenant=Depends(current_tenant)):
        from app.data_scope import scan_visible
        items = repo.batches(tenant['tenant_id'], scan_id=str(scan_id) if scan_id else None, limit=limit)
        items = [batch for batch in items if scan_visible(store, tenant, batch['scan_id'])]
        return dict(items=items, hourly_attempt_limit=gateway.limit)

    @router.get('/ai-batches/{batch_id}')
    def get_batch(batch_id: UUID, tenant=Depends(current_tenant)):
        from app.data_scope import scan_visible
        batch = repo.batch(tenant['tenant_id'], str(batch_id))
        if batch is None or not scan_visible(store, tenant, batch['scan_id']):
            raise HTTPException(404, 'Batch not found')
        return batch

    @router.post('/ai-batches/{batch_id}/cancel')
    def cancel_batch(batch_id: UUID, tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        from app.data_scope import scan_visible
        existing = repo.batch(tenant['tenant_id'], str(batch_id))
        if existing is None or not scan_visible(store, tenant, existing['scan_id']):
            raise HTTPException(404, 'Batch not found')
        batch = repo.cancel(tenant['tenant_id'], str(batch_id))
        if batch is None:
            raise HTTPException(404, 'Batch not found')
        return batch

    @router.post('/scans/{scan_id}/resources/{resource_key}/questions')
    async def ask(scan_id: UUID, request: Request, resource_key: str = Path(pattern=KEY), tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        body = await payload(request, QuestionRequest)
        if body.acknowledge_external_processing is not True:
            raise HTTPException(422, 'Acknowledge external processing of the question and sanitized resource context')
        question = ' '.join(body.question.split())
        if len(question) < 3:
            raise HTTPException(422, 'Enter a question of at least 3 characters')
        scan = owned(scan_id, tenant)
        findings, assessment, context = one(scan, resource_key)
        if body.evidence_digest != assessment['evidence_digest']:
            raise HTTPException(409, 'Resource evidence changed; refresh before asking a question')
        if repo.followup_count(tenant['tenant_id'], scan['scan_id'], resource_key) >= MAX_QUESTIONS:
            raise HTTPException(409, f'This resource has reached the limit of {MAX_QUESTIONS} questions for this scan')
        prior = repo.results(tenant['tenant_id'], {resource_key}).get(resource_key)
        message = dict(resource=context, question=question,
                       prior_advice=prior['response']['advice'] if prior and prior['evidence_digest'] == assessment['evidence_digest'] else None)
        from starlette.concurrency import run_in_threadpool
        try:
            result = await run_in_threadpool(gateway.review, tenant, body.target_id, body.idempotency_key, scan['scan_id'],
                                             message, assessment, kind='followup', attribution=attribution(findings[0]))
        except AIError as error:
            raise HTTPException(error.status, str(error), headers={'Retry-After': '3600'} if error.status == 429 else None) from None
        repo.add_followup(tenant['tenant_id'], scan_id=scan['scan_id'], key=resource_key, attempt_id=result['assessment_id'],
                          question=question, actor=actor_for(tenant))
        followups = repo.followups(tenant['tenant_id'], scan['scan_id'], resource_key)
        return dict(answer=result['advice'], assessment_id=result['assessment_id'], followups=followups,
                    followups_remaining=max(0, MAX_QUESTIONS - len(followups)))

    @router.get('/resources/{resource_key}/history')
    def resource_history(resource_key: str = Path(pattern=KEY), tenant=Depends(current_tenant)):
        scans = [s for s in store.list(tenant['tenant_id'], 25)
                 if s.get('status') == 'completed' and s.get('data_origin') != 'legacy_synthetic'][:10]
        return dict(scans=history(scans, resource_key), ai_results=repo.result_history(tenant['tenant_id'], resource_key),
                    decisions=repo.decisions(tenant['tenant_id'], resource_key, 20))

    @router.get('/resources/{resource_key}/decisions')
    def decisions(resource_key: str = Path(pattern=KEY), tenant=Depends(current_tenant)):
        from app.data_scope import scan_visible
        items = [row for row in repo.decisions(tenant['tenant_id'], resource_key)
                 if scan_visible(store, tenant, row['scan_id'])]
        return dict(items=items)

    @router.post('/resources/{resource_key}/decisions', status_code=201)
    async def decide(request: Request, resource_key: str = Path(pattern=KEY), tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        body = await payload(request, DecisionRequest)
        today = datetime.now(timezone.utc).date()
        if body.decision == 'defer':
            if body.defer_until and not today < body.defer_until <= today + timedelta(days=365):
                raise HTTPException(422, 'Choose a defer date within the next 365 days')
        elif body.defer_until:
            raise HTTPException(422, 'Only deferred decisions can have a defer date')
        if body.decision in ('dismiss', 'defer') and not body.note.strip():
            raise HTTPException(422, 'Add a note explaining this decision')
        scan = owned(body.scan_id, tenant)
        _, assessment, _ = one(scan, resource_key)
        if body.evidence_digest != assessment['evidence_digest']:
            raise HTTPException(409, 'Resource evidence changed; refresh before recording a decision')
        return repo.decide(tenant['tenant_id'], key=resource_key, scan_id=scan['scan_id'], decision=body.decision,
                           note=body.note.strip(), defer_until=body.defer_until, evidence_digest=assessment['evidence_digest'],
                           actor=actor_for(tenant))

    @router.get('/ai/targets')
    def ai_targets(tenant=Depends(current_tenant)):
        return gateway.available(tenant)

    @router.get('/ai/assessments')
    def assessment_history(limit: int = Query(25,ge=1,le=50), before: UUID | None = None,
                           scan_id: UUID | None = None, resource_reference: str | None = Query(None,pattern=r'^[a-f0-9]{64}$'),
                           tenant=Depends(current_tenant)):
        try:
            return ledger.page(tenant,limit,str(before) if before else None,str(scan_id) if scan_id else None,resource_reference)
        except AIError as error:
            raise HTTPException(error.status,str(error)) from None

    @router.get('/ai/assessments/{assessment_id}')
    def assessment_record(assessment_id: UUID,tenant=Depends(current_tenant)):
        result=ledger.get(tenant,str(assessment_id))
        if result is None:
            raise HTTPException(404,'Assessment not found')
        return result

    @router.get('/ai/usage')
    def usage(days: int = Query(30,ge=1,le=90),tenant=Depends(current_tenant)):
        try:
            return ledger.usage(tenant,days)
        except AIError as error:
            raise HTTPException(error.status,str(error)) from None

    return router
