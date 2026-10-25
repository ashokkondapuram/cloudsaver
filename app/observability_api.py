"""Observability connector management, collection jobs and summaries. Providers are read only by the worker or an explicit test."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from app.auth import Role, require_workspace_role
from app.schemas import bounded_json
from app.observability_store import ObservabilityStore
from app.v150_store import WorkflowConflict


def create_router(store, current_tenant):
    router = APIRouter(prefix='/api/v1/observability', tags=['Observability'])
    repo = ObservabilityStore(store)

    def admin(tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        return tenant

    def reader(tenant=Depends(current_tenant)):
        if Role.BILLING_ADMIN.value not in tenant.get('roles', []):
            require_workspace_role(tenant, Role.TENANT_ADMIN)
        return tenant

    async def definition(request, tenant):
        from app.collectors.observability import check_url, validate
        raw = await bounded_json(request)
        try:
            config = validate(raw.get('connector') if isinstance(raw, dict) and 'connector' in raw else raw, tenant)
            await run_in_threadpool(check_url, config['base_url'])
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        return raw, config

    def found(item):
        if item is None:
            raise HTTPException(404, 'Connector not found')
        return item

    @router.get('/connectors')
    def connectors(tenant=Depends(reader)):
        return dict(items=repo.connectors(tenant['tenant_id']))

    @router.post('/connectors', status_code=201)
    async def create(request: Request, tenant=Depends(admin)):
        _, config = await definition(request, tenant)
        try:
            return await run_in_threadpool(repo.create, tenant, config)
        except WorkflowConflict as error:
            raise HTTPException(409, str(error)) from None

    @router.post('/connectors/test')
    async def test_draft(request: Request, tenant=Depends(admin)):
        _, config = await definition(request, tenant)
        return await run_in_threadpool(probe, config, tenant)

    @router.post('/connectors/{connector_id}')
    async def update(connector_id: UUID, request: Request, tenant=Depends(admin)):
        raw, config = await definition(request, tenant)
        version = raw.get('version') if isinstance(raw, dict) else None
        if type(version) is not int:
            raise HTTPException(422, 'Include the connector version you edited.')
        try:
            return found(await run_in_threadpool(repo.update, tenant, str(connector_id), config, version))
        except WorkflowConflict as error:
            raise HTTPException(409, str(error)) from None

    @router.post('/connectors/{connector_id}/disable')
    def disable(connector_id: UUID, tenant=Depends(admin)):
        return found(repo.set_enabled(tenant['tenant_id'], str(connector_id), False))

    @router.post('/connectors/{connector_id}/enable')
    def enable(connector_id: UUID, tenant=Depends(admin)):
        return found(repo.set_enabled(tenant['tenant_id'], str(connector_id), True))

    @router.post('/connectors/{connector_id}/test')
    async def test(connector_id: UUID, tenant=Depends(admin)):
        connector = found(repo.connector(tenant['tenant_id'], str(connector_id)))
        return await run_in_threadpool(probe, connector, tenant)

    @router.post('/sync', status_code=202)
    async def sync(request: Request, response: Response, tenant=Depends(admin)):
        raw = await bounded_json(request)
        try:
            key = str(UUID(str((raw or {}).get('idempotency_key'))))
        except ValueError:
            raise HTTPException(422, 'A UUID idempotency_key is required.') from None
        try:
            job = await run_in_threadpool(repo.submit, tenant, key)
        except WorkflowConflict as error:
            raise HTTPException(409, str(error)) from None
        response.headers['Location'] = job['poll_url']
        response.headers['Retry-After'] = '3'
        return job

    @router.get('/sync-jobs/{job_id}')
    def job(job_id: UUID, response: Response, tenant=Depends(admin)):
        result = repo.job(tenant['tenant_id'], str(job_id))
        if result is None:
            raise HTTPException(404, 'Collection job not found')
        if result['status'] in ('queued', 'running'):
            response.headers['Retry-After'] = '3'
        return result

    @router.get('/summary')
    def summary(tenant=Depends(current_tenant)):
        return repo.summary(tenant['tenant_id'])

    return router


def probe(connector, tenant):
    """One bounded read: one query or service over the last hour. Nothing is stored."""
    from app.collectors.observability import SourceError, collect, message
    try:
        result = collect(connector, tenant, probe=True)
    except SourceError as error:
        return dict(ok=False, error_code=error.code, message=message(error.code))
    except Exception:
        return dict(ok=False, error_code='OBSERVABILITY_SOURCE_UNAVAILABLE', message=message('OBSERVABILITY_SOURCE_UNAVAILABLE'))
    coverage = result['mapping_coverage']
    if connector['kind'] in ('prometheus', 'rest_metrics'):
        detail = f"{coverage['series']:,} series returned, {coverage['labeled']:,} with the resource label."
    else:
        detail = f"{coverage['services']:,} service read, {coverage['mapped_services']:,} linked to a resource."
    return dict(ok=True, message='Connection works. ' + detail, mapping_coverage=coverage, warnings=result['warnings'])
