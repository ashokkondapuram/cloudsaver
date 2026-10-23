"""identity-service: internal verify API, directory change feed and the platform portal admin API."""
import logging
import os
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from identity.auth import ADMIN_CALLERS, DIRECTORY_CALLERS, VERIFY_CALLERS, OperatorAuth, caller_dependency, load_callers
from identity.domain import IdentityError, Throttled
from identity.keys import key_prefix

logger = logging.getLogger('cloudsaver.identity')
MAX_BODY = 1_048_576


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str = Field(max_length=256)
    client_ip: str = Field(max_length=64)
    request_id: str | None = Field(None, max_length=64)


def build_service():
    from identity.events import RedisEvents
    from identity.keys import Peppers
    from identity.service import IdentityService
    from identity.store_postgres import PostgresStore
    from identity.throttle import RedisBackend, Throttle
    from identity.usage import UsageRecorder
    url = os.getenv('CLOUDSAVER_IDENTITY_DATABASE_URL')
    if not url:
        raise RuntimeError('Set CLOUDSAVER_IDENTITY_DATABASE_URL')
    return IdentityService(PostgresStore(url), Peppers.from_env(), Throttle(RedisBackend()), RedisEvents(), UsageRecorder())


def problem(request, status, detail, headers=None):
    return JSONResponse({'type': 'about:blank', 'status': status, 'detail': detail, 'instance': request.url.path},
                        status_code=status, media_type='application/problem+json', headers=headers)


def create_app(service=None, callers=None, operator_auth=None, flush_interval=30):
    from app.runtime import install_log_redaction
    install_log_redaction()
    service = service or build_service()
    callers = callers if callers is not None else load_callers()
    operator_auth = operator_auth or OperatorAuth()

    @asynccontextmanager
    async def lifespan(_):
        from identity.usage import Flusher
        flusher = Flusher(service.usage, service.store, flush_interval)
        flusher.start()
        yield
        flusher.stop()

    app = FastAPI(title='identity-service', version='1.2.0', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service
    verify_caller = caller_dependency(callers, VERIFY_CALLERS)
    directory_caller = caller_dependency(callers, DIRECTORY_CALLERS)
    any_caller = caller_dependency(callers, VERIFY_CALLERS | DIRECTORY_CALLERS | ADMIN_CALLERS)
    portal_caller = caller_dependency(callers, ADMIN_CALLERS)
    operator_dependency = operator_auth.dependency()

    def operator(caller=Depends(portal_caller), identity=Depends(operator_dependency)):
        return identity

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return problem(request, exc.status_code, exc.detail, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo the request: the verify body contains a key.
        return problem(request, 422, 'Invalid or unsupported request')

    @app.exception_handler(IdentityError)
    async def identity_error(request, exc):
        headers = {'Retry-After': str(exc.retry_after)} if isinstance(exc, Throttled) else None
        return problem(request, exc.status, exc.detail, headers)

    @app.middleware('http')
    async def guard(request, call_next):
        if int(request.headers.get('content-length') or 0) > MAX_BODY:
            return problem(request, 413, 'Request body is too large')
        try:
            rid = str(UUID(request.headers.get('X-Request-ID', '')))
        except ValueError:
            rid = str(uuid4())
        request.state.request_id = rid
        try:
            response = await call_next(request)
        except Exception:
            logger.error('Unhandled identity request failure request_id=%s', rid)
            response = problem(request, 500, 'The service could not complete the request')
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'X-Frame-Options': 'DENY', 'X-Request-ID': rid})
        return response

    def rid(request):
        return request.state.request_id

    @app.get('/healthz')
    def health():
        return {'status': 'healthy', 'service': 'identity-service'}

    @app.get('/readyz')
    def ready():
        try:
            service.get_platform()
            return {'status': 'ready'}
        except Exception:
            return JSONResponse({'status': 'unready'}, status_code=503)

    # ----- internal ----------------------------------------------------------------------------------
    @app.post('/internal/v1/keys/verify')
    def verify(request: Request, payload: VerifyRequest, caller=Depends(verify_caller)):
        return service.verify(payload.key, payload.client_ip, caller, payload.request_id or rid(request))

    @app.get('/internal/v1/directory/changes')
    def changes(after: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=500), caller=Depends(directory_caller)):
        return service.changes(after, limit)

    @app.get('/internal/v1/directory/snapshot')
    def directory_snapshot(caller=Depends(directory_caller)):
        return service.directory_snapshot()

    @app.get('/internal/v1/metrics')
    def metrics(caller=Depends(any_caller)):
        return {'verify': [{'result': labels[1], 'caller': labels[2], 'count': count}
                           for labels, count in sorted(service.metrics.items()) if labels[0] == 'verify']}

    # ----- portal admin API --------------------------------------------------------------------------
    @app.get('/admin/v1/session')
    def session(identity=Depends(operator)):
        return {'actor': identity['actor'], 'display_name': identity['display_name'], 'roles': identity['roles'],
                'auth_mode': identity['auth_mode'], 'provider_scoped_keys': service.provider_scoped_keys,
                'environment': service.environment, 'key_prefix': key_prefix(service.environment)}

    @app.get('/admin/v1/customers')
    def customers(q: str | None = Query(None, max_length=120), status: str | None = None, cursor: str | None = None,
                  limit: int = Query(50, ge=1, le=200), identity=Depends(operator)):
        return service.list_customers(q, status, cursor, limit)

    @app.post('/admin/v1/customers', status_code=201)
    def create_customer(request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.create_customer(payload, identity, rid(request))

    @app.get('/admin/v1/customers/{customer_id}')
    def customer(customer_id: str, identity=Depends(operator)):
        return service.get_customer(customer_id)

    @app.patch('/admin/v1/customers/{customer_id}')
    def update_customer(customer_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_customer(customer_id, payload, identity, rid(request))

    @app.delete('/admin/v1/customers/{customer_id}')
    def delete_customer(customer_id: str, request: Request, version: int = Query(..., ge=0), identity=Depends(operator)):
        return service.set_customer_status(customer_id, {'version': version}, 'deleted', identity, rid(request))

    @app.post('/admin/v1/customers/{customer_id}/suspend')
    def suspend_customer(customer_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.set_customer_status(customer_id, payload, 'suspended', identity, rid(request))

    @app.post('/admin/v1/customers/{customer_id}/reactivate')
    def reactivate_customer(customer_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.set_customer_status(customer_id, payload, 'active', identity, rid(request))

    @app.get('/admin/v1/workspaces')
    def workspaces(q: str | None = Query(None, max_length=120), status: str | None = None, customer_id: str | None = None,
                   cursor: str | None = None, limit: int = Query(50, ge=1, le=200), identity=Depends(operator)):
        return service.list_workspaces(q, status, customer_id, cursor, limit)

    @app.post('/admin/v1/workspaces', status_code=201)
    def create_workspace(request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.create_workspace(payload, identity, rid(request))

    @app.get('/admin/v1/workspaces/{tenant_id}')
    def workspace(tenant_id: str, identity=Depends(operator)):
        return service.get_workspace(tenant_id)

    @app.patch('/admin/v1/workspaces/{tenant_id}')
    def update_workspace(tenant_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_workspace(tenant_id, payload, identity, rid(request))

    @app.put('/admin/v1/workspaces/{tenant_id}/scopes/{provider}')
    def replace_scopes(tenant_id: str, provider: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.replace_scopes(tenant_id, provider, payload, identity, rid(request))

    @app.post('/admin/v1/workspaces/{tenant_id}/suspend')
    def suspend_workspace(tenant_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.set_workspace_status(tenant_id, payload, 'suspended', identity, rid(request))

    @app.post('/admin/v1/workspaces/{tenant_id}/reactivate')
    def reactivate_workspace(tenant_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.set_workspace_status(tenant_id, payload, 'active', identity, rid(request))

    @app.delete('/admin/v1/workspaces/{tenant_id}')
    def delete_workspace(tenant_id: str, request: Request, version: int = Query(..., ge=0), identity=Depends(operator)):
        return service.set_workspace_status(tenant_id, {'version': version}, 'deleted', identity, rid(request))

    @app.get('/admin/v1/platform-settings')
    def platform(identity=Depends(operator)):
        return service.get_platform()

    @app.put('/admin/v1/platform-settings')
    def update_platform(request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_platform(payload, identity, rid(request))

    @app.get('/admin/v1/workspaces/{tenant_id}/keys')
    def keys(tenant_id: str, identity=Depends(operator)):
        return service.list_keys(tenant_id)

    @app.post('/admin/v1/workspaces/{tenant_id}/keys', status_code=201)
    def issue_key(tenant_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.issue_key(tenant_id, payload, identity, rid(request))

    @app.post('/admin/v1/workspaces/{tenant_id}/keys/revoke-all')
    def revoke_all(tenant_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.revoke_all(tenant_id, payload, identity, rid(request))

    @app.get('/admin/v1/workspaces/{tenant_id}/usage')
    def workspace_usage(tenant_id: str, start: str | None = Query(None, alias='from'), end: str | None = Query(None, alias='to'),
                        identity=Depends(operator)):
        return service.workspace_usage(tenant_id, start, end)

    @app.get('/admin/v1/keys/{key_id}')
    def key(key_id: str, identity=Depends(operator)):
        return service.get_key(key_id)

    @app.patch('/admin/v1/keys/{key_id}')
    def update_key(key_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.update_key(key_id, payload, identity, rid(request))

    @app.post('/admin/v1/keys/{key_id}/rotate', status_code=201)
    def rotate_key(key_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.rotate_key(key_id, payload, identity, rid(request))

    @app.post('/admin/v1/keys/{key_id}/revoke')
    def revoke_key(key_id: str, request: Request, payload: dict = Body(...), identity=Depends(operator)):
        return service.revoke_key(key_id, payload, identity, rid(request))

    @app.get('/admin/v1/keys/{key_id}/usage')
    def key_usage(key_id: str, start: str | None = Query(None, alias='from'), end: str | None = Query(None, alias='to'),
                  identity=Depends(operator)):
        return service.key_usage(key_id, start, end)

    @app.get('/admin/v1/audit')
    def audit(customer_id: str | None = None, tenant_id: str | None = None, key_id: str | None = Query(None, max_length=12),
              actor: str | None = Query(None, max_length=120), action: str | None = Query(None, max_length=40),
              before: str | None = None, limit: int = Query(50, ge=1, le=200), identity=Depends(operator)):
        return service.audit({'customer_id': customer_id, 'tenant_id': tenant_id, 'key_id': key_id, 'actor': actor,
                              'action': action}, before, limit)

    @app.get('/admin/v1/failures')
    def failures(tenant_id: str | None = None, source_ip: str | None = Query(None, max_length=64),
                 reason: str | None = Query(None, max_length=24), start: str | None = Query(None, alias='from'),
                 identity=Depends(operator)):
        return service.failures({'tenant_id': tenant_id, 'source_ip': source_ip, 'reason': reason}, start)

    return app
