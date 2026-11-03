"""Explicit normalized billing ingestion; tenant-owned, finance-authorized access."""
from datetime import date, datetime, timezone
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from uuid import UUID
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from app.auth import Role, require_workspace_role
from app.focus import FocusError, FocusRepository, ImportRequest, money
from app.schemas import bounded_json


def create_router(repository, current_tenant, *, scan_store=None):
    router=APIRouter(prefix='/api/v1/finops',tags=['Billing evidence'])

    def finance(tenant=Depends(current_tenant)):
        require_workspace_role(tenant,Role.BILLING_ADMIN)
        return tenant

    @router.post('/sync',status_code=202)
    async def sync(request:Request,response:Response,currency:str=Query('USD',pattern=r'^[A-Z]{3}$'),tenant=Depends(finance)):
        from app.billing_jobs import BillingJobs
        from app.v150_store import WorkflowConflict
        raw=await bounded_json(request)
        try:
            if not isinstance(raw,dict) or set(raw)!={'idempotency_key'}:raise ValueError()
            key=str(UUID(raw['idempotency_key']))
        except (ValueError,TypeError,KeyError):raise HTTPException(422,'Provide a UUID idempotency_key') from None
        try:result=await run_in_threadpool(BillingJobs(repository.store).submit,tenant,key,currency)
        except FocusError as error:raise HTTPException(error.status,str(error)) from None
        except WorkflowConflict as error:raise HTTPException(409,str(error)) from None
        response.headers['Location']=result['poll_url'];response.headers['Retry-After']='3'
        return result

    @router.get('/sync-jobs/{job_id}')
    def sync_job(job_id:UUID,response:Response,tenant=Depends(finance)):
        from app.billing_jobs import BillingJobs
        result=BillingJobs(repository.store).get(tenant['tenant_id'],str(job_id))
        if result is None:raise HTTPException(404,'Billing job not found')
        if result['status'] in ('queued','running','cancel_requested'):response.headers['Retry-After']='3'
        return result

    @router.post('/sync-jobs/{job_id}/cancel')
    def cancel_sync(job_id:UUID,tenant=Depends(finance)):
        from app.billing_jobs import BillingJobs
        result=BillingJobs(repository.store).cancel(tenant['tenant_id'],str(job_id))
        if result is None:raise HTTPException(404,'Billing job not found')
        return result

    @router.get('/sync-status')
    def billing_sync_status(tenant=Depends(finance)):
        from app.collectors.billing_sync import sync_status
        try:return sync_status(tenant,repository)
        except (ValueError,KeyError,TypeError):
            raise HTTPException(503,'Billing connector configuration is unavailable') from None

    @router.get('/commitments')
    def commitments(tenant=Depends(finance)):
        from app import commitment_store
        from app.collectors.commitments import summarize
        scopes=commitment_store.latest(repository.store,tenant['tenant_id'])
        items=[dict(item,scope_id=scope['scope_id']) for scope in scopes for item in scope.get('items') or []]
        return dict(items=items,summary=summarize(items),
                    scopes=[{key:scope.get(key) for key in ('provider','scope_id','status','observed_at','coverage','warnings','error_code','period_start','period_end')} for scope in scopes])

    @router.post('/imports',status_code=201)
    async def import_evidence(request:Request,tenant=Depends(finance)):
        try:
            payload=ImportRequest.model_validate(await bounded_json(request))
        except (ValidationError,ValueError):
            raise HTTPException(422,'Invalid normalized billing import; check schema, decimal strings, scope and charge periods') from None
        try:
            return await run_in_threadpool(repository.import_records,tenant,payload)
        except FocusError as error:
            raise HTTPException(error.status,str(error)) from None

    @router.get('/imports')
    def import_history(limit:int=Query(25,ge=1,le=100),tenant=Depends(finance)):
        return dict(items=repository.imports(tenant,limit))

    @router.get('/summary')
    def summary(start:date|None=None,end:date|None=None,currency:str=Query('USD',pattern=r'^[A-Z]{3}$'),
                budget:str|None=None,tenant=Depends(finance)):
        today=datetime.now(timezone.utc).date()
        start,end=start or today.replace(day=1),end or today
        if not 0<(end-start).days<=366:
            raise HTTPException(422,'Select a billing window from 1 to 366 UTC days')
        try:
            if budget is not None:
                budget=money(budget)
                if budget.startswith('-'): raise ValueError('Budget cannot be negative')
            return repository.summary(tenant,start,end,currency,budget)
        except (FocusError,ValueError) as error:
            raise HTTPException(error.status if isinstance(error,FocusError) else 422,
                                str(error) if isinstance(error,FocusError) else 'Budget must be a nonnegative decimal string') from None

    def _azure_resource_binding(tenant, scope_id: str, resource_id: str):
        from app.collectors.billing_sync import bindings

        selected = bindings(tenant)
        binding = next(
            (b for b in selected if b['provider'] == 'azure' and b['scope_id'] == scope_id),
            None,
        )
        if not binding:
            raise HTTPException(403, 'This Azure subscription is not an authorized billing scope')
        if not resource_id.lower().startswith(f'/subscriptions/{scope_id}/'.lower()):
            raise HTTPException(422, 'resource_id must belong to the given subscription scope')
        return binding

    @router.get('/azure-rest-catalog')
    def azure_rest_catalog(tenant=Depends(finance)):
        from app.azure_rest_catalog import catalog_operations

        return dict(items=catalog_operations())

    @router.get('/azure-resource-costs')
    async def azure_resource_costs(
        resource_id: str = Query(..., min_length=1, max_length=300),
        scope_id: str = Query(..., min_length=1, max_length=64),
        start: date = Query(..., description='Observation window start (UTC, inclusive)'),
        end: date = Query(..., description='Observation window end (UTC, exclusive)'),
        baseline_start: date | None = None,
        baseline_end: date | None = None,
        scan_id: UUID | None = None,
        persist: bool = False,
        tenant=Depends(finance),
    ):
        from app.azure_json_profile import fetch_azure_resource_profile
        from app.collectors.billing_sync import azure_resource_rows, _import_snapshot

        _azure_resource_binding(tenant, scope_id, resource_id)
        if (baseline_start is None) ^ (baseline_end is None):
            raise HTTPException(422, 'Provide both baseline_start and baseline_end, or neither')
        findings = None
        if scan_id is not None and scan_store is not None:
            scan = scan_store.get(tenant['tenant_id'], str(scan_id))
            if scan is None:
                raise HTTPException(404, 'Owned scan not found')
            normalize = resource_id.lower()
            findings = [
                row
                for row in scan.get('findings') or []
                if row.get('cloud_provider', 'azure') == 'azure'
                and row.get('resource_id', '').lower() == normalize
            ]
        try:
            snapshot = await run_in_threadpool(
                fetch_azure_resource_profile,
                tenant=tenant,
                scope_id=scope_id,
                resource_id=resource_id,
                observation_start=start,
                observation_end=end,
                baseline_start=baseline_start,
                baseline_end=baseline_end,
                scan_id=scan_id,
                scan_store=scan_store,
                evidence_store=repository.store,
                findings=findings,
                fetch_rows=azure_resource_rows,
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        except FocusError as error:
            raise HTTPException(error.status, str(error)) from None
        except Exception:
            raise HTTPException(503, 'Azure resource billing is unavailable right now') from None
        if persist:
            binding = _azure_resource_binding(tenant, scope_id, resource_id)
            currency = snapshot['cost_management']['observation'].get('currency') or 'USD'
            obs_rows = await run_in_threadpool(
                azure_resource_rows, scope_id, resource_id, tenant, start, end
            )
            imported = await run_in_threadpool(
                _import_snapshot,
                repository,
                tenant,
                binding,
                [row for row in obs_rows if row['currency'] == currency],
                start,
                end,
                currency,
            )
            snapshot['persisted'] = dict(inserted=imported['inserted'], currency=currency)
        else:
            snapshot['persisted'] = None
        return snapshot

    @router.post('/resource-cost')
    async def resource_cost(
        resource_id: str = Query(..., min_length=1, max_length=300),
        scope_id: str = Query(..., min_length=1, max_length=64),
        start: date | None = None,
        end: date | None = None,
        tenant=Depends(finance),
    ):
        from app.collectors.billing_sync import azure_resource_rows, _import_snapshot
        from datetime import timedelta

        binding = _azure_resource_binding(tenant, scope_id, resource_id)
        if start is None or end is None:
            end = datetime.now(timezone.utc).date()
            start = end - timedelta(days=30)
        else:
            try:
                from app.azure_resource_finops import validate_window

                validate_window(start, end)
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
        try:
            rows = await run_in_threadpool(azure_resource_rows, scope_id, resource_id, tenant, start, end)
        except FocusError as error:
            raise HTTPException(error.status, str(error)) from None
        except Exception:
            raise HTTPException(503, 'Resource cost is unavailable right now') from None
        currencies = sorted({r['currency'] for r in rows})
        imported = [
            await run_in_threadpool(_import_snapshot, repository, tenant, binding, rows, start, end, c)
            for c in currencies
        ]
        return dict(
            resource_id=resource_id,
            rows=len(rows),
            currencies=currencies,
            inserted=sum(x['inserted'] for x in imported),
            window_start=start.isoformat(),
            window_end=end.isoformat(),
        )

    @router.get('/unit-economics/preview')
    def unit_economics_preview(
        prior_cost: str = Query(..., min_length=1, max_length=32),
        current_cost: str = Query(..., min_length=1, max_length=32),
        prior_volume: str = Query(..., min_length=1, max_length=32),
        current_volume: str = Query(..., min_length=1, max_length=32),
        tenant=Depends(finance),
    ):
        from app.unit_economics import compute_elasticity_ratio
        try:
            return compute_elasticity_ratio(prior_cost, current_cost, prior_volume, current_volume)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @router.get('/saas-connectors')
    def saas_connectors(tenant=Depends(finance)):
        from app.finops_saas_focus_connectors import connector_capabilities

        return dict(items=connector_capabilities())

    @router.post('/ebpf-flows/ingest', status_code=202)
    async def ingest_ebpf_flows(request: Request, tenant=Depends(finance)):
        from app.collectors_ebpf_flow import normalize_flow_record
        from app.v3_finops_store import V3FinOpsStore

        raw = await bounded_json(request)
        if not isinstance(raw, dict) or "records" not in raw or not isinstance(raw["records"], list):
            raise HTTPException(422, "Provide records array")
        try:
            normalized = [normalize_flow_record(item) for item in raw["records"][:500]]
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(422, str(error)) from None
        persisted = await run_in_threadpool(
            V3FinOpsStore(repository.store).insert_ebpf_flows, tenant["tenant_id"], normalized
        )
        return dict(accepted=len(normalized), **persisted)

    @router.post('/saas-focus/import', status_code=201)
    async def import_saas_focus(request: Request, tenant=Depends(finance)):
        from app.finops_saas_focus_connectors import normalize_focus_record
        from app.v3_finops_store import V3FinOpsStore

        raw = await bounded_json(request)
        if not isinstance(raw, dict) or "provider" not in raw or "records" not in raw:
            raise HTTPException(422, "Provide provider and records array")
        provider = str(raw["provider"])
        records = raw["records"]
        if not isinstance(records, list):
            raise HTTPException(422, "records must be an array")
        try:
            normalized = [normalize_focus_record(provider, item) for item in records[:500]]
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(422, str(error)) from None
        persisted = await run_in_threadpool(
            V3FinOpsStore(repository.store).insert_saas_focus_records, tenant["tenant_id"], normalized
        )
        return dict(accepted=len(normalized), **persisted)

    @router.get('/commitment-ladder/preview')
    def commitment_ladder_preview(
        raw_p10_hr: str = Query(..., pattern=r'^\d+(\.\d+)?$'),
        waste_hr: str = Query(..., pattern=r'^\d+(\.\d+)?$'),
        existing_hr: str = Query(..., pattern=r'^\d+(\.\d+)?$'),
        tenant=Depends(finance),
    ):
        from app.autopilot_commitments import commitment_ladder
        from app.commitment_arbitrage import calculate_clean_commitment_baseline

        baseline = calculate_clean_commitment_baseline(raw_p10_hr, waste_hr, existing_hr)
        steps = commitment_ladder(raw_p10_hr, waste_hr, existing_hr)
        return dict(status='computed', purchase_authorized=False, baseline=baseline, steps=steps)

    @router.get('/spot-arbitrage/preview')
    def spot_arbitrage_preview(
        unused_commitment_usd_hr: str = Query(..., max_length=32),
        spot_interruption_score: str = Query(..., max_length=32),
        on_demand_usd_hr: str = Query(..., max_length=32),
        tenant=Depends(finance),
    ):
        from app.finops_spot_arbitrage import arbitrage_node_pool_capacity

        try:
            return arbitrage_node_pool_capacity(
                unused_commitment_usd_hr=unused_commitment_usd_hr,
                spot_interruption_score=spot_interruption_score,
                on_demand_usd_hr=on_demand_usd_hr,
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    return router
