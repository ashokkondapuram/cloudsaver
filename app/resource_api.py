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
from app.resource_assessment import (FILTERS, ai_state, assessments, csv_report, decision_state, group, history,
                                     inventory_observation, merge_inventory, planning_summary,
                                     matches, merge, resource_key, row)
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

    def owned(scan_id, tenant):
        scan = store.get(tenant['tenant_id'], str(scan_id))
        if scan is None:
            raise HTTPException(404, 'Scan not found')
        if scan['status'] != 'completed' or scan.get('data_origin') == 'legacy_synthetic':
            raise HTTPException(409, 'Analysis requires a completed live scan observation')
        try:
            for finding in scan['findings']:
                validate_finding_scope(finding, tenant)
        except (ValueError, KeyError):
            raise HTTPException(409, 'The saved scan is outside the current workspace scope') from None
        from app.focus import FocusRepository
        return FocusRepository(evidence_store).attach(tenant, scan)

    def inventory(scan, tenant):
        merged = assessments(scan)
        from app.resource_assessment import lifecycle
        previous=next((s for s in store.list(tenant['tenant_id'],100) if s['status']=='completed' and s.get('data_origin')!='legacy_synthetic' and s['scan_id']!=scan['scan_id'] and s['timestamp']<scan['timestamp'] and s.get('scope_fingerprint') and s.get('scope_fingerprint')==scan.get('scope_fingerprint')),None)
        deltas,comparison=lifecycle(merged,previous)
        scan['_lifecycle_comparison']=comparison
        keys = set(merged)
        results = repo.results(tenant['tenant_id'], keys)
        states = repo.item_states(tenant['tenant_id'], scan['scan_id'])
        decisions = repo.latest_decisions(tenant['tenant_id'], keys)
        items = []
        for key, (assessment, _) in merged.items():
            items.append(dict(row(assessment), lifecycle_delta=deltas[key], ai=ai_state(assessment, results.get(key), states.get(key)),
                              decision=decision_state(assessment, decisions.get(key))))
        order = {'critical': 0, 'high': 1, 'evidence_required': 2}
        items.sort(key=lambda i: (order[i['review_priority']], -(i['retail_estimate_usd'] or 0), i['resource_name'], i['resource_key']))
        return merged, items

    def filtered(items, filters, search):
        needle = (search or '').casefold()
        return [i for i in items if matches(i, filters) and (not needle or needle in (i['resource_name'] + ' ' + i['resource_id']).casefold())]

    def one(scan, key):
        pair=assessments(scan).get(key)
        if pair is None:raise HTTPException(404,'Resource not found in this scan')
        return group(scan['findings']).get(key,[]), *pair

    def summary(items):
        counts = lambda field: {k: sum(1 for i in items if field(i) == k) for k in sorted({field(i) for i in items})}
        return dict(total=len(items), ai_status=counts(lambda i: i['ai']['status']), ai_risk=counts(lambda i: i['ai']['risk_level'] or 'none'),
                    decision=counts(lambda i: (i['decision'] or {}).get('decision', 'none')),
                    review_priority=counts(lambda i: i['review_priority']))

    def query_filters(provider, service_category, review_priority, ai_status, ai_risk, decision, pillar_status):
        return dict(zip(FILTERS, (provider, service_category, review_priority, ai_status, ai_risk, decision, pillar_status)))

    filter_params = dict(
        provider=Query(None, pattern=r'^(azure|aws|gcp|kubernetes)$'), service_category=Query(None, max_length=40),
        review_priority=Query(None, pattern=r'^(critical|high|evidence_required)$'),
        ai_status=Query(None, pattern=r'^(not_run|queued|running|completed|stale|failed)$'),
        ai_risk=Query(None, pattern=r'^(low|medium|high|critical|none)$'),
        decision=Query(None, pattern=r'^(accept|dismiss|defer|none)$'),pillar_status=Query(None,pattern=r'^(observed|risk|unknown)$'))

    @router.get('/scans/{scan_id}/resources')
    def resources(scan_id: UUID, provider: str | None = filter_params['provider'],
                  service_category: str | None = filter_params['service_category'],
                  review_priority: str | None = filter_params['review_priority'], ai_status: str | None = filter_params['ai_status'],
                  ai_risk: str | None = filter_params['ai_risk'], decision: str | None = filter_params['decision'],pillar_status: str | None = filter_params['pillar_status'],
                  q: str | None = Query(None, max_length=200), limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                  tenant=Depends(current_tenant)):
        scan = owned(scan_id, tenant)
        _, items = inventory(scan, tenant)
        selected = filtered(items, query_filters(provider, service_category, review_priority, ai_status, ai_risk, decision, pillar_status), q)
        return dict(scan_id=scan['scan_id'], observed_at=scan.get('timestamp'), summary=dict(summary(items),**scan.get('_lifecycle_comparison',{})),commitment_baseline=planning_summary(scan),
                    total=len(selected), items=selected[offset:offset + limit])

    @router.get('/scans/{scan_id}/resources/export')
    def export(scan_id: UUID, provider: str | None = filter_params['provider'],
               service_category: str | None = filter_params['service_category'],
               review_priority: str | None = filter_params['review_priority'], ai_status: str | None = filter_params['ai_status'],
               ai_risk: str | None = filter_params['ai_risk'], decision: str | None = filter_params['decision'],pillar_status: str | None = filter_params['pillar_status'],
               q: str | None = Query(None, max_length=200), tenant=Depends(current_tenant)):
        scan = owned(scan_id, tenant)
        _, items = inventory(scan, tenant)
        selected = filtered(items, query_filters(provider, service_category, review_priority, ai_status, ai_risk, decision, pillar_status), q)
        return dict(filename=f"cloudsaver-resources-{scan['scan_id']}.csv", rows=len(selected), content=csv_report(selected))

    @router.get('/scans/{scan_id}/resources/{resource_key}')
    def resource(scan_id: UUID, resource_key: str = Path(pattern=KEY), tenant=Depends(current_tenant)):
        scan = owned(scan_id, tenant)
        findings, assessment, context = one(scan, resource_key)
        result = repo.results(tenant['tenant_id'], {resource_key}).get(resource_key)
        state = repo.item_states(tenant['tenant_id'], scan['scan_id']).get(resource_key)
        decision = repo.latest_decisions(tenant['tenant_id'], {resource_key}).get(resource_key)
        followups = repo.followups(tenant['tenant_id'], scan['scan_id'], resource_key)
        normalize_id = lambda value: value.lower() if assessment['provider'] == 'azure' else value
        selected_id = normalize_id(assessment['resource_id'])
        observation = next((row for row in scan.get('inventory', []) if row.get('cloud_provider', 'azure') == assessment['provider']
                            and normalize_id(row['resource_id']) == selected_id), None)
        evaluations = [row for row in scan.get('rule_evaluations', []) if row.get('cloud_provider', 'azure') == assessment['provider']
                       and normalize_id(row['resource_id']) == selected_id]
        groups = {row['opportunity_group_id'] for row in findings if row.get('opportunity_group_id')}
        overlaps = [dict(resource_id=row['resource_id'], resource_name=row.get('resource_name'), rule_id=row['rule_id'])
                    for row in scan['findings'] if row.get('opportunity_group_id') in groups and normalize_id(row['resource_id']) != selected_id]
        from app.pricing import opportunity_totals
        costs = dict(billed_cost_usd=assessment.get('billed_cost_usd'), effective_cost_usd=assessment.get('effective_cost_usd'),retail_estimate_usd=assessment['retail_estimate_usd'], modeled_future_cost_usd=None,
                     opportunity_usd=opportunity_totals(findings, realized=True)['total_monthly_opportunity_usd'],
                     verified_realized_savings_usd=None, currency='USD',
                     explanation='Billed/effective values are exact resource-period USD FOCUS imports where available; inspect coverage. Retail opportunities are estimates and post-change savings remain unverified.')
        return dict(scan_id=scan['scan_id'], assessment=assessment, findings=findings, ai_context=context,
                    ai=ai_state(assessment, result, state), ai_result=result['response'] if result else None,
                    decision=decision_state(assessment, decision), followups=followups,
                    followups_remaining=max(0, MAX_QUESTIONS - len(followups)), observation=observation,
                    rule_evaluations=evaluations, costs=costs, financial_overlaps=overlaps)

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
        merged = assessments(scan)
        if body.all:
            keys = sorted(merged)
        else:
            keys = list(dict.fromkeys(body.resource_keys))
            if any(not re.fullmatch(KEY, k) or k not in merged for k in keys):
                raise HTTPException(404, 'One or more selected resources are not in this scan')
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
