"""Grafana → Mimir Kubernetes rightsizing (advisory, read-only)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.auth import Role, require_workspace_role
from app.collectors.grafana_rightsizing import probe, validate_connector
from app.collectors.observability import check_url
from app.grafana_k8s_store import GrafanaK8sStore
from app.kubernetes_grafana_schemas import ConnectorUpdateEnvelope, RightsizingRunRequest
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
        raw = await bounded_json(request)
        try:
            envelope = ConnectorUpdateEnvelope.model_validate(raw)
        except ValidationError as error:
            raise HTTPException(422, str(error.errors()[0]['msg'])) from None
        try:
            config = validate_connector(envelope.connector, tenant)
            await run_in_threadpool(check_url, config['base_url'])
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        if repo.connector(tenant['tenant_id'], str(connector_id)) is None:
            raise HTTPException(404, 'Connector not found')
        version = envelope.version
        try:
            item = await run_in_threadpool(repo.connectors.update, tenant, str(connector_id), config, version, expected_kind='grafana_mimir')
        except WorkflowConflict as error:
            raise HTTPException(409, str(error)) from None
        if item is None or item.get('kind') != 'grafana_mimir':
            raise HTTPException(404, 'Connector not found')
        return item

    @router.post('/rightsizing/run', status_code=202)
    async def run_rightsizing(request: Request, response: Response, tenant=Depends(admin)):
        raw = await bounded_json(request)
        if not isinstance(raw, dict):
            raise HTTPException(422, 'Request body must be a JSON object.')
        try:
            body = RightsizingRunRequest.model_validate(raw)
        except ValidationError as error:
            raise HTTPException(422, str(error.errors()[0]['msg'])) from None
        try:
            job = await run_in_threadpool(
                repo.submit, tenant, str(body.idempotency_key), str(body.connector_id),
                cluster=body.cluster, window_days=body.window_days,
            )
        except WorkflowConflict as error:
            raise HTTPException(409, str(error)) from None
        response.headers['Location'] = job['poll_url']
        if job['status'] in ('queued', 'running'):
            response.headers['Retry-After'] = '3'
        return job

    @router.get('/rightsizing/jobs/{job_id}')
    async def job(job_id: UUID, response: Response, tenant=Depends(reader)):
        result = repo.job(tenant['tenant_id'], str(job_id))
        if result is None:
            raise HTTPException(404, 'Job not found')
        if result['status'] in ('queued', 'running'):
            response.headers['Retry-After'] = '3'
        return result

    return router
