"""Grafana → Mimir Kubernetes rightsizing (advisory, read-only)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from app.auth import Role, require_workspace_role
from app.collectors.grafana_rightsizing import probe, validate_connector
from app.collectors.observability import check_url
from app.grafana_k8s_store import GrafanaK8sStore
from app.schemas import bounded_json
from app.v150_store import WorkflowConflict


def create_router(store, current_tenant):
    router = APIRouter(prefix='/api/v1/kubernetes/grafana', tags=['Kubernetes Grafana'])
    repo = GrafanaK8sStore(store)

    def admin(tenant=Depends(current_tenant)):
        require_workspace_role(tenant, Role.TENANT_ADMIN)
        return tenant

    def reader(tenant=Depends(current_tenant)):
        if Role.BILLING_ADMIN.value not in tenant.get('roles', []):
            require_workspace_role(tenant, Role.TENANT_ADMIN)
        return tenant

    async def parse_connector(request, tenant):
        raw = await bounded_json(request)
        body = raw.get('connector') if isinstance(raw, dict) and 'connector' in raw else raw
        try:
            config = validate_connector(body, tenant)
            await run_in_threadpool(check_url, config['base_url'])
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        return raw, config

    @router.get('/connectors')
    def connectors(tenant=Depends(reader)):
        return dict(items=repo.list_connectors(tenant['tenant_id']))

    @router.post('/connectors', status_code=201)
    async def create(request: Request, tenant=Depends(admin)):
        _, config = await parse_connector(request, tenant)
        try:
            return await run_in_threadpool(repo.connectors.create, tenant, config)
        except WorkflowConflict as error:
            raise HTTPException(409, str(error)) from None

    @router.post('/connectors/test')
    async def test_draft(request: Request, tenant=Depends(admin)):
        _, config = await parse_connector(request, tenant)
        return await run_in_threadpool(probe, config)

    @router.post('/connectors/{connector_id}/test')
    async def test_saved(connector_id: UUID, tenant=Depends(admin)):
        connector = repo.connector(tenant['tenant_id'], str(connector_id))
        if connector is None:
            raise HTTPException(404, 'Connector not found')
        return await run_in_threadpool(probe, connector)

    @router.post('/connectors/{connector_id}')
    async def update(connector_id: UUID, request: Request, tenant=Depends(admin)):
        raw, config = await parse_connector(request, tenant)
        version = raw.get('version') if isinstance(raw, dict) else None
        if type(version) is not int:
            raise HTTPException(422, 'Include the connector version you edited.')
        try:
            item = await run_in_threadpool(repo.connectors.update, tenant, str(connector_id), config, version)
        except WorkflowConflict as error:
            raise HTTPException(409, str(error)) from None
        if item is None or item.get('kind') != 'grafana_mimir':
            raise HTTPException(404, 'Connector not found')
        return item

    @router.post('/rightsizing/run', status_code=202)
    async def run_rightsizing(request: Request, response: Response, tenant=Depends(admin)):
        raw = await bounded_json(request)
        try:
            key = str(UUID(str((raw or {}).get('idempotency_key'))))
            connector_id = str(UUID(str((raw or {}).get('connector_id'))))
        except ValueError:
            raise HTTPException(422, 'connector_id and a UUID idempotency_key are required.') from None
        cluster = (raw or {}).get('cluster')
        if cluster is not None and not isinstance(cluster, str):
            raise HTTPException(422, 'cluster must be a string when provided.')
        window_days = (raw or {}).get('window_days', 14)
        if type(window_days) is not int or not 1 <= window_days <= 30:
            raise HTTPException(422, 'window_days must be 1–30.')
        try:
            job = await run_in_threadpool(repo.submit, tenant, key, connector_id, cluster=cluster, window_days=window_days)
        except WorkflowConflict as error:
            raise HTTPException(409, str(error)) from None
        job = await run_in_threadpool(repo.execute, tenant, job['id'])
        response.headers['Location'] = job['poll_url']
        response.headers['Retry-After'] = '3'
        return job

    @router.get('/rightsizing/jobs/{job_id}')
    async def job(job_id: UUID, response: Response, tenant=Depends(reader)):
        result = repo.job(tenant['tenant_id'], str(job_id))
        if result is None:
            raise HTTPException(404, 'Job not found')
        if result['status'] == 'queued':
            result = await run_in_threadpool(repo.execute, tenant, str(job_id))
        if result['status'] in ('queued', 'running'):
            response.headers['Retry-After'] = '3'
        return result

    return router
